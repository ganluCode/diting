"""Neo4j 客户端 — 异步驱动，连接池，通用执行"""
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.exceptions import Neo4jError

from diting.config import Neo4jSettings

logger = logging.getLogger(__name__)


class GraphClient:
    """异步 Neo4j 客户端，所有语言插件共享"""

    def __init__(self, settings: Neo4jSettings):
        self._settings = settings
        self._driver: Optional[AsyncDriver] = None

    async def connect(self):
        self._driver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.user, self._settings.password),
        )
        await self._driver.verify_connectivity()
        logger.info("Neo4j connected: %s", self._settings.uri)

    async def close(self):
        if self._driver:
            await self._driver.close()
            self._driver = None

    @asynccontextmanager
    async def session(self):
        if not self._driver:
            raise RuntimeError("GraphClient not connected. Call connect() first.")
        async with self._driver.session() as s:
            yield s

    async def run(self, query: str, **params) -> list[dict]:
        """执行单条 Cypher，返回所有行"""
        async with self.session() as s:
            result = await s.run(query, **params)
            return [record.data() async for record in result]

    async def run_one(self, query: str, **params) -> Optional[dict]:
        """执行单条 Cypher，返回第一行（或 None）"""
        rows = await self.run(query, **params)
        return rows[0] if rows else None

    async def run_scalar(self, query: str, **params) -> Any:
        """执行单条 Cypher，返回第一行第一列"""
        row = await self.run_one(query, **params)
        if row is None:
            return None
        return next(iter(row.values()))

    async def execute_write(self, query: str, **params) -> list[dict]:
        """在写事务中执行"""
        async with self.session() as s:
            result = await s.execute_write(
                lambda tx: tx.run(query, **params)
            )
            return [record.data() for record in result]

    async def run_raw(self, cypher: str, params: Optional[dict] = None) -> dict:
        """执行原始 Cypher，适合 ask_graph 等动态查询"""
        try:
            rows = await self.run(cypher, **(params or {}))
            truncated = len(rows) > 100
            return {"count": len(rows), "truncated": truncated, "results": rows[:100]}
        except Neo4jError as e:
            return {"error": str(e), "cypher": cypher}

    async def get_schema_summary(self) -> dict:
        labels = await self.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
        rel_types = await self.run(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"
        )
        return {
            "labels": [r["label"] for r in labels],
            "relationship_types": [r["relationshipType"] for r in rel_types],
        }

    async def create_indexes(self, index_statements: list[str]):
        """批量创建索引（IF NOT EXISTS，幂等）"""
        async with self.session() as s:
            for stmt in index_statements:
                await s.run(stmt)
        logger.debug("Created %d indexes", len(index_statements))

    # ── project helpers ──────────────────────────────────────────────────────

    @staticmethod
    def project_filter(var: str = "t") -> str:
        """生成项目过滤条件片段（project=null 时不过滤）"""
        return f"AND ($project IS NULL OR {var}.project = $project)"
