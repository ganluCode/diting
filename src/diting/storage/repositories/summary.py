"""摘要缓存 Repository"""
from typing import Optional

from sqlalchemy import select

from diting.storage.models import CodeSummaryCache, Project
from diting.storage.repositories.base import BaseRepository


class SummaryRepository(BaseRepository):

    async def get(self, project_name: str, method_id: str) -> Optional[CodeSummaryCache]:
        result = await self.session.execute(
            select(CodeSummaryCache)
            .join(Project)
            .where(Project.project_name == project_name)
            .where(CodeSummaryCache.method_id == method_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        project_name: str,
        method_id: str,
        code_fingerprint: str,
        summary: str,
        model_used: str = "",
        commit_hash: str = "",
    ) -> bool:
        """写入或更新摘要。返回 True=已写入，False=fingerprint 未变跳过"""
        existing = await self.get(project_name, method_id)

        if existing:
            if existing.code_fingerprint == code_fingerprint:
                return False  # 代码未变，跳过
            existing.code_fingerprint = code_fingerprint
            existing.summary = summary
            existing.model_used = model_used
            existing.commit_hash = commit_hash
        else:
            # 查 project id
            project = await self.session.execute(
                select(Project.id).where(Project.project_name == project_name)
            )
            pid = project.scalar_one()
            self.session.add(CodeSummaryCache(
                project_id=pid,
                method_id=method_id,
                code_fingerprint=code_fingerprint,
                summary=summary,
                model_used=model_used,
                commit_hash=commit_hash,
            ))

        await self.session.flush()
        return True

    async def list_by_project(self, project_name: str, limit: int = 100) -> list[CodeSummaryCache]:
        result = await self.session.execute(
            select(CodeSummaryCache)
            .join(Project)
            .where(Project.project_name == project_name)
            .order_by(CodeSummaryCache.generated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
