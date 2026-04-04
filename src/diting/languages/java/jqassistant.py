"""jQAssistant CLI 管理 — 下载、配置生成、subprocess 执行"""
import logging
import os
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

JQASSISTANT_VERSION_DEFAULT = "2.3.0"
DOWNLOAD_URL_TEMPLATE = (
    "https://repo1.maven.org/maven2/com/buschmais/jqassistant/cli/"
    "jqassistant-commandline-neo4jv5/{ver}/"
    "jqassistant-commandline-neo4jv5-{ver}-distribution.zip"
)


class JQAssistant:
    def __init__(
        self,
        tools_dir: Path,
        version: str = JQASSISTANT_VERSION_DEFAULT,
    ):
        self.tools_dir = tools_dir
        self.version = version
        self._dist_dir = tools_dir / f"jqassistant-commandline-neo4jv5-{version}"
        self._bin = self._dist_dir / "bin" / "jqassistant.sh"

    @property
    def bin(self) -> Path:
        return self._bin

    def is_installed(self) -> bool:
        return self._bin.exists()

    async def ensure_installed(self):
        if self.is_installed():
            logger.info("jQAssistant %s already installed", self.version)
            return
        await self._download()

    async def _download(self):
        url = DOWNLOAD_URL_TEMPLATE.format(ver=self.version)
        zip_path = self.tools_dir / f"jqa-{self.version}.zip"
        self.tools_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading jQAssistant %s from %s", self.version, url)
        async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(zip_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        logger.info("Extracting %s", zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(self.tools_dir)
        zip_path.unlink()
        self._bin.chmod(0o755)
        logger.info("jQAssistant installed: %s", self._dist_dir)

    def generate_config(
        self,
        scan_targets: list[Path],
        config_file: Path,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        reset: bool = False,
    ) -> Path:
        """生成 .jqassistant.yml 配置文件"""
        files_yaml = "\n".join(
            f"        - java:classpath::{target}" for target in scan_targets
        )
        reset_yaml = "\n    reset: true" if reset else ""

        config_content = f"""\
jqassistant:
  store:
    uri: "{neo4j_uri}"
    remote:
      username: {neo4j_user}
      password: {neo4j_password}
      encryption: false

  plugins:
    - group-id: org.jqassistant.plugin
      artifact-id: jqassistant-spring-plugin
      version: 2.2.0

  scan:{reset_yaml}
    include:
      files:
{files_yaml}

  analyze:
    groups:
      - spring-boot:Default
    report:
      continueOnFailure: true
"""
        config_file.write_text(config_content)
        logger.info("Generated jQAssistant config: %s", config_file)
        return config_file

    def run_scan(self, cwd: Path) -> subprocess.CompletedProcess:
        """执行 jqassistant scan"""
        env = os.environ.copy()
        env["JQASSISTANT_OPTS"] = (
            "--add-opens java.base/java.lang=ALL-UNNAMED "
            "--add-opens java.base/java.nio=ALL-UNNAMED"
        )
        return subprocess.run(
            [str(self._bin), "scan"],
            cwd=cwd,
            env=env,
            capture_output=False,
            check=True,
        )

    def run_analyze(self, cwd: Path) -> subprocess.CompletedProcess:
        """执行 jqassistant analyze（允许失败，Spring plugin 规则违规不影响数据）"""
        env = os.environ.copy()
        env["JQASSISTANT_OPTS"] = (
            "--add-opens java.base/java.lang=ALL-UNNAMED "
            "--add-opens java.base/java.nio=ALL-UNNAMED"
        )
        return subprocess.run(
            [str(self._bin), "analyze"],
            cwd=cwd,
            env=env,
            capture_output=False,
        )  # no check=True — constraint violations are OK


def find_scan_targets(project_path: Path) -> list[Path]:
    """
    查找 Java 项目编译产物（target/classes、build/classes、*.jar）
    支持 Maven 单模块、多模块和 Gradle 项目。
    """
    targets: list[Path] = []

    # Maven single / multi-module
    for classes_dir in [project_path / "target" / "classes",
                        *project_path.glob("*/target/classes"),
                        *project_path.glob("*/*/target/classes")]:
        if classes_dir.is_dir():
            targets.append(classes_dir)

    # Gradle
    gradle_main = project_path / "build" / "classes" / "java" / "main"
    if gradle_main.is_dir():
        targets.append(gradle_main)
    for gradle_dir in project_path.glob("*/build/classes/java/main"):
        if gradle_dir.is_dir():
            targets.append(gradle_dir)

    # JAR files (fallback)
    if not targets:
        for jar in project_path.glob("target/*.jar"):
            if not any(x in jar.name for x in ("-sources", "-javadoc")):
                targets.append(jar)

    return targets


def count_class_files(path: Path) -> int:
    if path.is_dir():
        return sum(1 for _ in path.rglob("*.class"))
    return 0
