"""分析运行日志 Repository"""
from sqlalchemy import select, update

from diting.storage.models import AnalysisRun, Project
from diting.storage.repositories.base import BaseRepository


class RunRepository(BaseRepository):

    async def create(
        self,
        project_name: str,
        run_type: str,
        status: str = "running",
        commit_hash: str = "",
    ) -> AnalysisRun:
        project = await self.session.execute(
            select(Project.id).where(Project.project_name == project_name)
        )
        pid = project.scalar_one()
        run = AnalysisRun(
            project_id=pid,
            run_type=run_type,
            status=status,
            commit_hash=commit_hash,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish(self, run_id: int, status: str = "success", **extra):
        values = {"status": status}
        for key in ("files_changed", "summaries_generated", "summaries_skipped",
                     "tokens_used", "duration_ms", "error_message"):
            if key in extra:
                values[key] = extra[key]
        await self.session.execute(
            update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values)
        )

    async def list_by_project(self, project_name: str, limit: int = 20) -> list[AnalysisRun]:
        result = await self.session.execute(
            select(AnalysisRun)
            .join(Project)
            .where(Project.project_name == project_name)
            .order_by(AnalysisRun.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
