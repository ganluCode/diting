"""Java 扫描器 — jQAssistant 字节码扫描 + 项目标签"""
import logging
from pathlib import Path
from typing import Optional

from diting.graph.client import GraphClient
from diting.languages.base import ScanResult
from diting.languages.java.jqassistant import JQAssistant, find_scan_targets, count_class_files

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).parent / "tools"


class JavaScanner:
    def __init__(
        self,
        graph: GraphClient,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        jqa_version: str = "2.3.0",
    ):
        self.graph = graph
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.jqa = JQAssistant(_TOOLS_DIR, jqa_version)

    async def scan(
        self,
        project_path: Path,
        project_id: str,
        reset: bool = False,
    ) -> ScanResult:
        result = ScanResult(project_id=project_id, language="java")
        project_path = project_path.resolve()

        # 1. 确保 jQAssistant 已安装
        await self.jqa.ensure_installed()

        # 2. 查找编译产物
        targets = find_scan_targets(project_path)
        if not targets:
            result.errors.append(
                f"No compiled artifacts found. Run: mvn compile -DskipTests\n"
                f"  Looked in: {project_path}/target/classes"
            )
            return result

        total_class_files = sum(count_class_files(t) for t in targets)
        result.files_scanned = total_class_files
        logger.info("Found %d scan targets, %d class files", len(targets), total_class_files)

        # 3. 清理旧数据（保证幂等性）
        if not reset:
            await self._clean_project_data(project_id)

        # 4. 生成 jQA 配置
        config_file = _TOOLS_DIR.parent / ".jqassistant.yml"
        _TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        self.jqa.generate_config(
            scan_targets=targets,
            config_file=config_file,
            neo4j_uri=self.neo4j_uri,
            neo4j_user=self.neo4j_user,
            neo4j_password=self.neo4j_password,
            reset=reset,
        )

        # 5. 执行扫描
        cwd = config_file.parent
        logger.info("Running jQAssistant scan for project: %s", project_id)
        try:
            self.jqa.run_scan(cwd)
        except Exception as e:
            result.errors.append(f"jQAssistant scan failed: {e}")
            return result

        # 6. 执行 Spring 分析规则（允许部分失败）
        logger.info("Running jQAssistant analyze")
        self.jqa.run_analyze(cwd)

        # 7. 打项目标签
        tagged = await self._tag_project_nodes(project_path, project_id)
        logger.info("Tagged %d nodes with project=%s", tagged, project_id)

        # 8. 统计
        stats = await self._get_stats(project_id)
        result.nodes_written = stats.get("types", 0) + stats.get("methods", 0)
        result.details = stats

        return result

    async def _clean_project_data(self, project_id: str):
        """清理项目旧数据（确保幂等性）"""
        check = await self.graph.run_scalar(
            "MATCH (t:Java:Type {project: $p}) RETURN count(t)", p=project_id
        )
        if not check:
            logger.info("No existing data for project %s", project_id)
            return

        logger.info("Cleaning existing data for project %s (%d types)", project_id, check)

        for label, rel in [("Method", "DECLARES"), ("Field", "DECLARES")]:
            await self.graph.run(
                f"MATCH (t:Java:Type {{project: $p}})-[:{rel}]->(n:Java:{label}) "
                f"DETACH DELETE n",
                p=project_id,
            )
        await self.graph.run(
            "MATCH (t:Java:Type {project: $p}) DETACH DELETE t", p=project_id
        )
        # 清理孤儿 Artifact
        await self.graph.run(
            "MATCH (a:Artifact) WHERE NOT (a)-[:CONTAINS]->() DETACH DELETE a"
        )
        logger.info("Cleaned project %s", project_id)

    async def _tag_project_nodes(self, project_path: Path, project_id: str) -> int:
        """给该项目的 Type 节点打 project 标签（三级策略）"""
        # 策略1: Artifact.fileName 包含 /{project_id}/
        count = await self.graph.run_scalar(
            "MATCH (a:Artifact)-[:CONTAINS]->(t:Java:Type) "
            "WHERE a.fileName CONTAINS $pattern "
            "SET t.project = $pid RETURN count(t)",
            pattern=f"/{project_id}/", pid=project_id,
        )
        if count:
            return count

        # 策略2: Artifact.fileName 包含 project_path
        count = await self.graph.run_scalar(
            "MATCH (a:Artifact)-[:CONTAINS]->(t:Java:Type) "
            "WHERE a.fileName CONTAINS $path "
            "SET t.project = $pid RETURN count(t)",
            path=str(project_path), pid=project_id,
        )
        if count:
            return count

        # 策略3: 兜底 — 标记所有未打标签的节点
        logger.warning(
            "Artifact path matching failed, falling back to tagging all untagged nodes"
        )
        count = await self.graph.run_scalar(
            "MATCH (t:Java:Type) WHERE t.project IS NULL AND t.fqn IS NOT NULL "
            "SET t.project = $pid RETURN count(t)",
            pid=project_id,
        )
        return count or 0

    async def _get_stats(self, project_id: str) -> dict:
        rows = await self.graph.run(
            """
            MATCH (t:Java:Type {project: $p})
            WITH count(t) AS types
            OPTIONAL MATCH (m:Java:Method)<-[:DECLARES]-(t2:Java:Type {project: $p})
            RETURN types, count(m) AS methods
            """,
            p=project_id,
        )
        if rows:
            return {"types": rows[0].get("types", 0), "methods": rows[0].get("methods", 0)}
        return {}
