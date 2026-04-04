"""Python 调用图增强器"""
import logging
from pathlib import Path

from diting.graph import CypherExecutor, EnhanceResult, GraphClient
from diting.languages.python.schema import PYTHON_SCHEMA

logger = logging.getLogger(__name__)

_CYPHER_DIR = Path(__file__).parent / "cypher"


class PythonEnhancer:
    def __init__(self, graph: GraphClient):
        self.graph = graph
        self.executor = CypherExecutor(graph)

    async def enhance(
        self,
        project_id: str,
        clean: bool = False,
        verify: bool = True,
    ) -> EnhanceResult:
        await self.graph.create_indexes(PYTHON_SCHEMA.index_statements())

        if clean:
            await self.executor.delete_relationships(PYTHON_SCHEMA.enhanced_relationships)

        if not _CYPHER_DIR.exists() or not any(_CYPHER_DIR.glob("[0-9]*.cypher")):
            logger.info("No Python enhancement scripts found, skipping")
            return EnhanceResult()

        return await self.executor.run_directory(_CYPHER_DIR, run_verify=verify)
