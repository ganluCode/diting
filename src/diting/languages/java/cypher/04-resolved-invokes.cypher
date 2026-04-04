// @version: 2
// @depends: 02-overrides, 03-spring-injection
// @creates: RESOLVED_INVOKES
// @description: 接口调用 → 具体实现派发（需 INJECTS 先完成）

// ========================================
// Step 4: 接口/抽象调用 → 具体实现解析
// 建立 RESOLVED_INVOKES 关系（最终交付物）
// ========================================

// --- 4a: 接口/抽象方法调用解析 ---
// 当 caller INVOKES 一个接口或抽象方法时，
// 找到所有实现该方法的具体类，创建 RESOLVED_INVOKES
MATCH (caller:Method)-[:INVOKES]->(ifMethod:Method)<-[:DECLARES]-(ifType:Java:Type)
WHERE ifType:Interface OR ifMethod.abstract IS NOT NULL
MATCH (implType:Java:Type)-[:IMPLEMENTS|EXTENDS*]->(ifType),
      (implType)-[:DECLARES]->(implMethod:Method)
WHERE implMethod.signature = ifMethod.signature
  AND implMethod.abstract IS NULL
  AND NOT EXISTS { (implMethod)-[:INHERITED_FROM]->() }
MERGE (caller)-[:RESOLVED_INVOKES {
    via: ifMethod.signature,
    dispatchType: 'interface'
}]->(implMethod)
RETURN count(*) AS interface_dispatch_resolved;

// --- 4b: Spring DI 方法调用解析 ---
// 当一个类持有 @Autowired 接口字段，并调用该接口的方法时，
// 将调用解析到被注入的具体实现类的方法
MATCH (ownerType:Java:Type)-[:DECLARES]->(field:Field:Spring:InjectionPoint),
      (field)-[:OF_TYPE]->(interfaceType:Java:Type),
      (ownerType)-[:DECLARES]->(callerMethod:Method),
      (callerMethod)-[:INVOKES]->(interfaceMethod:Method)<-[:DECLARES]-(interfaceType),
      (concreteType:Spring:Injectable)-[:IMPLEMENTS|EXTENDS*]->(interfaceType),
      (concreteType)-[:DECLARES]->(concreteMethod:Method)
WHERE concreteMethod.signature = interfaceMethod.signature
  AND concreteMethod.abstract IS NULL
  AND NOT EXISTS { (concreteMethod)-[:INHERITED_FROM]->() }
  AND concreteType:Class
MERGE (callerMethod)-[:RESOLVED_INVOKES {
    via: interfaceMethod.signature,
    dispatchType: 'spring_injection',
    field: field.name
}]->(concreteMethod)
RETURN count(*) AS spring_dispatch_resolved;
