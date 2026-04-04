// @description: Java 增强验证脚本 — 检查常见断链问题

// 验证 RESOLVED_INVOKES 不为空（接口调用链）
MATCH ()-[r:RESOLVED_INVOKES]->()
WITH count(r) AS cnt
WHERE cnt = 0
RETURN "WARN: RESOLVED_INVOKES 为空，接口调用链未增强。检查 04-resolved-invokes.cypher" AS message;

// 验证 INJECTS 存在（Spring DI）
MATCH ()-[r:INJECTS]->()
WITH count(r) AS cnt
WHERE cnt = 0
RETURN "WARN: INJECTS 为空，Spring 注入关系未建立。检查 03-spring-injection.cypher" AS message;

// 检查 OVERRIDES 数量（方法重写）
MATCH ()-[r:OVERRIDES]->()
WITH count(r) AS cnt
WHERE cnt = 0
RETURN "WARN: OVERRIDES 为空，可能继承关系未增强。检查 02-overrides.cypher" AS message;

// 检查 Spring Bean 标注（jQAssistant Spring 插件）
MATCH (t:Java:Type:Spring:Injectable)
WITH count(t) AS cnt
WHERE cnt = 0
RETURN "WARN: 无 Spring:Injectable 节点。Spring 插件可能未生效，检查 jQAssistant 分析规则" AS message;
