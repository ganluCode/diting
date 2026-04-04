"""Java 调用图增强器 — 执行 cypher/ 目录下的增强脚本"""
import logging
from pathlib import Path

from diting.graph import CypherExecutor, EnhanceResult, GraphClient
from diting.languages.java.schema import JAVA_SCHEMA

logger = logging.getLogger(__name__)

_CYPHER_DIR = Path(__file__).parent / "cypher"


class JavaEnhancer:
    def __init__(self, graph: GraphClient):
        self.graph = graph
        self.executor = CypherExecutor(graph)

    async def enhance(
        self,
        project_id: str,
        clean: bool = False,
        verify: bool = True,
    ) -> EnhanceResult:
        """
        执行 Java 增强脚本（继承、重写、Spring DI、接口调用解析、AOP 等）

        Args:
            project_id: 项目 ID（目前增强作用于全图，未来可加范围参数）
            clean: 先删除所有增强关系再重建
            verify: 执行完后跑 _verify.cypher 检查断链
        """
        # 1. 确保索引
        await self.graph.create_indexes(JAVA_SCHEMA.index_statements())

        # 2. 可选：清除旧增强关系
        if clean:
            logger.info("Cleaning existing enhanced relationships")
            counts = await self.executor.delete_relationships(
                JAVA_SCHEMA.enhanced_relationships
            )
            for rel, cnt in counts.items():
                logger.info("  Deleted %d %s", cnt, rel)

            # 清除自定义标签
            await self._clean_labels()

        # 3. 执行增强脚本
        logger.info("Running Java enhancement scripts from %s", _CYPHER_DIR)
        result = await self.executor.run_directory(
            _CYPHER_DIR,
            run_verify=verify,
        )

        logger.info("Java enhancement complete: %s", result.summary())
        if result.verify_warnings:
            logger.warning("Verification warnings:")
            for w in result.verify_warnings:
                logger.warning("  %s", w)

        return result

    async def _clean_labels(self):
        """清除增强阶段打的自定义标签"""
        label_cleanups = [
            ("Spring:InjectionPoint", "REMOVE f:Spring:InjectionPoint"),
            ("Spring:EventHandler",   "REMOVE m:Spring:EventHandler"),
            ("Spring:Aspect",         "REMOVE n:Spring:Aspect"),
            ("Spring:Advice",         "REMOVE n:Spring:Advice"),
            ("Spring:FeignClient",    "REMOVE n:Spring:FeignClient"),
            ("EntryPoint",            "REMOVE m:EntryPoint:XxlJob:Scheduled:ApiEndpoint:MQConsumer"),
        ]
        for label, remove_stmt in label_cleanups:
            try:
                await self.graph.run(
                    f"MATCH (n:{label}) {remove_stmt} RETURN count(n)"
                )
            except Exception as e:
                logger.debug("Failed to clean label %s: %s", label, e)
