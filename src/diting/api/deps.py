"""FastAPI 依赖注入"""
from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from diting.core.services.project import ProjectService
from diting.core.services.scan import ScanService
from diting.core.services.search import SearchService
from diting.graph.client import GraphClient

# ── 全局实例（startup 时初始化）──────────────────────────────────────────────
_graph_client: GraphClient | None = None
_pg_enabled: bool = False


def set_graph_client(client: GraphClient):
    global _graph_client
    _graph_client = client


def set_pg_enabled(enabled: bool):
    global _pg_enabled
    _pg_enabled = enabled


def get_graph_client() -> GraphClient:
    if _graph_client is None:
        raise RuntimeError("GraphClient not initialized")
    return _graph_client


# ── Session 依赖 ─────────────────────────────────────────────────────────────

async def get_db_session() -> AsyncGenerator[AsyncSession | None, None]:
    """PG 启用时返回 session，未启用返回 None"""
    if not _pg_enabled:
        yield None
        return
    from diting.storage.database import get_session_dep
    async for session in get_session_dep():
        yield session


# ── Service 依赖 ─────────────────────────────────────────────────────────────

def get_project_service(
    graph: Annotated[GraphClient, Depends(get_graph_client)],
    session: Annotated[AsyncSession | None, Depends(get_db_session)],
) -> ProjectService:
    return ProjectService(session=session, graph=graph)


def get_scan_service(
    graph: Annotated[GraphClient, Depends(get_graph_client)],
    session: Annotated[AsyncSession | None, Depends(get_db_session)],
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> ScanService:
    return ScanService(graph, projects, session=session)


def get_search_service(
    graph: Annotated[GraphClient, Depends(get_graph_client)],
    projects: Annotated[ProjectService, Depends(get_project_service)],
) -> SearchService:
    return SearchService(graph, projects)
