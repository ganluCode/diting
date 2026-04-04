// @version: 1
// @depends: 01-inheritance
// @creates: OVERRIDES, VIRTUAL_INVOKES
// @description: 方法重写与虚拟调用 — CHA 级别调用图增强

// ========================================
// Step 2: 方法重写与虚拟调用
// 建立 OVERRIDES, VIRTUAL_INVOKES, VIRTUAL_DEPENDS_ON 关系
// 来源: jQAssistant java:MethodOverrides, java:VirtualInvokes, java:VirtualDependsOn
// ========================================

// --- 2a: OVERRIDES ---
// 标记子类方法重写了哪个父类/接口方法
// 例如: OrderServiceImpl.createOrder() OVERRIDES OrderService.createOrder()
MATCH (type:Java:Type)-[:DECLARES]->(method:Method),
      (superType:Java:Type)-[:DECLARES]->(superMethod:Method),
      path=(type)-[:EXTENDS|IMPLEMENTS*]->(superType)
WHERE method.signature = superMethod.signature
  AND superMethod.visibility <> 'private'
  AND NOT EXISTS { (method)-[:INHERITED_FROM]->(:Method) }
  AND NOT EXISTS { (superMethod)-[:INHERITED_FROM]->(:Method) }
WITH type, method, superType, superMethod, length(path) AS depth
ORDER BY depth ASC
WITH method, head(collect(superMethod)) AS overriddenMethod
MERGE (method)-[:OVERRIDES]->(overriddenMethod)
RETURN count(*) AS overridden_methods;

// --- 2b: VIRTUAL_INVOKES (CHA 核心) ---
// 将接口/抽象方法的 INVOKES 传播到所有可能的具体实现
// 这是 CHA 分析的核心：解决"调谁的问题"
MATCH (method:Method)-[invokes:INVOKES]->(:Method)-[:INHERITED_FROM*0..1]->(invokedMethod:Method),
      (invokedMethod)<-[:OVERRIDES*0..]-(overridingMethod:Method)
WHERE overridingMethod.abstract IS NULL
  AND NOT EXISTS { (overridingMethod)-[:INHERITED_FROM]->() }
WITH method, overridingMethod, coalesce(invokes.lineNumber, -1) AS lineNumber
MERGE (method)-[:VIRTUAL_INVOKES {lineNumber: lineNumber}]->(overridingMethod)
RETURN count(*) AS virtual_invokes;

// --- 2c: VIRTUAL_DEPENDS_ON ---
// 将类依赖传播到子类型
// 例如: 如果 A DEPENDS_ON List, 则 A VIRTUAL_DEPENDS_ON ArrayList
MATCH (type:Java:Type)-[:EXTENDS|IMPLEMENTS*]->(superType:Java:Type),
      (dependent:Java:Type)-[:DEPENDS_ON]->(superType)
WHERE superType.fqn <> 'java.lang.Object'
  AND NOT EXISTS { (dependent)-[:EXTENDS|IMPLEMENTS*]->(superType) }
WITH dependent, collect(DISTINCT type) AS types
UNWIND types AS type
MERGE (dependent)-[:VIRTUAL_DEPENDS_ON]->(type)
RETURN count(*) AS virtual_depends_on;
