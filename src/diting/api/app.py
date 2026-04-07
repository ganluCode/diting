"""FastAPI 应用工厂"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from diting.api import deps
from diting.api.routers import analysis, projects, search
from diting.config import get_settings
from diting.graph.client import GraphClient
from diting.languages.registry import ensure_plugins_loaded

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    ensure_plugins_loaded()

    # Neo4j（连接失败时降级运行，图谱相关接口不可用）
    client: GraphClient | None = None
    try:
        _client = GraphClient(cfg.neo4j)
        await _client.connect()
        client = _client
        deps.set_graph_client(client)
    except Exception as e:
        logger.warning("Neo4j unavailable, graph features disabled: %s", e)

    # PostgreSQL (optional)
    if cfg.pg.enabled:
        try:
            from diting.storage.database import init_db, create_tables, close_db
            await init_db(cfg.pg.async_dsn)
            await create_tables()
            deps.set_pg_enabled(True)
            logger.info("PostgreSQL connected: %s:%s", cfg.pg.host, cfg.pg.port)
        except Exception as e:
            logger.warning("PostgreSQL unavailable, PG features disabled: %s", e)

    # Ensure indexes (only if Neo4j available)
    if client:
        from diting.core.services.project import ProjectService
        ps = ProjectService(graph=client)
        await ps.ensure_indexes()

    pg_ok = deps._pg_enabled
    logger.info("DiTing API started (neo4j=%s, pg=%s)",
                "on" if client else "off",
                "on" if pg_ok else "off")
    yield

    # Shutdown
    if pg_ok:
        from diting.storage.database import close_db
        await close_db()
    if client:
        await client.close()
    logger.info("DiTing API stopped")


def create_app() -> FastAPI:
    cfg = get_settings()

    app = FastAPI(
        title="DiTing API",
        description="代码知识图谱分析系统 — 多语言、Neo4j、FastAPI",
        version="0.1.0",
        lifespan=lifespan,
    )

    # API Key 认证（API_KEY 有值时启用）
    if cfg.api.key:
        from diting.api.middleware import ApiKeyMiddleware
        app.add_middleware(ApiKeyMiddleware, api_key=cfg.api.key)
        _enable_api_key_in_openapi(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects.router)
    app.include_router(search.router)
    app.include_router(analysis.router)

    # 分页
    from fastapi_pagination import add_pagination
    add_pagination(app)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def _enable_api_key_in_openapi(app: FastAPI):
    """给 OpenAPI schema 注入 X-API-Key SecurityScheme，让 Swagger UI 显示 Authorize 按钮"""
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {})["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            }
        }
        # 全局应用（除了 /health /docs 等，它们在中间件里排除）
        schema["security"] = [{"ApiKeyAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


app = create_app()
