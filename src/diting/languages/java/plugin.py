"""Java 语言插件主入口"""
from pathlib import Path
from typing import Optional

from diting.graph import GraphClient
from diting.languages.base import LanguagePlugin, LanguageSchema, ScanResult
from diting.languages.java.enhancer import JavaEnhancer
from diting.languages.java.queries import JavaQueries
from diting.languages.java.schema import JAVA_SCHEMA
from diting.languages.java.scanner import JavaScanner


class JavaPlugin(LanguagePlugin):
    name = "java"
    label_prefix = "Java"

    def __init__(self, graph: GraphClient, **settings):
        super().__init__(graph)
        neo4j_uri = settings.get("neo4j_uri", "bolt://localhost:7687")
        neo4j_user = settings.get("neo4j_user", "neo4j")
        neo4j_password = settings.get("neo4j_password", "neo4j_password")
        jqa_version = settings.get("jqa_version", "2.3.0")

        self._scanner = JavaScanner(graph, neo4j_uri, neo4j_user, neo4j_password, jqa_version)
        self._enhancer = JavaEnhancer(graph)
        self._queries = JavaQueries(graph)

    async def scan(
        self,
        project_path: Path,
        project_id: str,
        reset: bool = False,
        **opts,
    ) -> ScanResult:
        return await self._scanner.scan(project_path, project_id, reset=reset)

    async def enhance(
        self,
        project_id: str,
        clean: bool = False,
        verify: bool = True,
    ):
        return await self._enhancer.enhance(project_id, clean=clean, verify=verify)

    def get_schema(self) -> LanguageSchema:
        return JAVA_SCHEMA

    def get_queries(self) -> dict:
        return {
            "search_code": self._queries.search_code,
            "get_class_info": self._queries.get_class_info,
            "get_method_info": self._queries.get_method_info,
            "trace_call_chain": self._queries.trace_call_chain,
            "find_implementations": self._queries.find_implementations,
            "find_api_endpoints": self._queries.find_api_endpoints,
            "find_spring_beans": self._queries.find_spring_beans,
        }

    # Convenience properties for direct access
    @property
    def queries(self) -> JavaQueries:
        return self._queries
