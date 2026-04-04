"""跨语言统一搜索 Service"""
import logging
from typing import Optional

from diting.core.services.project import ProjectService
from diting.graph import GraphClient
from diting.languages.registry import get_plugin, list_plugins

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, graph: GraphClient, project_service: ProjectService):
        self.graph = graph
        self.projects = project_service

    async def search_code(
        self,
        query: str,
        scope: str = "all",
        limit: int = 20,
        project_id: Optional[str] = None,
    ) -> dict:
        if project_id:
            project = await self.projects.get(project_id)
            if not project:
                return {"count": 0, "results": [], "error": f"Project '{project_id}' not found"}
            return await self._search_by_language(query, project.language, scope, limit, project_id)

        all_results = []
        for lang in list_plugins():
            try:
                r = await self._search_by_language(query, lang, scope, limit, None)
                all_results.extend(r.get("results", []))
            except Exception as e:
                logger.warning("Search failed for %s: %s", lang, e)

        seen = set()
        deduped = []
        for r in all_results:
            key = r.get("id") or r.get("fqn")
            if key and key not in seen:
                seen.add(key)
                deduped.append(r)

        return {"count": len(deduped), "results": deduped[:limit]}

    async def _search_by_language(self, query, language, scope, limit, project_id):
        plugin = get_plugin(language, self.graph)
        queries = plugin.get_queries()
        if "search_code" in queries:
            return await queries["search_code"](
                query=query, scope=scope, limit=limit, project=project_id
            )
        results = await plugin.search_by_name(query, scope, limit, project_id)
        return {"count": len(results), "results": results}
