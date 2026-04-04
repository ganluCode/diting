# DiTing（谛听）

代码知识图谱分析系统 — 多语言源码/字节码逆向工程为 Neo4j 知识图谱。

## Quick Start

```bash
cp .env.example .env   # 填写 Neo4j / PG 连接信息
make dev               # uv sync 安装依赖
uv run diting --help   # 查看所有命令
```

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。
