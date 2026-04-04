"""SQLAlchemy ORM 模型 — 5 张表"""
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    # 分类
    project_type: Mapped[str | None] = mapped_column(String(50))
    languages: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)

    # 仓库
    repo_url: Mapped[str | None] = mapped_column(String(500))
    branch: Mapped[str] = mapped_column(String(100), default="main")

    # 扫描配置
    scanner: Mapped[str] = mapped_column(String(50), default="jqassistant")
    source_path: Mapped[str | None] = mapped_column(String(500))

    # 状态
    scan_status: Mapped[str] = mapped_column(String(20), default="pending")
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime)
    enhanced_at: Mapped[datetime | None] = mapped_column(DateTime)
    schema_version: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联
    summaries: Mapped[list["CodeSummaryCache"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    lifecycles: Mapped[list["CodeLifecycle"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    branches: Mapped[list["BranchMatrix"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    runs: Mapped[list["AnalysisRun"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project {self.project_name}>"


class CodeSummaryCache(Base):
    """LLM 摘要缓存 — 按 method_id + code_fingerprint 去重"""
    __tablename__ = "code_summary_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    method_id: Mapped[str] = mapped_column(String(500), nullable=False)
    code_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(String(50))
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    commit_hash: Mapped[str | None] = mapped_column(String(40))

    project: Mapped["Project"] = relationship(back_populates="summaries")

    __table_args__ = (
        Index("uq_summary_project_method", "project_id", "method_id", unique=True),
        Index("idx_summary_fingerprint", "code_fingerprint"),
        Index("idx_summary_commit", "commit_hash"),
    )


class CodeLifecycle(Base):
    """代码生死簿 — 死代码检测"""
    __tablename__ = "code_lifecycle"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    method_id: Mapped[str] = mapped_column(String(500), nullable=False)
    static_status: Mapped[str | None] = mapped_column(String(20))
    dynamic_status: Mapped[str | None] = mapped_column(String(20))
    verdict: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    traffic_count: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="lifecycles")

    __table_args__ = (
        Index("uq_lifecycle_project_method", "project_id", "method_id", unique=True),
        Index("idx_lifecycle_verdict", "verdict"),
    )


class BranchMatrix(Base):
    """分流逻辑矩阵 — 条件分支/特性开关分析"""
    __tablename__ = "branch_matrix"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500))
    line_number: Mapped[int | None] = mapped_column(Integer)
    condition_expr: Mapped[str | None] = mapped_column(Text)
    branch_type: Mapped[str | None] = mapped_column(String(50))
    old_path: Mapped[str | None] = mapped_column(Text)
    new_path: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="branches")

    __table_args__ = (
        Index("idx_branch_active", "is_active"),
    )


class AnalysisRun(Base):
    """分析运行日志"""
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_type: Mapped[str | None] = mapped_column(String(20))
    commit_hash: Mapped[str | None] = mapped_column(String(40))
    files_changed: Mapped[int | None] = mapped_column(Integer)
    summaries_generated: Mapped[int | None] = mapped_column(Integer)
    summaries_skipped: Mapped[int | None] = mapped_column(Integer)
    tokens_used: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="runs")

    __table_args__ = (
        Index("idx_runs_commit", "commit_hash"),
        Index("idx_runs_status", "status"),
    )
