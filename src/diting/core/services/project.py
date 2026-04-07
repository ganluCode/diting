"""项目管理 Service — CLI 和 API 统一调用

PG 启用时走 SQLAlchemy Repository，未启用时 fallback 到 Neo4j。
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from diting.core.models import Project as ProjectDTO, ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


# ── 仓库 URL 解析 ─────────────────────────────────────────────────────────────

_GIT_URL_RE = re.compile(
    r"^(?P<scheme>https?://|git@)(?P<host>[^:/]+)[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?/?$"
)


def parse_repo_url(url: str) -> Optional[dict]:
    """解析 github/gitee 仓库 URL，返回 {scheme, host, owner, repo, is_ssh}。

    支持：
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
      https://gitee.com/owner/repo
    """
    if not url:
        return None
    m = _GIT_URL_RE.match(url.strip())
    if not m:
        return None
    scheme = m.group("scheme")
    return {
        "scheme": scheme,
        "host": m.group("host"),
        "owner": m.group("owner"),
        "repo": m.group("repo"),
        "is_ssh": scheme == "git@",
    }


def inject_token(url: str, tokens: dict[str, str]) -> str:
    """将 token 注入 HTTPS 仓库 URL（SSH URL 原样返回）。

    tokens: {host: token} 映射，如 {"github.com": "ghp_xxx", "gitee.com": "xxx"}
    """
    info = parse_repo_url(url)
    if not info or info["is_ssh"]:
        return url
    token = tokens.get(info["host"])
    if not token:
        return url
    # 形如 https://oauth2:<token>@github.com/owner/repo.git
    return f"https://oauth2:{token}@{info['host']}/{info['owner']}/{info['repo']}.git"


class ProjectService:
    """统一项目管理服务"""

    def __init__(
        self,
        session=None,
        graph=None,
        workspace: str = "",
        git_tokens: Optional[dict[str, str]] = None,
    ):
        """
        Args:
            session: SQLAlchemy AsyncSession（PG 启用时传入）
            graph: GraphClient（PG 未启用时 fallback）
            workspace: 代码工作区根目录，用于拼接相对 source_path
            git_tokens: {host: token} 私有仓库认证，如 {"github.com": "ghp_xxx"}
        """
        self._session = session
        self._graph = graph
        self._workspace = workspace
        self._git_tokens = git_tokens or {}

    # ── 路径解析 ─────────────────────────────────────────────────────────────

    def resolve_source_path(self, source_path: str) -> Path:
        """将项目 source_path 解析为绝对路径。

        - 绝对路径：原样返回
        - 相对路径：拼接 workspace 根目录；若 workspace 未配置则抛错
        """
        if not source_path:
            raise ValueError("source_path is empty")
        p = Path(source_path).expanduser()
        if p.is_absolute():
            return p
        if not self._workspace:
            raise ValueError(
                f"source_path '{source_path}' is relative but DITING_WORKSPACE is not set"
            )
        return Path(self._workspace).expanduser() / p

    async def resolve_project_path(self, project_name: str) -> Path:
        """根据项目名查询并解析完整源码路径。"""
        project = await self.get(project_name)
        if not project:
            raise ValueError(f"Project '{project_name}' not found")
        return self.resolve_source_path(project.source_path)

    # ── Git 克隆 ─────────────────────────────────────────────────────────────

    async def clone(self, project_name: str, force: bool = False) -> Path:
        """克隆项目仓库到本地。

        读取项目的 repo_url / branch，克隆到 resolve_source_path() 的位置。
        - force=True 且目标目录已存在 → 先删除后重新克隆
        - 目标目录已存在且非空 → 抛错
        """
        project = await self.get(project_name)
        if not project:
            raise ValueError(f"Project '{project_name}' not found")

        # 从 PG 或 Neo4j 拿 repo_url 和 branch
        repo_url, branch = await self._get_repo_info(project_name)
        if not repo_url:
            raise ValueError(f"Project '{project_name}' has no repo_url")

        target = self.resolve_source_path(project.source_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            if not force:
                if any(target.iterdir()):
                    raise ValueError(
                        f"Target path '{target}' already exists and is not empty; use force=True to overwrite"
                    )
            else:
                import shutil
                shutil.rmtree(target)

        # 注入 token（HTTPS 私有仓库），SSH URL 原样使用
        effective_url = inject_token(repo_url, self._git_tokens)

        cmd = ["git", "clone"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [effective_url, str(target)]

        # 日志脱敏：不打印带 token 的真实 URL
        logger.info("Cloning %s → %s (branch=%s)", repo_url, target, branch or "default")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            # 脱敏错误信息中可能包含的 token
            err_msg = stderr.decode("utf-8", errors="replace")
            for token in self._git_tokens.values():
                if token:
                    err_msg = err_msg.replace(token, "***")
            raise RuntimeError(f"git clone failed (exit {proc.returncode}): {err_msg}")
        logger.info("Cloned to %s", target)
        return target

    async def _get_repo_info(self, project_name: str) -> tuple[Optional[str], Optional[str]]:
        """返回 (repo_url, branch)"""
        if self._use_pg:
            from diting.storage.repositories.project import ProjectRepository
            repo = ProjectRepository(self._session)
            p = await repo.get_by_name(project_name)
            return (p.repo_url, p.branch) if p else (None, None)
        else:
            row = await self._graph.run_one(
                "MATCH (p:DiTing:Project {id: $id}) RETURN p.repo_url AS url, p.branch AS branch",
                id=project_name,
            )
            return (row["url"], row["branch"]) if row else (None, None)

    @property
    def _use_pg(self) -> bool:
        return self._session is not None

    async def create(self, req: ProjectCreate) -> ProjectDTO:
        if self._use_pg:
            return await self._pg_create(req)
        return await self._neo4j_create(req)

    async def get(self, project_name: str) -> Optional[ProjectDTO]:
        if self._use_pg:
            return await self._pg_get(project_name)
        return await self._neo4j_get(project_name)

    async def list_all(self) -> list[ProjectDTO]:
        if self._use_pg:
            return await self._pg_list_all()
        return await self._neo4j_list_all()

    async def update(self, project_name: str, req: ProjectUpdate) -> Optional[ProjectDTO]:
        """更新项目字段（只更新传入的非 None 值）"""
        if self._use_pg:
            from diting.storage.repositories.project import ProjectRepository
            repo = ProjectRepository(self._session)
            fields = req.model_dump(exclude_none=True)
            # name → display_name 映射
            if "name" in fields:
                fields["display_name"] = fields.pop("name")
            project = await repo.update_fields(project_name, **fields)
            return self._pg_to_dto(project) if project else None
        else:
            # Neo4j fallback
            existing = await self._neo4j_get(project_name)
            if not existing:
                return None
            fields = req.model_dump(exclude_none=True)
            if fields:
                set_clause = ", ".join(f"p.{k} = ${k}" for k in fields)
                await self._graph.run(
                    f"MATCH (p:DiTing:Project {{id: $id}}) SET {set_clause}",
                    id=project_name, **fields,
                )
            return await self._neo4j_get(project_name)

    async def update_scan_status(self, project_name: str, status: str):
        if self._use_pg:
            from diting.storage.repositories.project import ProjectRepository
            repo = ProjectRepository(self._session)
            await repo.update_scan_status(project_name, status)
        else:
            now = datetime.now(timezone.utc).isoformat()
            await self._graph.run(
                "MATCH (p:DiTing:Project {id: $id}) SET p.scan_status = $s, p.scanned_at = $now",
                id=project_name, s=status, now=now,
            )

    async def update_enhance_status(self, project_name: str, schema_version: int):
        if self._use_pg:
            from diting.storage.repositories.project import ProjectRepository
            repo = ProjectRepository(self._session)
            await repo.update_enhance_status(project_name, schema_version)
        else:
            now = datetime.now(timezone.utc).isoformat()
            await self._graph.run(
                "MATCH (p:DiTing:Project {id: $id}) "
                "SET p.scan_status = 'enhanced', p.enhanced_at = $now, p.schema_version = $sv",
                id=project_name, now=now, sv=schema_version,
            )

    async def delete(self, project_name: str):
        if self._use_pg:
            from diting.storage.repositories.project import ProjectRepository
            repo = ProjectRepository(self._session)
            await repo.delete_by_name(project_name)
        else:
            await self._graph.run(
                "MATCH (p:DiTing:Project {id: $id}) DETACH DELETE p", id=project_name,
            )
        logger.info("Deleted project: %s", project_name)

    async def ensure_indexes(self):
        """初始化存储（PG 建表 / Neo4j 建索引）"""
        if self._use_pg:
            from diting.storage.database import create_tables
            await create_tables()
        else:
            await self._graph.create_indexes([
                "CREATE INDEX diting_project_id IF NOT EXISTS FOR (p:Project) ON (p.id)"
            ])

    # ── PG (SQLAlchemy) ───────────────────────────────────────────────────────

    async def _pg_create(self, req: ProjectCreate) -> ProjectDTO:
        from diting.storage.repositories.project import ProjectRepository
        repo = ProjectRepository(self._session)

        existing = await repo.get_by_name(req.id)
        if existing:
            raise ValueError(f"Project '{req.id}' already exists")

        # source_path 处理：如果用户没给，但给了 repo_url，默认用项目 id 作为目录名
        source_path = req.source_path or req.id

        create_kwargs = dict(
            project_name=req.id,
            display_name=req.name or req.id,
            languages=[req.language],
            source_path=source_path,
            description=req.description,
        )
        if req.repo_url:
            create_kwargs["repo_url"] = req.repo_url
        if req.branch:
            create_kwargs["branch"] = req.branch

        project = await repo.create(**create_kwargs)
        logger.info("Created project (PG): %s (%s)", req.id, req.language)
        return self._pg_to_dto(project)

    async def _pg_get(self, project_name: str) -> Optional[ProjectDTO]:
        from diting.storage.repositories.project import ProjectRepository
        repo = ProjectRepository(self._session)
        project = await repo.get_by_name(project_name)
        return self._pg_to_dto(project) if project else None

    async def _pg_list_all(self) -> list[ProjectDTO]:
        from diting.storage.repositories.project import ProjectRepository
        repo = ProjectRepository(self._session)
        projects = await repo.list_all()
        return [self._pg_to_dto(p) for p in projects]

    def _pg_to_dto(self, p) -> ProjectDTO:
        langs = p.languages or []
        source_path = p.source_path or ""
        resolved = None
        if source_path:
            try:
                resolved = str(self.resolve_source_path(source_path))
            except ValueError:
                resolved = None
        return ProjectDTO(
            id=p.project_name,
            name=p.display_name or p.project_name,
            language=langs[0] if langs else "",
            source_path=source_path,
            resolved_path=resolved,
            description=p.description or "",
            repo_url=p.repo_url,
            branch=p.branch,
            scan_status=p.scan_status or "pending",
            scanned_at=p.scanned_at,
            enhanced_at=p.enhanced_at,
            schema_version=p.schema_version or 0,
            node_stats={},
        )

    # ── Neo4j (fallback) ─────────────────────────────────────────────────────

    async def _neo4j_create(self, req: ProjectCreate) -> ProjectDTO:
        existing = await self._neo4j_get(req.id)
        if existing:
            raise ValueError(f"Project '{req.id}' already exists")

        now = datetime.now(timezone.utc).isoformat()
        await self._graph.run(
            """
            CREATE (p:DiTing:Project {
                id: $id, name: $name, language: $language,
                source_path: $source_path, description: $description,
                repo_url: $repo_url, branch: $branch,
                scan_status: 'pending', schema_version: 0, created_at: $now
            })
            """,
            id=req.id, name=req.name or req.id, language=req.language,
            source_path=req.source_path or req.id, description=req.description,
            repo_url=req.repo_url or "", branch=req.branch or "",
            now=now,
        )
        logger.info("Created project (Neo4j): %s (%s)", req.id, req.language)
        return await self._neo4j_get(req.id)

    async def _neo4j_get(self, project_name: str) -> Optional[ProjectDTO]:
        row = await self._graph.run_one(
            "MATCH (p:DiTing:Project {id: $id}) RETURN p", id=project_name,
        )
        if not row:
            return None
        props = row["p"]
        source_path = props.get("source_path", "")
        resolved = None
        if source_path:
            try:
                resolved = str(self.resolve_source_path(source_path))
            except ValueError:
                resolved = None
        return ProjectDTO(
            id=props["id"], name=props.get("name", props["id"]),
            language=props.get("language", ""),
            source_path=source_path,
            resolved_path=resolved,
            description=props.get("description", ""),
            repo_url=props.get("repo_url") or None,
            branch=props.get("branch") or None,
            scan_status=props.get("scan_status", "pending"),
            scanned_at=_parse_dt(props.get("scanned_at")),
            enhanced_at=_parse_dt(props.get("enhanced_at")),
            schema_version=props.get("schema_version", 0),
            node_stats={},
        )

    async def _neo4j_list_all(self) -> list[ProjectDTO]:
        rows = await self._graph.run(
            "MATCH (p:DiTing:Project) RETURN p ORDER BY p.id"
        )
        results = []
        for r in rows:
            dto = await self._neo4j_get(r["p"]["id"])
            if dto:
                results.append(dto)
        return results


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None
