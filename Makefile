.PHONY: install dev sync lint fmt test serve mcp scan enhance schema help

# ── 环境 ──────────────────────────────────────────────────────────────────────
install:        ## 安装依赖（生产）
	uv sync --no-dev

dev:            ## 安装依赖（含开发工具）
	uv sync

sync:           ## 同步 lockfile
	uv lock --upgrade

# ── 质量 ──────────────────────────────────────────────────────────────────────
lint:           ## 检查代码风格
	uv run ruff check src/ tests/
	uv run mypy src/

fmt:            ## 自动格式化
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

test:           ## 运行测试
	uv run pytest -v

test-cov:       ## 运行测试 + 覆盖率
	uv run pytest --cov=src/diting --cov-report=term-missing

# ── 服务 ──────────────────────────────────────────────────────────────────────
serve:          ## 启动 FastAPI（开发模式，热重载）
	uv run uvicorn diting.api.app:app --reload --port 8000

serve-prod:     ## 启动 FastAPI（生产模式）
	uv run uvicorn diting.api.app:app --host 0.0.0.0 --port 8000 --workers 4

mcp:            ## 启动 MCP Server（stdio）
	uv run diting mcp

# ── 项目管理 ──────────────────────────────────────────────────────────────────
project-list:   ## 列出所有项目
	uv run diting project list

# ── 帮助 ──────────────────────────────────────────────────────────────────────
help:           ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
