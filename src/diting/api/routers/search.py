"""搜索路由 — 跨语言统一搜索 + 语言特有查询"""
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination import Page, paginate

from diting.api.deps import get_graph_client, get_search_service
from diting.core.services.search import SearchService
from diting.graph.client import GraphClient
from diting.languages.registry import get_plugin

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=Page[dict[str, Any]])
async def search_code(
    q: str = Query(..., description="搜索关键词"),
    scope: str = Query("all", description="all | class | method | function"),
    limit: int = Query(50, ge=1, le=200),
    project: Optional[str] = Query(None, description="项目 ID，不传则查全部"),
    search: Annotated[SearchService, Depends(get_search_service)] = None,
):
    result = await search.search_code(q, scope=scope, limit=limit, project_id=project)
    return paginate(result.get("results", []))


@router.get("/classes/{class_fqn:path}")
async def get_class_info(
    class_fqn: str,
    project: Optional[str] = Query(None),
    language: str = Query("java", description="语言插件"),
    graph: Annotated[GraphClient, Depends(get_graph_client)] = None,
):
    plugin = get_plugin(language, graph)
    queries = plugin.get_queries()
    if "get_class_info" not in queries:
        raise HTTPException(400, f"Language '{language}' does not support get_class_info")
    return await queries["get_class_info"](class_fqn=class_fqn, project=project)


@router.get("/methods/{method_id:path}/call-chain")
async def trace_call_chain(
    method_id: str,
    direction: str = Query("callees", description="callees | callers"),
    depth: int = Query(2, ge=1, le=5),
    project: Optional[str] = Query(None),
    language: str = Query("java"),
    graph: Annotated[GraphClient, Depends(get_graph_client)] = None,
):
    if "#" not in method_id:
        raise HTTPException(400, "method_id must be 'ClassName#methodName'")
    class_fqn, method_name = method_id.rsplit("#", 1)
    plugin = get_plugin(language, graph)
    queries = plugin.get_queries()
    if "trace_call_chain" not in queries:
        raise HTTPException(400, f"Language '{language}' does not support trace_call_chain")
    return await queries["trace_call_chain"](
        class_fqn=class_fqn, method_name=method_name,
        direction=direction, depth=depth, project=project,
    )


@router.get("/methods/{method_id:path}")
async def get_method_info(
    method_id: str,
    project: Optional[str] = Query(None),
    language: str = Query("java"),
    graph: Annotated[GraphClient, Depends(get_graph_client)] = None,
):
    if "#" not in method_id:
        raise HTTPException(400, "method_id must be 'ClassName#methodName'")
    class_fqn, method_name = method_id.rsplit("#", 1)
    plugin = get_plugin(language, graph)
    queries = plugin.get_queries()
    if "get_method_info" not in queries:
        raise HTTPException(400, f"Language '{language}' does not support get_method_info")
    return await queries["get_method_info"](
        class_fqn=class_fqn, method_name=method_name, project=project
    )


# ── Java specific ─────────────────────────────────────────────────────────────

@router.get("/java/spring-beans", response_model=Page[dict[str, Any]])
async def find_spring_beans(
    stereotype: str = Query("all"),
    name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    project: Optional[str] = Query(None),
    graph: Annotated[GraphClient, Depends(get_graph_client)] = None,
):
    from diting.languages.java.queries import JavaQueries
    q = JavaQueries(graph)
    result = await q.find_spring_beans(stereotype=stereotype, name_filter=name,
                                        limit=limit, project=project)
    return paginate(result.get("beans", []))


@router.get("/java/api-endpoints", response_model=Page[dict[str, Any]])
async def find_api_endpoints(
    name: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    project: Optional[str] = Query(None),
    graph: Annotated[GraphClient, Depends(get_graph_client)] = None,
):
    from diting.languages.java.queries import JavaQueries
    q = JavaQueries(graph)
    result = await q.find_api_endpoints(name_filter=name, limit=limit, project=project)
    return paginate(result.get("endpoints", []))


@router.get("/java/implementations/{interface_fqn:path}")
async def find_implementations(
    interface_fqn: str,
    project: Optional[str] = Query(None),
    graph: Annotated[GraphClient, Depends(get_graph_client)] = None,
):
    from diting.languages.java.queries import JavaQueries
    q = JavaQueries(graph)
    return await q.find_implementations(interface_fqn=interface_fqn, project=project)
