"""Python 特有查询"""
import logging
from typing import Optional

from diting.graph.client import GraphClient

logger = logging.getLogger(__name__)


def _pf(var: str = "n") -> str:
    return f"AND ($project IS NULL OR {var}.project = $project)"


class PythonQueries:
    def __init__(self, graph: GraphClient):
        self.graph = graph

    async def search_code(
        self,
        query: str,
        scope: str = "all",
        limit: int = 20,
        project: Optional[str] = None,
    ) -> dict:
        results = []

        if scope in ("class", "all"):
            rows = await self.graph.run(
                f"""
                MATCH (c:Python:Class)
                WHERE (c.name CONTAINS $q OR c.fqn CONTAINS $q) {_pf("c")}
                RETURN c.fqn AS fqn, c.name AS name, c.module_fqn AS module_fqn,
                       c.docstring AS docstring
                ORDER BY CASE WHEN c.name = $q THEN 0 WHEN c.name STARTS WITH $q THEN 1 ELSE 2 END
                LIMIT $limit
                """,
                q=query, limit=min(limit, 50), project=project,
            )
            for r in rows:
                results.append({
                    "type": "class", "id": r["fqn"], "fqn": r["fqn"],
                    "name": r["name"], "module_fqn": r.get("module_fqn"),
                    "docstring": r.get("docstring"),
                })

        if scope in ("function", "method", "all"):
            rows = await self.graph.run(
                f"""
                MATCH (fn:Python:Function)
                WHERE (fn.name CONTAINS $q OR fn.fqn CONTAINS $q
                       OR (fn.docstring IS NOT NULL AND fn.docstring CONTAINS $q))
                  {_pf("fn")}
                RETURN fn.fqn AS fqn, fn.name AS name, fn.class_fqn AS class_fqn,
                       fn.module_fqn AS module_fqn, fn.is_method AS is_method,
                       fn.docstring AS docstring
                ORDER BY CASE WHEN fn.name = $q THEN 0 WHEN fn.name STARTS WITH $q THEN 1 ELSE 2 END
                LIMIT $limit
                """,
                q=query, limit=min(limit, 50), project=project,
            )
            for r in rows:
                results.append({
                    "type": "method" if r.get("is_method") else "function",
                    "id": r["fqn"], "fqn": r["fqn"], "name": r["name"],
                    "class_fqn": r.get("class_fqn"), "module_fqn": r.get("module_fqn"),
                    "docstring": r.get("docstring"),
                })

        return {"count": len(results), "results": results}

    async def get_class_info(self, class_fqn: str, project: Optional[str] = None) -> dict:
        class_name = class_fqn.split(".")[-1]
        rows = await self.graph.run(
            f"""
            MATCH (c:Python:Class)
            WHERE (c.fqn = $fqn OR c.name = $name) {_pf("c")}
            RETURN c.fqn AS fqn, c.name AS name, c.module_fqn AS module_fqn,
                   c.docstring AS docstring, c.is_dataclass AS is_dataclass,
                   c.external_bases AS external_bases
            ORDER BY CASE WHEN c.fqn = $fqn THEN 0 ELSE 1 END
            LIMIT 3
            """,
            fqn=class_fqn, name=class_name, project=project,
        )
        if not rows:
            return {"error": f"Class not found: {class_fqn}"}

        c = rows[0]
        fqn = c["fqn"]

        bases, methods = await _gather(
            self.graph.run(
                "MATCH (c:Python:Class {fqn:$fqn})-[:EXTENDS]->(parent:Python:Class) "
                "RETURN parent.fqn AS fqn, parent.name AS name LIMIT 10",
                fqn=fqn,
            ),
            self.graph.run(
                "MATCH (c:Python:Class {fqn:$fqn})-[:DECLARES]->(fn:Python:Function) "
                "RETURN fn.fqn AS fqn, fn.name AS name, fn.is_async AS is_async, "
                "fn.is_static AS is_static, fn.docstring AS docstring ORDER BY fn.name",
                fqn=fqn,
            ),
        )

        return {
            "class": {
                "fqn": fqn, "name": c["name"], "module_fqn": c.get("module_fqn"),
                "docstring": c.get("docstring"), "is_dataclass": c.get("is_dataclass"),
            },
            "bases": bases,
            "external_bases": c.get("external_bases") or [],
            "methods": [
                {"fqn": m["fqn"], "name": m["name"], "is_async": m.get("is_async"),
                 "is_static": m.get("is_static"), "docstring": m.get("docstring")}
                for m in methods
            ],
        }

    async def trace_call_chain(
        self,
        class_fqn: str,
        method_name: str,
        direction: str = "callees",
        depth: int = 2,
        project: Optional[str] = None,
    ) -> dict:
        depth = max(1, min(depth, 5))

        if direction == "callees":
            query = f"""
                MATCH (c:Python:Class {{fqn:$cfqn}})-[:DECLARES]->(start:Python:Function {{name:$mname}})
                MATCH (start)-[:INVOKES*1..{depth}]->(callee:Python:Function)
                RETURN DISTINCT callee.fqn AS fqn, callee.name AS name,
                                callee.class_fqn AS class_fqn, callee.docstring AS docstring
                LIMIT 50
            """
        else:
            query = f"""
                MATCH (c:Python:Class {{fqn:$cfqn}})-[:DECLARES]->(target:Python:Function {{name:$mname}})
                MATCH (caller:Python:Function)-[:INVOKES*1..{depth}]->(target)
                RETURN DISTINCT caller.fqn AS fqn, caller.name AS name,
                                caller.class_fqn AS class_fqn, caller.docstring AS docstring
                LIMIT 50
            """

        rows = await self.graph.run(query, cfqn=class_fqn, mname=method_name)
        return {
            "method_id": f"{class_fqn}#{method_name}",
            "direction": direction, "depth": depth,
            "count": len(rows),
            "results": rows,
        }


async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros)
