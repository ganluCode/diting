"""Cypher 文件加载、拆分、执行 — 支持元信息注释"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from diting.graph.client import GraphClient

logger = logging.getLogger(__name__)

# 元信息注释格式: // @key: value
_META_RE = re.compile(r"^//\s*@(\w+):\s*(.+)$")


@dataclass
class CypherFile:
    path: Path
    version: int = 0
    depends: list[str] = field(default_factory=list)
    creates: list[str] = field(default_factory=list)
    description: str = ""
    queries: list[tuple[str, str]] = field(default_factory=list)  # [(desc, cypher)]


@dataclass
class StepResult:
    file: str
    description: str
    count: Optional[int]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class EnhanceResult:
    steps: list[StepResult] = field(default_factory=list)
    verify_warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def summary(self) -> str:
        ok = sum(1 for s in self.steps if s.ok)
        return f"{ok}/{len(self.steps)} steps OK"


def parse_cypher_file(path: Path) -> CypherFile:
    """解析 .cypher 文件，提取元信息和查询列表"""
    content = path.read_text(encoding="utf-8")
    cf = CypherFile(path=path)

    lines = content.splitlines()
    non_comment_lines = []

    for line in lines:
        m = _META_RE.match(line.strip())
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "version":
                cf.version = int(val)
            elif key == "depends":
                cf.depends = [v.strip() for v in val.split(",")]
            elif key == "creates":
                cf.creates = [v.strip() for v in val.split(",")]
            elif key == "description":
                cf.description = val
            # skip meta lines
        elif line.strip().startswith("//"):
            # normal comment — skip for execution but keep for desc extraction
            non_comment_lines.append(line)
        else:
            non_comment_lines.append(line)

    # Split by ; into individual queries
    raw = "\n".join(non_comment_lines)
    parts = [p.strip() for p in raw.split(";") if p.strip()]

    for part in parts:
        # Use the first comment line as description, fallback to first 60 chars
        desc_match = re.search(r"//\s*(.+)", part)
        desc = desc_match.group(1).strip() if desc_match else part[:60].replace("\n", " ")
        # Remove inline comments from the actual cypher
        cypher = re.sub(r"//[^\n]*", "", part).strip()
        if cypher:
            cf.queries.append((desc, cypher))

    return cf


class CypherExecutor:
    """执行 .cypher 文件目录中的所有增强脚本"""

    def __init__(self, client: GraphClient):
        self.client = client

    async def run_directory(
        self,
        cypher_dir: Path,
        *,
        pattern: str = "[0-9]*.cypher",
        run_verify: bool = True,
    ) -> EnhanceResult:
        """
        按编号顺序执行目录中所有 Cypher 文件，然后执行 _verify.cypher（如存在）
        """
        result = EnhanceResult()
        files = sorted(cypher_dir.glob(pattern))

        if not files:
            logger.warning("No cypher files found in %s", cypher_dir)
            return result

        for cypher_file in files:
            logger.info("Running %s", cypher_file.name)
            cf = parse_cypher_file(cypher_file)

            for desc, query in cf.queries:
                step = await self._run_step(cypher_file.name, desc, query)
                result.steps.append(step)
                if step.ok:
                    logger.info("  %-40s %s", desc[:40], f"count={step.count}")
                else:
                    logger.error("  %-40s ERROR: %s", desc[:40], step.error)

        # Run verify script
        verify_file = cypher_dir / "_verify.cypher"
        if run_verify and verify_file.exists():
            warnings = await self._run_verify(verify_file)
            result.verify_warnings.extend(warnings)
            for w in warnings:
                logger.warning("VERIFY: %s", w)

        logger.info("Enhancement complete: %s", result.summary())
        return result

    async def run_file(self, cypher_file: Path) -> EnhanceResult:
        """执行单个 Cypher 文件"""
        result = EnhanceResult()
        cf = parse_cypher_file(cypher_file)
        for desc, query in cf.queries:
            step = await self._run_step(cypher_file.name, desc, query)
            result.steps.append(step)
        return result

    async def delete_relationships(self, rel_types: list[str]) -> dict[str, int]:
        """删除指定类型的所有关系（用于 --clean 模式）"""
        counts = {}
        for rel in rel_types:
            try:
                count = await self.client.run_scalar(
                    f"MATCH ()-[r:{rel}]->() DELETE r RETURN count(r) AS deleted"
                )
                counts[rel] = count or 0
                logger.info("Deleted %d %s relationships", counts[rel], rel)
            except Exception as e:
                logger.warning("Failed to delete %s: %s", rel, e)
                counts[rel] = -1
        return counts

    async def _run_step(self, filename: str, desc: str, query: str) -> StepResult:
        try:
            # Most enhancement queries RETURN count(*) as the last column
            row = await self.client.run_one(query)
            count = next(iter(row.values())) if row else 0
            return StepResult(file=filename, description=desc, count=count)
        except Exception as e:
            return StepResult(file=filename, description=desc, count=None, error=str(e))

    async def _run_verify(self, verify_file: Path) -> list[str]:
        """执行验证脚本，返回警告消息列表"""
        warnings = []
        cf = parse_cypher_file(verify_file)
        for desc, query in cf.queries:
            try:
                rows = await self.client.run(query)
                for row in rows:
                    msg = next(iter(row.values()), "")
                    if msg:
                        warnings.append(str(msg))
            except Exception as e:
                warnings.append(f"Verify error ({desc}): {e}")
        return warnings
