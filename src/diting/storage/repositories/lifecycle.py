"""代码生死簿 Repository"""
from typing import Optional

from sqlalchemy import select

from diting.storage.models import CodeLifecycle, Project
from diting.storage.repositories.base import BaseRepository


class LifecycleRepository(BaseRepository):

    async def upsert(
        self,
        project_name: str,
        method_id: str,
        static_status: str = "",
        dynamic_status: str = "",
        verdict: str = "",
        traffic_count: int = 0,
        notes: str = "",
    ):
        existing = await self.session.execute(
            select(CodeLifecycle)
            .join(Project)
            .where(Project.project_name == project_name)
            .where(CodeLifecycle.method_id == method_id)
        )
        record = existing.scalar_one_or_none()

        if record:
            record.static_status = static_status
            record.dynamic_status = dynamic_status
            record.verdict = verdict
            record.traffic_count = traffic_count
            record.notes = notes
        else:
            project = await self.session.execute(
                select(Project.id).where(Project.project_name == project_name)
            )
            pid = project.scalar_one()
            self.session.add(CodeLifecycle(
                project_id=pid,
                method_id=method_id,
                static_status=static_status,
                dynamic_status=dynamic_status,
                verdict=verdict,
                traffic_count=traffic_count,
                notes=notes,
            ))
        await self.session.flush()

    async def get_dead_code(self, project_name: str) -> list[CodeLifecycle]:
        result = await self.session.execute(
            select(CodeLifecycle)
            .join(Project)
            .where(Project.project_name == project_name)
            .where(CodeLifecycle.verdict.in_(["dead", "suspect"]))
            .order_by(CodeLifecycle.verdict, CodeLifecycle.method_id)
        )
        return list(result.scalars().all())

    async def list_by_project(self, project_name: str, limit: int = 100) -> list[CodeLifecycle]:
        result = await self.session.execute(
            select(CodeLifecycle)
            .join(Project)
            .where(Project.project_name == project_name)
            .order_by(CodeLifecycle.method_id)
            .limit(limit)
        )
        return list(result.scalars().all())
