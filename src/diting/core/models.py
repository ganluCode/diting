"""共享 Pydantic 数据模型 — API 和内部逻辑共用"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    id: str = Field(..., description="项目唯一 ID（如 order-service）")
    name: str = Field("", description="可读名称，默认同 id")
    language: Literal["java", "python"] = Field(..., description="编程语言")
    source_path: str = Field(..., description="源码/字节码根目录绝对路径")
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    source_path: Optional[str] = None
    description: Optional[str] = None
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    project_type: Optional[str] = None


class Project(BaseModel):
    id: str
    name: str
    language: str
    source_path: str
    description: str = ""
    scan_status: Literal["pending", "scanned", "enhanced", "error"] = "pending"
    scanned_at: Optional[datetime] = None
    enhanced_at: Optional[datetime] = None
    schema_version: int = 0
    node_stats: dict[str, int] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ScanRequest(BaseModel):
    reset: bool = False
    skip_enhance: bool = False


class EnhanceRequest(BaseModel):
    clean: bool = False
    verify: bool = True


class SearchResult(BaseModel):
    type: str                   # "class", "method", "function"
    id: str
    name: str
    fqn: Optional[str] = None
    language: str = ""
    summary: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    count: int
    results: list[SearchResult]


class CallChainResponse(BaseModel):
    method_id: str
    direction: str
    depth: int
    count: int
    results: list[dict[str, Any]]


class MethodInfo(BaseModel):
    method_id: str
    class_fqn: str
    class_name: str
    method: dict[str, Any]
    annotations: list[dict] = Field(default_factory=list)
    callees: list[dict] = Field(default_factory=list)
    resolved_callees: list[dict] = Field(default_factory=list)
    callers: list[dict] = Field(default_factory=list)


class ClassInfo(BaseModel):
    class_: dict[str, Any] = Field(alias="class")
    annotations: list[dict] = Field(default_factory=list)
    supertypes: list[dict] = Field(default_factory=list)
    methods: list[dict] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class AskRequest(BaseModel):
    question: str
    mode: Literal["auto", "nl", "cypher"] = "auto"


class AskResponse(BaseModel):
    mode: str
    count: int
    results: list[dict]
    generated_cypher: Optional[str] = None
    question: Optional[str] = None
    error: Optional[str] = None
