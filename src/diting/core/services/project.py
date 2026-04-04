"""项目管理 Service — CLI 和 API 统一调用

PG 启用时走 SQLAlchemy Repository，未启用时 fallback 到 Neo4j。
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from diting.core.models import Project as ProjectDTO, ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


class ProjectService:
    """统一项目管理服务"""

    def __init__(self, session=None, graph=None):
        """
        Args:
            session: SQLAlchemy AsyncSession（PG 启用时传入）
            graph: GraphClient（PG 未启用时 fallback）
        """
        self._session = session
        self._graph = graph

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
            if "name" in fields:
                fields["name"] = fields.pop("name")
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
                "CREATE INDEX diting_project_id IF NOT EXISTS FOR (p:DiTing:Project) ON (p.id)"
            ])

    # ── PG (SQLAlchemy) ───────────────────────────────────────────────────────

    async def _pg_create(self, req: ProjectCreate) -> ProjectDTO:
        from diting.storage.repositories.project import ProjectRepository
        repo = ProjectRepository(self._session)

        existing = await repo.get_by_name(req.id)
        if existing:
            raise ValueError(f"Project '{req.id}' already exists")

        project = await repo.create(
            project_name=req.id,
            display_name=req.name or req.id,
            languages=[req.language],
            source_path=req.source_path,
            description=req.description,
        )
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

    @staticmethod
    def _pg_to_dto(p) -> ProjectDTO:
        langs = p.languages or []
        return ProjectDTO(
            id=p.project_name,
            name=p.display_name or p.project_name,
            language=langs[0] if langs else "",
            source_path=p.source_path or "",
            description=p.description or "",
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
                scan_status: 'pending', schema_version: 0, created_at: $now
            })
            """,
            id=req.id, name=req.name or req.id, language=req.language,
            source_path=req.source_path, description=req.description, now=now,
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
        return ProjectDTO(
            id=props["id"], name=props.get("name", props["id"]),
            language=props.get("language", ""),
            source_path=props.get("source_path", ""),
            description=props.get("description", ""),
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
