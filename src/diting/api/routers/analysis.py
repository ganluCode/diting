"""分析路由 — Schema 查看、原始 Cypher、NL2Cypher"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from diting.api.deps import get_graph_client
from diting.core.models import AskRequest
from diting.graph.client import GraphClient
from diting.languages.registry import get_plugin, list_plugins

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/schema/{language}")
async def get_schema(language: str):
    """查看语言 schema 声明"""
    try:
        # Use a dummy graph client just to get schema (no queries needed)
        from unittest.mock import MagicMock
        plugin = get_plugin(language, MagicMock())
        schema = plugin.get_schema()
        return {
            "language": language,
            "labels": list(schema.labels.keys()),
            "relationships": list(schema.relationships.keys()),
            "enhanced_relationships": schema.enhanced_relationships,
            "indexes": [{"label": l, "properties": p} for l, p in schema.indexes],
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/languages")
async def list_languages():
    """列出所有已注册的语言插件"""
    return {"languages": list_plugins()}


@router.post("/cypher")
async def run_cypher(
    body: dict,
    graph: Annotated[GraphClient, Depends(get_graph_client)],
):
    """执行原始 Cypher 语句（用于调试）"""
    cypher = body.get("cypher", "")
    if not cypher:
        raise HTTPException(400, "cypher field required")
    params = body.get("params", {})
    return await graph.run_raw(cypher, params)


@router.post("/ask")
async def ask_graph(
    req: AskRequest,
    graph: Annotated[GraphClient, Depends(get_graph_client)],
):
    """NL2Cypher — 自然语言或 Cypher 直接查询"""
    from diting.config import get_settings
    from diting.mcp.nl2cypher import NL2Cypher

    cfg = get_settings()
    if not cfg.nl2cypher.nl2cypher_enabled or not cfg.nl2cypher.api_key:
        raise HTTPException(503, "NL2Cypher not enabled. Set NL2CYPHER_ENABLED=true and LLM_API_KEY.")

    nl2cypher = NL2Cypher(cfg.nl2cypher)

    _cypher_kw = {"MATCH", "RETURN", "WHERE", "WITH", "MERGE", "CREATE", "CALL"}
    is_cypher = req.mode == "cypher" or (
        req.mode == "auto" and any(kw in req.question.upper().split() for kw in _cypher_kw)
    )

    if is_cypher:
        result = await graph.run_raw(req.question)
        result["mode"] = "cypher"
        return result

    schema = await graph.get_schema_summary()
    generated = await nl2cypher.generate(req.question, schema)
    if "error" in generated:
        return {"error": generated["error"], "mode": "nl2cypher"}

    result = await graph.run_raw(generated["cypher"])
    result["mode"] = "nl2cypher"
    result["generated_cypher"] = generated["cypher"]
    result["question"] = req.question
    return result
