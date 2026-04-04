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

    # Neo4j
    client = GraphClient(cfg.neo4j)
    await client.connect()
    deps.set_graph_client(client)

    # PostgreSQL (optional)
    if cfg.pg.enabled:
        from diting.storage.database import init_db, create_tables, close_db
        await init_db(cfg.pg.async_dsn)
        await create_tables()
        deps.set_pg_enabled(True)
        logger.info("PostgreSQL enabled")

    # Ensure indexes
    from diting.core.services.project import ProjectService
    ps = ProjectService(graph=client)
    await ps.ensure_indexes()

    logger.info("DiTing API started (pg=%s)", "on" if cfg.pg.enabled else "off")
    yield

    # Shutdown
    if cfg.pg.enabled:
        from diting.storage.database import close_db
        await close_db()
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


app = create_app()
