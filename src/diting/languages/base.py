"""语言插件抽象基类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class RelationshipDef:
    source_label: str
    target_label: str
    properties: dict[str, type] = field(default_factory=dict)


@dataclass
class LanguageSchema:
    """语言图谱 Schema 声明（可比对、可文档化、可验证）"""
    labels: dict[str, dict[str, type]]              # 节点标签 → 属性定义
    relationships: dict[str, RelationshipDef]        # 关系类型 → 定义
    indexes: list[tuple[str, list[str]]]             # (标签, 属性列表)
    enhanced_relationships: list[str] = field(default_factory=list)  # clean 时删除

    def index_statements(self) -> list[str]:
        """生成 CREATE INDEX IF NOT EXISTS 语句"""
        stmts = []
        for label, props in self.indexes:
            safe_name = f"idx_{label.replace(':', '_').lower()}_{props[0]}"
            prop_str = ", ".join(f"n.{p}" for p in props)
            stmts.append(
                f"CREATE INDEX {safe_name} IF NOT EXISTS FOR (n:{label}) ON ({prop_str})"
            )
        return stmts


@dataclass
class ScanResult:
    project_id: str
    language: str
    nodes_written: int = 0
    relationships_written: int = 0
    files_scanned: int = 0
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class LanguagePlugin(ABC):
    """
    每种语言实现这个接口。
    每个插件自包含：scanner + enhancer + schema + queries。
    """

    name: str          # "java", "python"
    label_prefix: str  # "Java", "Python"（Neo4j 标签前缀）

    def __init__(self, graph_client):
        self.graph = graph_client

    @abstractmethod
    async def scan(
        self,
        project_path: Path,
        project_id: str,
        reset: bool = False,
        **opts,
    ) -> ScanResult:
        """扫描源码/字节码 → 写入 Neo4j"""

    @abstractmethod
    async def enhance(
        self,
        project_id: str,
        clean: bool = False,
        verify: bool = True,
    ):
        """执行语言特有的 Cypher 增强，返回 EnhanceResult"""

    @abstractmethod
    def get_schema(self) -> LanguageSchema:
        """声明该语言的节点标签、关系类型、属性"""

    def get_queries(self) -> dict[str, Callable]:
        """语言特有的查询（如 Java 的 find_spring_beans），可选覆盖"""
        return {}

    async def ensure_indexes(self):
        """创建 schema 声明的索引"""
        stmts = self.get_schema().index_statements()
        await self.graph.create_indexes(stmts)

    async def search_by_name(
        self,
        query: str,
        scope: str = "all",
        limit: int = 20,
        project_id: Optional[str] = None,
    ) -> list[dict]:
        """
        通用名称搜索（所有语言都有 fqn/name 属性）。
        子类可以覆盖以增加语言特有的搜索逻辑（如 Java 搜索 summary）。
        """
        pf = self.graph.project_filter("n")
        prefix = self.label_prefix
        results = []

        if scope in ("class", "type", "all"):
            rows = await self.graph.run(
                f"""
                MATCH (n:{prefix}:Type)
                WHERE (n.name CONTAINS $q OR n.fqn CONTAINS $q)
                  {pf}
                RETURN n.fqn AS fqn, n.name AS name, labels(n) AS labels
                ORDER BY CASE WHEN n.name = $q THEN 0 WHEN n.name STARTS WITH $q THEN 1 ELSE 2 END
                LIMIT $limit
                """,
                q=query, limit=limit, project=project_id,
            )
            for r in rows:
                results.append({
                    "type": "type",
                    "id": r["fqn"],
                    "fqn": r["fqn"],
                    "name": r["name"],
                    "language": self.name,
                    "labels": r.get("labels", []),
                })

        if scope in ("function", "method", "all"):
            rows = await self.graph.run(
                f"""
                MATCH (t:{prefix}:Type)-[:DECLARES]->(m:{prefix}:Function)
                WHERE m.name CONTAINS $q {pf.replace('n.', 't.')}
                RETURN t.fqn AS type_fqn, t.name AS type_name,
                       m.name AS name, m.fqn AS fqn
                ORDER BY CASE WHEN m.name = $q THEN 0 WHEN m.name STARTS WITH $q THEN 1 ELSE 2 END
                LIMIT $limit
                """,
                q=query, limit=limit, project=project_id,
            )
            for r in rows:
                results.append({
                    "type": "function",
                    "id": r["fqn"],
                    "fqn": r["fqn"],
                    "name": r["name"],
                    "type_fqn": r["type_fqn"],
                    "language": self.name,
                })

        return results
