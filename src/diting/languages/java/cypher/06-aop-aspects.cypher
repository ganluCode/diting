// @version: 1
// @depends: 01-inheritance
// @creates: ADVISES
// @description: AOP 切面分析

// ========================================
// Step 6: AOP 切面分析
// 建立 Aspect → 目标方法的 ADVISES 关系
// ========================================

// --- 6a: 标记 @Aspect 类 ---
MATCH (cls:Java:Type)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn = 'org.aspectj.lang.annotation.Aspect'
SET cls:Spring:Aspect
RETURN count(cls) AS aspects_labeled;

// --- 6b: 标记 Advice 方法（@Around/@Before/@After/@AfterReturning/@AfterThrowing）---
MATCH (aspectCls:Spring:Aspect)-[:DECLARES]->(m:Method)-[:ANNOTATED_BY]->(ann)-[:OF_TYPE]->(annType:Type)
WHERE annType.fqn IN [
    'org.aspectj.lang.annotation.Around',
    'org.aspectj.lang.annotation.Before',
    'org.aspectj.lang.annotation.After',
    'org.aspectj.lang.annotation.AfterReturning',
    'org.aspectj.lang.annotation.AfterThrowing'
]
SET m:Spring:Advice
RETURN count(m) AS advice_methods_labeled;

// --- 6c: 基于注解匹配的 AOP 关系 ---
// 很多 AOP 切点使用 @annotation(XxxAnnotation) 模式
// 例如: @Around("@annotation(com.xxx.DbName)")
// 此处通过 Advice 方法名和切面类名推断关联：
// 如果切面类名包含某注解的简名（如 DataSourceAspect → @DbName）
// 或者 Advice 方法调用了被特定注解标注的方法
MATCH (aspectCls:Spring:Aspect)-[:DECLARES]->(advice:Spring:Advice)
MATCH (aspectCls)-[:DECLARES]->(advice)-[:INVOKES]->(targetMethod:Method)<-[:DECLARES]-(targetCls:Java:Type)
WHERE NOT targetCls:Spring:Aspect
MERGE (advice)-[:ADVISES]->(targetMethod)
RETURN count(*) AS aop_direct_advises;
