"""项目 Repository"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from diting.storage.models import Project
from diting.storage.repositories.base import BaseRepository


class ProjectRepository(BaseRepository):

    async def create(
        self,
        project_name: str,
        display_name: str = "",
        languages: list[str] | None = None,
        source_path: str = "",
        project_type: str = "backend",
        repo_url: str = "",
        branch: str = "main",
        scanner: str = "jqassistant",
        description: str = "",
    ) -> Project:
        project = Project(
            project_name=project_name,
            display_name=display_name or project_name,
            languages=languages or [],
            source_path=source_path,
            project_type=project_type,
            repo_url=repo_url,
            branch=branch,
            scanner=scanner,
            description=description,
        )
        self.session.add(project)
        await self.session.flush()
        return project

    async def get_by_name(self, project_name: str) -> Optional[Project]:
        result = await self.session.execute(
            select(Project).where(Project.project_name == project_name)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, project_id: int) -> Optional[Project]:
        return await self.session.get(Project, project_id)

    async def list_all(self) -> list[Project]:
        result = await self.session.execute(
            select(Project).order_by(Project.project_name)
        )
        return list(result.scalars().all())

    async def update_scan_status(self, project_name: str, status: str):
        await self.session.execute(
            update(Project)
            .where(Project.project_name == project_name)
            .values(
                scan_status=status,
                scanned_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def update_fields(self, project_name: str, **fields) -> Optional[Project]:
        """更新任意字段（只更新传入的非 None 值）"""
        project = await self.get_by_name(project_name)
        if not project:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(project, key):
                setattr(project, key, value)
        project.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return project

    async def update_enhance_status(self, project_name: str, schema_version: int):
        await self.session.execute(
            update(Project)
            .where(Project.project_name == project_name)
            .values(
                scan_status="enhanced",
                enhanced_at=datetime.now(timezone.utc),
                schema_version=schema_version,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def delete_by_name(self, project_name: str) -> bool:
        project = await self.get_by_name(project_name)
        if not project:
            return False
        await self.session.delete(project)
        await self.session.flush()
        return True
