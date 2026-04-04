// @version: 1
// @creates: ASSIGNABLE_FROM, INHERITED_FROM
// @description: 继承层次分析 — 可赋值关系传递闭包 + 继承成员标记

// ========================================
// Step 1: 继承层次分析
// 建立 ASSIGNABLE_FROM 和 INHERITED_FROM 关系
// 来源: jQAssistant java:TypeAssignableFrom, java:MemberInheritedFrom
// ========================================

// --- 1a: ASSIGNABLE_FROM ---
// IMPLEMENTS/EXTENDS 的传递闭包，标记所有"可赋值"关系
// 例如: List ASSIGNABLE_FROM ArrayList (因为 ArrayList implements List)
MATCH (type:Java:Type)-[:IMPLEMENTS|EXTENDS*]->(superType:Java:Type)
WHERE type <> superType
MERGE (superType)-[:ASSIGNABLE_FROM]->(type)
RETURN count(*) AS assignable_types;

// --- 1b: INHERITED_FROM ---
// 标记从父类继承的成员（字节码中可能生成空名方法节点指向父类方法）
MATCH (type:Java:Type)-[:DECLARES]->(member:Member),
      (superType:Java:Type)-[:DECLARES]->(superMember:Member),
      path=shortestPath((type)-[:EXTENDS|IMPLEMENTS*]->(superType))
WHERE type <> superType
  AND member.name IS NULL
  AND superMember.name IS NOT NULL
  AND member.signature = superMember.signature
  AND superMember.visibility <> 'private'
WITH type, member, superType, superMember, length(path) AS depth
ORDER BY depth ASC
WITH member, head(collect(superMember)) AS inheritedMember
MERGE (member)-[:INHERITED_FROM]->(inheritedMember)
RETURN count(*) AS inherited_members;
