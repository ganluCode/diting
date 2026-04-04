"""Python 语言插件主入口"""
from pathlib import Path

from diting.graph import GraphClient
from diting.languages.base import LanguagePlugin, LanguageSchema, ScanResult
from diting.languages.python.enhancer import PythonEnhancer
from diting.languages.python.queries import PythonQueries
from diting.languages.python.scanner import PythonScanner
from diting.languages.python.schema import PYTHON_SCHEMA


class PythonPlugin(LanguagePlugin):
    name = "python"
    label_prefix = "Python"

    def __init__(self, graph: GraphClient, **settings):
        super().__init__(graph)
        self._scanner = PythonScanner(graph)
        self._enhancer = PythonEnhancer(graph)
        self._queries = PythonQueries(graph)

    async def scan(
        self,
        project_path: Path,
        project_id: str,
        reset: bool = False,
        **opts,
    ) -> ScanResult:
        # Python 扫描本身是幂等的（先 clean 再写入），reset 参数暂无额外含义
        return await self._scanner.scan(project_path, project_id)

    async def enhance(
        self,
        project_id: str,
        clean: bool = False,
        verify: bool = True,
    ):
        return await self._enhancer.enhance(project_id, clean=clean, verify=verify)

    def get_schema(self) -> LanguageSchema:
        return PYTHON_SCHEMA

    def get_queries(self) -> dict:
        return {
            "search_code": self._queries.search_code,
            "get_class_info": self._queries.get_class_info,
            "trace_call_chain": self._queries.trace_call_chain,
        }

    @property
    def queries(self) -> PythonQueries:
        return self._queries
