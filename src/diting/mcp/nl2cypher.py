"""NL2Cypher — 自然语言转 Cypher（移植自老代码，适配新 config）"""
import logging
import re

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是 Neo4j Cypher 专家，专门查询代码知识图谱（支持 Java 和 Python）。

## Java 图谱 Schema

### 节点标签（常用）
| 标签 | 说明 | 关键属性 |
|------|------|---------|
| :Java:Type:Class | Java 类 | fqn, name, abstract, project |
| :Java:Type:Interface | Java 接口 | fqn, name, project |
| :Java:Method | 方法 | name, signature, visibility, summary, effectiveLineCount, cyclomaticComplexity |
| :Spring:Injectable | Spring Bean | fqn, name |

### 关系类型（Java）
| 关系 | 说明 |
|------|------|
| (Type)-[:DECLARES]->(Method) | 类声明方法 |
| (Method)-[:INVOKES]->(Method) | 直接调用 |
| (Method)-[:RESOLVED_INVOKES]->(Method) | 接口 → 实现 |
| (Type)-[:IMPLEMENTS]->(Type) | 实现接口 |
| (Type)-[:EXTENDS]->(Type) | 继承 |
| (Type)-[:INJECTS {field}]->(Type) | Spring DI |
| (Method)-[:PUBLISHES_EVENT]->(Type) | 发布事件 |
| (Method)-[:HANDLES_EVENT]->(Type) | 监听事件 |
| (Node)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(Type) | 注解 |

## Python 图谱 Schema

### 节点标签
| 标签 | 说明 |
|------|------|
| :Python:Package | 包 |
| :Python:Module | 模块（.py 文件）|
| :Python:Class | 类 |
| :Python:Function | 函数/方法 |

### 关系类型（Python）
| 关系 | 说明 |
|------|------|
| (Package)-[:CONTAINS]->(Module) | 包含模块 |
| (Class)-[:DECLARES]->(Function) | 类声明方法 |
| (Function)-[:INVOKES]->(Function) | 调用 |
| (Class)-[:EXTENDS]->(Class) | 继承 |
| (Module)-[:IMPORTS]->(Module) | 导入 |

## 输出规则
1. **只输出 Cypher 语句**，不加任何解释、注释或 markdown
2. 始终包含 `LIMIT`（不超过 100）
3. 使用 `DISTINCT` 避免重复
4. 属性可能为 null，用 `IS NOT NULL` 或 `coalesce()` 处理
5. 多项目场景用 `WHERE t.project = 'project-id'` 过滤
"""


class NL2Cypher:
    def __init__(self, settings):
        self._api_type = settings.api_type.lower()
        self._model = settings.model

        if self._api_type == "anthropic":
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(
                api_key=settings.api_key,
                base_url=settings.base_url if settings.base_url else None,
            )
        else:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
            )

    async def generate(self, question: str, schema: dict) -> dict:
        schema_ctx = (
            f"当前图谱标签: {', '.join(schema.get('labels', []))}\n"
            f"当前图谱关系: {', '.join(schema.get('relationship_types', []))}"
        )
        system = _SYSTEM_PROMPT + "\n\n" + schema_ctx
        user_msg = f"生成 Cypher 查询：{question}"

        if self._api_type == "anthropic":
            return await self._call_anthropic(system, user_msg, question)
        return await self._call_openai(system, user_msg, question)

    async def _call_openai(self, system: str, user_msg: str, question: str) -> dict:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user_msg}],
                temperature=0.1, max_tokens=600,
            )
            raw = resp.choices[0].message.content.strip()
            return {"cypher": self._extract(raw), "question": question}
        except Exception as e:
            logger.error("NL2Cypher(openai) failed: %s", e)
            return {"error": f"Cypher 生成失败: {e}"}

    async def _call_anthropic(self, system: str, user_msg: str, question: str) -> dict:
        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=600,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = next(
                block.text for block in resp.content if hasattr(block, "text")
            ).strip()
            return {"cypher": self._extract(raw), "question": question}
        except Exception as e:
            logger.error("NL2Cypher(anthropic) failed: %s", e)
            return {"error": f"Cypher 生成失败: {e}"}

    @staticmethod
    def _extract(text: str) -> str:
        m = re.search(r"```(?:cypher)?\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else text.strip()
