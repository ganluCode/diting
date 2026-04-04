"""MCP Server — FastAPI 上层的薄包装层

所有工具直接调用 graph client 和语言 queries，
保持和老代码一致的工具接口。
"""
import logging
from typing import Optional

from fastmcp import FastMCP

from diting.config import get_settings
from diting.graph.client import GraphClient
from diting.languages.java.queries import JavaQueries
from diting.languages.registry import ensure_plugins_loaded
from diting.mcp.nl2cypher import NL2Cypher

logger = logging.getLogger(__name__)

cfg = get_settings()
ensure_plugins_loaded()

_graph: Optional[GraphClient] = None
_java_queries: Optional[JavaQueries] = None
_nl2cypher: Optional[NL2Cypher] = None


def _proj(project: Optional[str]) -> Optional[str]:
    return project or cfg.default_project or None


mcp = FastMCP(
    name="diting",
    instructions=(
        "DiTing 代码知识图谱 MCP Server，支持 Java/Python 多项目查询。\n"
        "所有工具支持可选的 project 参数（= scan 时的 project_id），不传则查全部。\n"
        "先调用 list_projects 查看可用项目列表。"
    ),
)


# ── 项目发现 ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_projects() -> dict:
    """列出 Neo4j 图谱中所有已扫描项目"""
    rows = await _graph.run(
        """
        MATCH (t)
        WHERE t.project IS NOT NULL
        WITH t.project AS project,
             CASE WHEN 'Java' IN labels(t) THEN 'java'
                  WHEN 'Python' IN labels(t) THEN 'python'
                  ELSE 'unknown' END AS language
        RETURN project, language, count(t) AS node_count
        ORDER BY project
        """
    )
    result = {"count": len(rows), "projects": rows}
    if cfg.default_project:
        result["default_project"] = cfg.default_project
    return result


# ── 通用搜索 ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_code(
    query: str,
    scope: str = "all",
    limit: int = 20,
    project: Optional[str] = None,
) -> dict:
    """
    搜索代码库中的方法/函数或类，支持按名称、签名、业务摘要搜索。

    Args:
        query: 搜索关键词（如 "createOrder"、"支付"）
        scope: "method" / "class" / "function" / "all"
        limit: 最多返回条数（默认 20，最大 50）
        project: 项目 ID，不传则查全部
    """
    return await _java_queries.search_code(query, scope, min(limit, 50), _proj(project))


# ── Java 特有工具 ─────────────────────────────────────────────────────────────

@mcp.tool()
async def get_class_info(class_fqn: str, project: Optional[str] = None) -> dict:
    """
    获取 Java 类的完整信息：注解、继承关系、所有方法、Spring 注入依赖。

    Args:
        class_fqn: 类全限定名或简单类名（如 "OrderServiceImpl"）
        project: 项目 ID，不传则查全部
    """
    return await _java_queries.get_class_info(class_fqn, _proj(project))


@mcp.tool()
async def get_method_info(method_id: str, project: Optional[str] = None) -> dict:
    """
    获取方法完整信息：签名、注解、调用者、被调用者。

    Args:
        method_id: 格式 "ClassName#methodName" 或 "com.example.ClassName#methodName"
        project: 项目 ID，不传则查全部
    """
    if "#" not in method_id:
        return {"error": "格式错误，应为 ClassName#methodName"}
    class_fqn, method_name = method_id.rsplit("#", 1)
    return await _java_queries.get_method_info(class_fqn, method_name, _proj(project))


@mcp.tool()
async def trace_call_chain(
    method_id: str,
    direction: str = "callees",
    depth: int = 2,
    project: Optional[str] = None,
) -> dict:
    """
    追踪方法调用链（INVOKES + RESOLVED_INVOKES）。

    Args:
        method_id: "ClassName#methodName"
        direction: "callees" 它调用了什么 / "callers" 谁调用了它
        depth: 追踪深度 1-5（默认 2）
        project: 项目 ID
    """
    if "#" not in method_id:
        return {"error": "格式错误，应为 ClassName#methodName"}
    class_fqn, method_name = method_id.rsplit("#", 1)
    return await _java_queries.trace_call_chain(
        class_fqn, method_name, direction, depth, _proj(project)
    )


@mcp.tool()
async def find_implementations(
    interface_fqn: str, project: Optional[str] = None
) -> dict:
    """查找接口或抽象类的所有具体实现类。"""
    return await _java_queries.find_implementations(interface_fqn, _proj(project))


@mcp.tool()
async def find_api_endpoints(
    name_filter: Optional[str] = None,
    limit: int = 20,
    project: Optional[str] = None,
) -> dict:
    """查找 HTTP API 入口（@GetMapping / @PostMapping 等）。"""
    return await _java_queries.find_api_endpoints(name_filter, min(limit, 100), _proj(project))


@mcp.tool()
async def find_spring_beans(
    stereotype: str = "all",
    name_filter: Optional[str] = None,
    limit: int = 20,
    project: Optional[str] = None,
) -> dict:
    """查找 Spring Bean，支持按 stereotype 过滤（Service/Controller/Repository/Component）。"""
    return await _java_queries.find_spring_beans(stereotype, name_filter, min(limit, 100), _proj(project))


# ── NL2Cypher ────────────────────────────────────────────────────────────────

@mcp.tool()
async def ask_graph(question: str, mode: str = "auto") -> dict:
    """
    用自然语言查询代码图谱，或直接执行 Cypher 语句。
    需配置 NL2CYPHER_ENABLED=true 和 LLM_API_KEY。

    Args:
        question: 自然语言问题 或 Cypher 语句
        mode: "auto" 自动判断 / "nl" 强制自然语言 / "cypher" 直接执行
    """
    if _nl2cypher is None:
        return {"error": "NL2Cypher 未启用。请设置 NL2CYPHER_ENABLED=true 和 LLM_API_KEY。"}

    _kw = {"MATCH", "RETURN", "WHERE", "WITH", "MERGE", "CREATE", "CALL"}
    is_cypher = mode == "cypher" or (
        mode == "auto" and any(kw in question.upper().split() for kw in _kw)
    )

    if is_cypher:
        result = await _graph.run_raw(question)
        result["mode"] = "cypher"
        return result

    schema = await _graph.get_schema_summary()
    generated = await _nl2cypher.generate(question, schema)
    if "error" in generated:
        return generated

    result = await _graph.run_raw(generated["cypher"])
    result.update(mode="nl2cypher", generated_cypher=generated["cypher"], question=question)
    return result


# ── 启动入口 ─────────────────────────────────────────────────────────────────

async def _init():
    global _graph, _java_queries, _nl2cypher
    _graph = GraphClient(cfg.neo4j)
    await _graph.connect()
    _java_queries = JavaQueries(_graph)
    if cfg.nl2cypher.nl2cypher_enabled and cfg.nl2cypher.api_key:
        _nl2cypher = NL2Cypher(cfg.nl2cypher)


def main():
    import asyncio
    asyncio.run(_init())
    logger.info(
        "Starting DiTing MCP Server | transport=%s host=%s port=%s",
        cfg.mcp.transport, cfg.mcp.host, cfg.mcp.port,
    )
    if cfg.mcp.transport == "sse":
        mcp.run(transport="sse", host=cfg.mcp.host, port=cfg.mcp.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
