# DiTing 架构设计

## 概述

DiTing（谛听）是一套代码知识图谱系统，将多语言项目源码/字节码逆向工程为 Neo4j 知识图谱，
支持调用链追踪、依赖分析、框架语义识别，并通过 FastAPI / MCP / CLI 三种方式对外提供能力。

## 设计原则

1. **语言作为插件，基础设施共享** — 不同语言差异大，不做一套通吃
2. **Cypher 可独立迭代调试** — 增强脚本是最容易出坑的地方，必须可验证
3. **上层统一** — API/MCP/CLI 不感知底层语言细节
4. **Schema 声明式** — 可比对、可文档化、可验证

## 目录结构

```
diting/
├── pyproject.toml                    # uv 管理，单一入口
├── Makefile                          # 常用命令
├── .env.example                      # 环境变量模板
│
├── src/diting/
│   ├── __init__.py
│   ├── config.py                     # pydantic-settings 统一配置
│   │
│   ├── languages/                    # ★ 语言插件（核心分离点）
│   │   ├── __init__.py
│   │   ├── base.py                   # 抽象基类：LanguagePlugin
│   │   ├── registry.py               # 插件注册表（自动发现）
│   │   │
│   │   ├── java/                     # Java 插件（自包含）
│   │   │   ├── __init__.py           # 注册到 registry
│   │   │   ├── scanner.py            # jQAssistant 字节码扫描
│   │   │   ├── jqassistant.py        # jQA 下载/配置/YAML 生成
│   │   │   ├── enhancer.py           # 加载并执行 cypher/*.cypher
│   │   │   ├── schema.py             # Java 节点标签/关系/索引定义
│   │   │   ├── queries.py            # Java 特有查询（Spring Bean 等）
│   │   │   └── cypher/               # ★ Java 专属 Cypher（可独立调试）
│   │   │       ├── 01-inheritance.cypher
│   │   │       ├── 02-overrides.cypher
│   │   │       ├── 03-spring-injection.cypher
│   │   │       ├── 04-resolved-invokes.cypher
│   │   │       ├── 05-custom-annotations.cypher
│   │   │       └── 06-aop-aspects.cypher
│   │   │
│   │   └── python/                   # Python 插件
│   │       ├── __init__.py
│   │       ├── scanner.py            # AST + Jedi 分析
│   │       ├── enhancer.py           # Python 专属增强
│   │       ├── schema.py
│   │       ├── queries.py
│   │       └── cypher/
│   │           └── 01-overrides.cypher
│   │
│   ├── graph/                        # 共享 Neo4j 基础设施
│   │   ├── __init__.py
│   │   ├── client.py                 # 连接池 + 通用 CRUD
│   │   └── cypher_executor.py        # .cypher 文件加载/拆分/执行
│   │
│   ├── core/                         # 业务编排层
│   │   ├── __init__.py
│   │   ├── models.py                 # Pydantic 共享数据模型
│   │   ├── project.py                # 项目管理（语言感知）
│   │   ├── scanner.py                # 调度到对应语言 scanner
│   │   └── search.py                 # 跨语言统一搜索
│   │
│   ├── api/                          # FastAPI
│   │   ├── __init__.py
│   │   ├── app.py                    # FastAPI 应用工厂
│   │   ├── deps.py                   # 依赖注入
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── projects.py           # /api/projects
│   │       ├── search.py             # /api/search
│   │       ├── analysis.py           # /api/analysis（调用链、实现类等）
│   │       └── scanner.py            # /api/scanner（触发扫描）
│   │
│   ├── mcp/                          # MCP Server（API 之上的薄层）
│   │   ├── __init__.py
│   │   ├── server.py
│   │   └── nl2cypher.py
│   │
│   └── cli/                          # CLI（typer）
│       ├── __init__.py
│       └── main.py
│
└── tests/
    ├── conftest.py
    ├── test_graph/
    ├── test_languages/
    ├── test_core/
    └── test_api/
```

## 核心抽象

### LanguagePlugin（languages/base.py）

```python
class LanguagePlugin(ABC):
    """每种语言实现这个接口"""

    name: str               # "java", "python"
    label_prefix: str       # "Java", "Python"（Neo4j 标签前缀）

    @abstractmethod
    async def scan(self, project_path: Path, project_id: str, **opts) -> ScanResult:
        """扫描源码/字节码 → 写入 Neo4j"""

    @abstractmethod
    async def enhance(self, project_id: str, clean: bool = False) -> EnhanceResult:
        """执行语言特有的 Cypher 增强"""

    @abstractmethod
    def get_schema(self) -> LanguageSchema:
        """声明该语言的节点标签、关系类型、属性"""

    def get_queries(self) -> dict[str, Callable]:
        """语言特有的查询（如 Java 的 find_spring_beans），可选"""
        return {}
```

### LanguageSchema（languages/base.py）

```python
@dataclass
class LanguageSchema:
    """语言图谱 Schema 声明"""
    labels: dict[str, dict[str, type]]           # 节点标签 → 属性定义
    relationships: dict[str, RelationshipDef]     # 关系类型 → 起止标签+属性
    indexes: list[tuple[str, list[str]]]          # 需要的索引
    enhanced_relationships: list[str]             # 增强阶段创建的关系（clean 时删除）
```

用途：
- Schema diff：本地声明 vs Neo4j 实际
- NL2Cypher prompt：自动从 schema 生成 Cypher 参考
- 文档生成：`diting schema show java`

### 插件注册（languages/registry.py）

```python
_registry: dict[str, type[LanguagePlugin]] = {}

def register(name: str):
    """装饰器，注册语言插件"""
    def wrapper(cls):
        _registry[name] = cls
        return cls
    return wrapper

def get_plugin(name: str, graph_client) -> LanguagePlugin:
    return _registry[name](graph_client)

def list_plugins() -> list[str]:
    return list(_registry.keys())
```

每个语言的 `__init__.py` 自动注册：

```python
# languages/java/__init__.py
from diting.languages.registry import register
from .plugin import JavaPlugin

register("java")(JavaPlugin)
```

## Cypher 管理

### 文件格式

每个 `.cypher` 文件头部含元信息注释：

```cypher
// @version: 2
// @depends: 01-inheritance
// @creates: RESOLVED_INVOKES
// @description: 接口调用 → 具体实现派发

MATCH (t:Java:Type)-[:DECLARES]->(m:Method) ...
```

### 执行流程（graph/cypher_executor.py）

1. 扫描 `cypher/` 目录，按编号排序
2. 解析元信息（版本、依赖、描述）
3. 按 `;` 分割为独立语句
4. 逐条执行，记录结果
5. 执行 `_verify.cypher`（如存在），报告断链

### 验证脚本（_verify.cypher）

```cypher
// 验证 RESOLVED_INVOKES 不为空
MATCH ()-[r:RESOLVED_INVOKES]->()
WITH count(r) AS cnt
WHERE cnt = 0
RETURN "WARN: RESOLVED_INVOKES 为空，接口调用链未增强" AS message;

// 验证 INJECTS 覆盖率
MATCH (t:Java:Type:Spring:Injectable)
OPTIONAL MATCH (dep)-[r:INJECTS]->(t)
WITH t, count(r) AS inject_count
WHERE inject_count = 0
RETURN count(t) AS uninjected_beans, "未被注入的 Bean 数量" AS label;
```

## 项目管理

项目元数据存 Neo4j（不引入额外依赖）：

```cypher
(:DiTing:Project {
    id: "order-service",
    name: "Order Service",
    language: "java",
    source_path: "/path/to/project",
    scanned_at: datetime(),
    enhanced_at: datetime(),
    schema_version: 2
})
```

## 数据流

```
                      ┌─────────────────────┐
                      │   CLI / API / MCP   │  ← 统一入口
                      └─────────┬───────────┘
                                │
                      ┌─────────▼───────────┐
                      │     core 编排层      │  ← 项目管理、搜索、调度
                      └─────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
    ┌──────────────┐  ┌──────────────┐   ┌──────────────┐
    │  Java Plugin │  │ Python Plugin│   │  Go Plugin   │  ← 语言插件
    │  scanner     │  │  scanner     │   │  (future)    │
    │  enhancer    │  │  enhancer    │   │              │
    │  queries     │  │  queries     │   │              │
    └──────┬───────┘  └──────┬───────┘   └──────────────┘
           │                 │
           ▼                 ▼
    ┌──────────────────────────────┐
    │    graph/ (Neo4j Client)     │  ← 共享基础设施
    │    cypher_executor           │
    └──────────────┬───────────────┘
                   │
                   ▼
            ┌─────────────┐
            │    Neo4j    │
            └─────────────┘
```

## API 设计（FastAPI）

```
GET  /api/projects                         # 列出项目
POST /api/projects                         # 添加项目
GET  /api/projects/{id}                    # 项目详情
POST /api/projects/{id}/scan               # 触发扫描
POST /api/projects/{id}/enhance            # 触发增强

GET  /api/search?q=xxx&project=xxx         # 跨语言搜索
GET  /api/classes/{fqn}                    # 类详情
GET  /api/methods/{id}                     # 方法详情
GET  /api/methods/{id}/call-chain          # 调用链追踪
GET  /api/classes/{fqn}/implementations    # 接口实现类

# Java 特有
GET  /api/java/spring-beans                # Spring Bean
GET  /api/java/api-endpoints               # REST 端点

GET  /api/schema/{language}                # Schema 定义
POST /api/cypher                           # 原始 Cypher 执行
POST /api/ask                              # NL2Cypher
```

## CLI 命令

```bash
# 项目管理
diting project list
diting project add <id> --language java --path /path/to/project
diting project show <id>

# 扫描
diting scan <project-id> [--reset] [--skip-enhance]
diting enhance <project-id> [--clean] [--verify]

# 查询
diting search <keyword> [--project <id>]
diting schema show <language>
diting schema check <project-id>

# 服务
diting serve [--port 8000]           # FastAPI
diting mcp                           # MCP Server (stdio)
```

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 包管理 | uv | 快、锁文件、workspace 支持 |
| Web 框架 | FastAPI | async、自动文档、Pydantic 集成 |
| 配置 | pydantic-settings | 验证、.env、嵌套、类型安全 |
| CLI | typer | 基于 type hint、自带帮助 |
| Neo4j | neo4j (async) | 官方异步驱动 |
| MCP | fastmcp | 已有基础，薄层复用 |
| NL2Cypher | openai/anthropic | 保留双协议支持 |
| Java 扫描 | jQAssistant | 字节码精度最高，subprocess 调用 |
| Python 扫描 | ast + jedi | 内置 + 跨文件解析 |

## 已知坑与注意事项

1. **jQAssistant 远程模式不幂等** — 每次扫描前必须 clean 该项目旧数据
2. **`Artifact.name` 为 null** — 打项目标签用 `Artifact.fileName` 路径匹配
3. **Neo4j 5.x WHERE 子句限制** — 不能在 WHERE pattern 中引入新变量
4. **callers 查询必须同时走 INVOKES + RESOLVED_INVOKES** — 否则 DI 注入链断裂
5. **Spring stereotype 从注解推导** — 不能只依赖 Neo4j labels
6. **PUBLISHES_EVENT** — 用 `EXISTS { MATCH ... }` 语法替代 WHERE pattern
