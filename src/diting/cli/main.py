"""DiTing CLI — typer

所有命令统一走 core/services，和 API 共用同一套 Service 层。
"""
import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="diting", help="DiTing 代码知识图谱系统", no_args_is_help=True)
project_app = typer.Typer(help="项目管理", no_args_is_help=True)
db_app = typer.Typer(help="数据库管理", no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(db_app, name="db")

console = Console()


def _run_async(coro):
    return asyncio.run(coro)


async def _connect():
    """连接 Neo4j + 可选 PG，返回 (graph, session_or_none, cfg)"""
    from diting.config import get_settings
    from diting.graph.client import GraphClient

    cfg = get_settings()
    graph = GraphClient(cfg.neo4j)
    await graph.connect()

    session = None
    if cfg.pg.enabled:
        from diting.storage.database import init_db, get_session
        await init_db(cfg.pg.async_dsn)
        # 手动获取 session
        session_ctx = get_session()
        session = await session_ctx.__aenter__()
        # 把 context manager 存起来以便 cleanup 时关闭
        session._ctx = session_ctx

    return graph, session, cfg


async def _cleanup(graph, session):
    if session:
        await session._ctx.__aexit__(None, None, None)
        from diting.storage.database import close_db
        await close_db()
    await graph.close()


def _make_project_service(graph, session):
    from diting.core.services.project import ProjectService
    return ProjectService(session=session, graph=graph)


def _make_scan_service(graph, session, project_service):
    from diting.core.services.scan import ScanService
    return ScanService(graph, project_service, session=session)


def _make_search_service(graph, project_service):
    from diting.core.services.search import SearchService
    return SearchService(graph, project_service)


# ── db (数据库管理) ───────────────────────────────────────────────────────────

@db_app.command("init")
def db_init():
    """初始化 PostgreSQL 数据库（建表，幂等）"""
    async def _fn():
        from diting.config import get_settings
        cfg = get_settings()
        if not cfg.pg.enabled:
            console.print("[red]PG_ENABLED=false，请在 .env 中启用 PostgreSQL[/red]")
            raise typer.Exit(1)

        from diting.storage.database import init_db, create_tables, close_db
        await init_db(cfg.pg.async_dsn)
        await create_tables()
        await close_db()
        console.print("[green]数据库初始化完成[/green]")

    _run_async(_fn())


@db_app.command("status")
def db_status():
    """检查数据库连接状态"""
    async def _fn():
        from diting.config import get_settings
        cfg = get_settings()

        # Neo4j
        try:
            from diting.graph.client import GraphClient
            g = GraphClient(cfg.neo4j)
            await g.connect()
            summary = await g.get_schema_summary()
            await g.close()
            console.print(f"[green]Neo4j OK[/green] ({cfg.neo4j.uri}) — "
                          f"{len(summary['labels'])} labels, "
                          f"{len(summary['relationship_types'])} rel types")
        except Exception as e:
            console.print(f"[red]Neo4j FAIL[/red] ({cfg.neo4j.uri}): {e}")

        # PG
        if cfg.pg.enabled:
            try:
                from diting.storage.database import init_db, close_db
                from diting.storage.database import get_session
                await init_db(cfg.pg.async_dsn)
                async with get_session() as session:
                    from diting.storage.repositories.project import ProjectRepository
                    repo = ProjectRepository(session)
                    projects = await repo.list_all()
                console.print(f"[green]PostgreSQL OK[/green] ({cfg.pg.host}:{cfg.pg.port}/"
                              f"{cfg.pg.database}) — {len(projects)} projects")
                await close_db()
            except Exception as e:
                console.print(f"[red]PostgreSQL FAIL[/red]: {e}")
        else:
            console.print("[dim]PostgreSQL: disabled (PG_ENABLED=false)[/dim]")

    _run_async(_fn())


# ── project ───────────────────────────────────────────────────────────────────

@project_app.command("list")
def project_list():
    """列出所有项目"""
    async def _fn():
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            projects = await ps.list_all()
            if not projects:
                console.print("[yellow]暂无项目[/yellow]")
                return
            table = Table("Name", "Language", "Status", "Source Path", "Scanned At")
            for p in projects:
                table.add_row(p.id, p.language, p.scan_status, p.source_path,
                              str(p.scanned_at or "—"))
            console.print(table)
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


@project_app.command("add")
def project_add(
    project_name: str = typer.Argument(..., help="项目名称（唯一标识，如 order-service）"),
    language: str = typer.Option(..., "--language", "-l", help="java | python"),
    path: str = typer.Option(..., "--path", "-p", help="源码根目录绝对路径"),
    display_name: str = typer.Option("", "--name", "-n", help="可读展示名"),
    description: str = typer.Option("", "--desc", "-d", help="项目描述"),
):
    """添加项目"""
    from diting.core.models import ProjectCreate

    async def _fn():
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            await ps.ensure_indexes()
            p = await ps.create(ProjectCreate(
                id=project_name, name=display_name or project_name,
                language=language, source_path=path, description=description,
            ))
            console.print(f"[green]项目已创建: {p.id} ({p.language})[/green]")
            console.print(f"  路径: {p.source_path}")
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


@project_app.command("show")
def project_show(project_name: str = typer.Argument(..., help="项目名称")):
    """查看项目详情"""
    async def _fn():
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            p = await ps.get(project_name)
            if not p:
                console.print(f"[red]项目 '{project_name}' 不存在[/red]")
                raise typer.Exit(1)
            console.print(p.model_dump_json(indent=2))
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


@project_app.command("delete")
def project_delete(
    project_name: str = typer.Argument(..., help="项目名称"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
):
    """删除项目元数据"""
    if not force:
        confirm = typer.confirm(f"确认删除项目 '{project_name}'？")
        if not confirm:
            raise typer.Abort()

    async def _fn():
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            p = await ps.get(project_name)
            if not p:
                console.print(f"[red]项目 '{project_name}' 不存在[/red]")
                raise typer.Exit(1)
            await ps.delete(project_name)
            console.print(f"[green]项目已删除: {project_name}[/green]")
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


# ── scan ──────────────────────────────────────────────────────────────────────

@app.command()
def scan(
    project_name: str = typer.Argument(..., help="项目名称"),
    reset: bool = typer.Option(False, "--reset", help="清空 Neo4j 全部数据后重新扫描"),
    skip_enhance: bool = typer.Option(False, "--skip-enhance", help="扫描后不自动执行增强"),
):
    """扫描项目源码/字节码 → Neo4j"""
    from diting.languages.registry import ensure_plugins_loaded

    async def _fn():
        ensure_plugins_loaded()
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            scanner = _make_scan_service(graph, session, ps)
            console.print(f"Scanning [bold]{project_name}[/bold]...")
            result = await scanner.scan(project_name, reset=reset, skip_enhance=skip_enhance)
            if result.ok:
                console.print(f"[green]扫描完成[/green] {result.details}")
            else:
                console.print(f"[red]扫描失败[/red] {result.errors}")
                raise typer.Exit(1)
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


# ── enhance ───────────────────────────────────────────────────────────────────

@app.command()
def enhance(
    project_name: str = typer.Argument(..., help="项目名称"),
    clean: bool = typer.Option(False, "--clean", help="先删除所有增强关系再重建"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="执行后运行验证脚本"),
):
    """执行语言特有的 Cypher 增强（继承、DI、调用链等）"""
    from diting.languages.registry import ensure_plugins_loaded

    async def _fn():
        ensure_plugins_loaded()
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            scanner = _make_scan_service(graph, session, ps)
            console.print(f"Enhancing [bold]{project_name}[/bold]...")
            result = await scanner.enhance(project_name, clean=clean, verify=verify)
            console.print(f"[green]{result.summary()}[/green]")
            if result.verify_warnings:
                for w in result.verify_warnings:
                    console.print(f"  [yellow]WARN:[/yellow] {w}")
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


# ── search ────────────────────────────────────────────────────────────────────

@app.command()
def search(
    keyword: str = typer.Argument(..., help="搜索关键词"),
    project: Optional[str] = typer.Option(None, "--project", "-p"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """搜索代码（类/方法）"""
    from diting.languages.registry import ensure_plugins_loaded

    async def _fn():
        ensure_plugins_loaded()
        graph, session, cfg = await _connect()
        try:
            ps = _make_project_service(graph, session)
            ss = _make_search_service(graph, ps)
            result = await ss.search_code(keyword, limit=limit, project_id=project)
            table = Table("Type", "Name", "FQN")
            for r in result.get("results", []):
                table.add_row(r.get("type", ""), r.get("name", ""),
                              r.get("fqn", r.get("id", "")))
            console.print(table)
        finally:
            await _cleanup(graph, session)

    _run_async(_fn())


# ── schema ────────────────────────────────────────────────────────────────────

@app.command()
def schema(language: str = typer.Argument(..., help="java | python")):
    """查看语言 schema 声明"""
    from diting.languages.registry import ensure_plugins_loaded, get_plugin
    from unittest.mock import MagicMock

    ensure_plugins_loaded()
    plugin = get_plugin(language, MagicMock())
    s = plugin.get_schema()

    console.print(f"\n[bold]{language} Schema[/bold]\n")
    console.print("[bold]Labels:[/bold]")
    for label, props in s.labels.items():
        console.print(f"  {label}: {list(props.keys())}")
    console.print("\n[bold]Relationships:[/bold]")
    for rel, defn in s.relationships.items():
        console.print(f"  {rel}: {defn.source_label} → {defn.target_label}")
    console.print("\n[bold]Enhanced:[/bold]", s.enhanced_relationships)


# ── serve ─────────────────────────────────────────────────────────────────────

@app.command()
def serve(
    port: int = typer.Option(8000, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
    reload: bool = typer.Option(False, "--reload"),
):
    """启动 FastAPI 服务"""
    import uvicorn
    uvicorn.run("diting.api.app:app", host=host, port=port, reload=reload)


@app.command("mcp")
def run_mcp():
    """启动 MCP Server"""
    from diting.mcp.server import main
    main()


if __name__ == "__main__":
    app()
