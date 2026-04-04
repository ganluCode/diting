"""扫描编排 Service — 路由到语言插件，记录运行日志"""
import logging
import time
from pathlib import Path

from diting.core.services.project import ProjectService
from diting.graph import GraphClient
from diting.languages.base import ScanResult
from diting.languages.registry import get_plugin

logger = logging.getLogger(__name__)


class ScanService:
    def __init__(self, graph: GraphClient, project_service: ProjectService, session=None):
        self.graph = graph
        self.projects = project_service
        self._session = session

    async def scan(
        self,
        project_name: str,
        reset: bool = False,
        skip_enhance: bool = False,
    ) -> ScanResult:
        project = await self.projects.get(project_name)
        if not project:
            raise ValueError(f"Project '{project_name}' not found")

        # 记录运行日志
        run_id = await self._log_run_start(project_name, "scan")
        t0 = time.time()

        # 构建插件
        plugin = self._build_plugin(project.language)

        logger.info("Scanning %s (language=%s, reset=%s)", project_name, project.language, reset)
        await self.projects.update_scan_status(project_name, "pending")

        try:
            result = await plugin.scan(
                project_path=Path(project.source_path),
                project_id=project_name,
                reset=reset,
            )
        except Exception as e:
            logger.error("Scan failed for %s: %s", project_name, e)
            await self.projects.update_scan_status(project_name, "error")
            await self._log_run_finish(run_id, "failed", t0, error_message=str(e))
            raise

        if result.ok:
            await self.projects.update_scan_status(project_name, "scanned")
            await self._log_run_finish(run_id, "success", t0,
                                        files_changed=result.files_scanned)
        else:
            await self.projects.update_scan_status(project_name, "error")
            await self._log_run_finish(run_id, "failed", t0,
                                        error_message="; ".join(result.errors))

        if result.ok and not skip_enhance:
            logger.info("Auto-enhancing %s", project_name)
            await self.enhance(project_name)

        return result

    async def enhance(
        self,
        project_name: str,
        clean: bool = False,
        verify: bool = True,
    ):
        project = await self.projects.get(project_name)
        if not project:
            raise ValueError(f"Project '{project_name}' not found")

        run_id = await self._log_run_start(project_name, "enhance")
        t0 = time.time()

        plugin = self._build_plugin(project.language)
        logger.info("Enhancing %s (language=%s)", project_name, project.language)

        try:
            result = await plugin.enhance(project_name, clean=clean, verify=verify)
            await self.projects.update_enhance_status(project_name, schema_version=1)
            await self._log_run_finish(run_id, "success", t0)
            return result
        except Exception as e:
            await self._log_run_finish(run_id, "failed", t0, error_message=str(e))
            raise

    def _build_plugin(self, language: str):
        plugin = get_plugin(language, self.graph)
        if language == "java":
            from diting.config import get_settings
            from diting.languages.java.plugin import JavaPlugin
            cfg = get_settings()
            plugin = JavaPlugin(
                self.graph,
                neo4j_uri=cfg.neo4j.uri,
                neo4j_user=cfg.neo4j.user,
                neo4j_password=cfg.neo4j.password,
                jqa_version=cfg.jqassistant_version,
            )
        return plugin

    async def _log_run_start(self, project_name: str, run_type: str) -> int | None:
        if not self._session:
            return None
        from diting.storage.repositories.run import RunRepository
        repo = RunRepository(self._session)
        run = await repo.create(project_name, run_type)
        return run.id

    async def _log_run_finish(self, run_id, status, t0, **extra):
        if run_id is None or not self._session:
            return
        from diting.storage.repositories.run import RunRepository
        repo = RunRepository(self._session)
        duration_ms = int((time.time() - t0) * 1000)
        await repo.finish(run_id, status, duration_ms=duration_ms, **extra)
