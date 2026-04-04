// @version: 1
// @depends: (none)
// @creates: OVERRIDES
// @description: Python 方法重写检测（通过 EXTENDS 关系派生）

// 检测方法重写关系
MATCH (child:Python:Class)-[:EXTENDS]->(parent:Python:Class)
MATCH (child)-[:DECLARES]->(cm:Python:Function)
MATCH (parent)-[:DECLARES]->(pm:Python:Function)
WHERE cm.name = pm.name AND cm.name <> '__init__'
MERGE (cm)-[:OVERRIDES]->(pm)
RETURN count(*) AS overrides;
