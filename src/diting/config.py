"""统一配置 — pydantic-settings，支持 .env 文件和环境变量

通过 ENV_FILE 环境变量指定配置文件，默认 .env：
    ENV_FILE=.env.prod diting serve
    ENV_FILE=.env.test diting db status
"""
import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = os.getenv("ENV_FILE", ".env")


class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEO4J_", extra="ignore")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j_password"
    http_port: int = 7474

    @property
    def http_url(self) -> str:
        host = self.uri.replace("bolt://", "").split(":")[0]
        return f"http://{host}:{self.http_port}"


class NL2CypherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    nl2cypher_enabled: bool = Field(False, alias="NL2CYPHER_ENABLED")
    api_type: Literal["openai", "anthropic"] = "openai"
    api_key: str = ""
    model: str = "MiniMax-Text-01"
    base_url: str = "https://api.minimaxi.chat/v1"

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore",
        populate_by_name=True,
    )


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    key: str = ""  # 静态 API Key，留空则不启用认证


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    transport: Literal["sse", "stdio"] = "sse"
    host: str = "0.0.0.0"
    port: int = 8001


class PgSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PG_", extra="ignore")

    enabled: bool = False
    host: str = "localhost"
    port: int = 5432
    user: str = "analyst"
    password: str = ""
    database: str = "code_analysis"
    container: str = "postgres"  # docker 模式

    @property
    def dsn(self) -> str:
        """同步 DSN（Alembic 等场景用）"""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def async_dsn(self) -> str:
        """异步 DSN（SQLAlchemy async engine 用）"""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class Settings(BaseSettings):
    # 默认项目（工具调用时未传 project 参数时的兜底）
    default_project: str = Field("", alias="DEFAULT_PROJECT")

    # jQAssistant 版本
    jqassistant_version: str = Field("2.3.0", alias="JQASSISTANT_VERSION")

    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    pg: PgSettings = Field(default_factory=PgSettings)
    nl2cypher: NL2CypherSettings = Field(default_factory=NL2CypherSettings)
    api: APISettings = Field(default_factory=APISettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    """获取全局配置（单例）。配置文件由 ENV_FILE 环境变量指定，默认 .env"""
    return Settings()
