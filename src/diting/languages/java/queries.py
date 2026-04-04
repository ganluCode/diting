"""Java 特有查询 — Spring Bean、API Endpoint、调用链等"""
import logging
from typing import Optional

from diting.graph.client import GraphClient

logger = logging.getLogger(__name__)

_SKIP_METHODS = {"<init>", "<clinit>"}

_WEB_ANNOTATIONS = [
    "org.springframework.web.bind.annotation.RequestMapping",
    "org.springframework.web.bind.annotation.GetMapping",
    "org.springframework.web.bind.annotation.PostMapping",
    "org.springframework.web.bind.annotation.PutMapping",
    "org.springframework.web.bind.annotation.DeleteMapping",
    "org.springframework.web.bind.annotation.PatchMapping",
]

_SPRING_STEREOTYPE_MAP = {
    "Service": "Service",
    "Controller": "Controller",
    "RestController": "Controller",
    "Repository": "Repository",
    "Component": "Component",
    "Configuration": "Configuration",
}


def _pf(var: str = "t") -> str:
    return f"AND ($project IS NULL OR {var}.project = $project)"


class JavaQueries:
    def __init__(self, graph: GraphClient):
        self.graph = graph

    # ── search ────────────────────────────────────────────────────────────────

    async def search_code(
        self,
        query: str,
        scope: str = "all",
        limit: int = 20,
        project: Optional[str] = None,
    ) -> dict:
        results: list[dict] = []

        if scope in ("method", "all"):
            rows = await self.graph.run(
                f"""
                MATCH (t:Java:Type)-[:DECLARES]->(m:Method)
                WHERE NOT m.name IN $skip
                  {_pf("t")}
                  AND (
                    m.name CONTAINS $q
                    OR m.signature CONTAINS $q
                    OR (m.summary IS NOT NULL AND m.summary CONTAINS $q)
                  )
                RETURN t.fqn        AS class_fqn,
                       t.name       AS class_name,
                       m.name       AS method_name,
                       m.signature  AS signature,
                       m.summary    AS summary,
                       m.visibility AS visibility
                ORDER BY CASE WHEN m.name = $q THEN 0 WHEN m.name STARTS WITH $q THEN 1 ELSE 2 END
                LIMIT $limit
                """,
                q=query, skip=list(_SKIP_METHODS), limit=min(limit, 50), project=project,
            )
            for r in rows:
                results.append({
                    "type": "method",
                    "id": f"{r['class_fqn']}#{r['method_name']}",
                    "class_fqn": r["class_fqn"],
                    "class_name": r["class_name"],
                    "method_name": r["method_name"],
                    "signature": r["signature"],
                    "summary": r.get("summary"),
                    "visibility": r.get("visibility"),
                })

        if scope in ("class", "all"):
            rows = await self.graph.run(
                f"""
                MATCH (t:Java:Type)
                WHERE (t:Class OR t:Interface)
                  {_pf("t")}
                  AND (t.name CONTAINS $q OR t.fqn CONTAINS $q)
                RETURN t.fqn     AS fqn,
                       t.name    AS name,
                       labels(t) AS labels
                ORDER BY CASE WHEN t.name = $q THEN 0 WHEN t.name STARTS WITH $q THEN 1 ELSE 2 END
                LIMIT $limit
                """,
                q=query, limit=min(limit, 50), project=project,
            )
            for r in rows:
                results.append({
                    "type": "class",
                    "id": r["fqn"],
                    "fqn": r["fqn"],
                    "name": r["name"],
                    "spring": self._spring_labels(r.get("labels", [])),
                })

        return {"count": len(results), "results": results}

    # ── class info ────────────────────────────────────────────────────────────

    async def get_class_info(self, class_fqn: str, project: Optional[str] = None) -> dict:
        class_name = class_fqn.split(".")[-1]

        rows = await self.graph.run(
            f"""
            MATCH (t:Java:Type)
            WHERE (t.fqn = $fqn OR t.name = $cname) {_pf("t")}
            RETURN t.fqn AS fqn, t.name AS name, labels(t) AS labels
            ORDER BY CASE WHEN t.fqn = $fqn THEN 0 ELSE 1 END
            LIMIT 3
            """,
            fqn=class_fqn, cname=class_name, project=project,
        )
        if not rows:
            return {"error": f"类未找到: {class_fqn}"}

        t = rows[0]
        fqn = t["fqn"]
        labels = t.get("labels") or []

        annotations, supertypes, methods, dependencies = await _gather(
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[:ANNOTATED_BY]->()-[:OF_TYPE]->(ann:Type) "
                "RETURN ann.name AS name, ann.fqn AS fqn LIMIT 20",
                fqn=fqn,
            ),
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[r:EXTENDS|IMPLEMENTS]->(sup:Java:Type) "
                "RETURN type(r) AS rel, sup.fqn AS fqn, sup.name AS name, labels(sup) AS labels",
                fqn=fqn,
            ),
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[:DECLARES]->(m:Method) "
                "WHERE NOT m.name IN $skip "
                "RETURN m.name AS name, m.signature AS signature, m.visibility AS visibility, "
                "m.summary AS summary, m.effectiveLineCount AS line_count, "
                "m.cyclomaticComplexity AS complexity ORDER BY m.name",
                fqn=fqn, skip=list(_SKIP_METHODS),
            ),
            self.graph.run(
                "MATCH (dep:Java:Type)-[r:INJECTS]->(t:Java:Type {fqn:$fqn}) "
                "RETURN dep.fqn AS dep_fqn, dep.name AS dep_name, r.field AS field LIMIT 30",
                fqn=fqn,
            ),
        )

        kind = "interface" if "Interface" in labels else "enum" if "Enum" in labels else "class"
        ann_list = [{"name": a["name"], "fqn": a["fqn"]} for a in annotations]

        return {
            "class": {
                "fqn": fqn, "name": t["name"], "kind": kind,
                "spring_stereotype": (
                    self._spring_stereotype_from_annotations(ann_list)
                    or self._spring_labels(labels)
                ),
            },
            "annotations": ann_list,
            "supertypes": [
                {"rel": s["rel"], "fqn": s["fqn"], "name": s["name"],
                 "kind": "interface" if "Interface" in (s.get("labels") or []) else "class"}
                for s in supertypes
            ],
            "methods": [
                {"name": m["name"], "signature": m["signature"], "visibility": m.get("visibility"),
                 "summary": m.get("summary"), "line_count": m.get("line_count"),
                 "complexity": m.get("complexity")}
                for m in methods
            ],
            "dependencies": [
                {"fqn": d["dep_fqn"], "name": d["dep_name"], "field": d.get("field")}
                for d in dependencies
            ],
        }

    # ── method info ───────────────────────────────────────────────────────────

    async def get_method_info(
        self, class_fqn: str, method_name: str, project: Optional[str] = None
    ) -> dict:
        class_name = class_fqn.split(".")[-1]

        rows = await self.graph.run(
            f"""
            MATCH (t:Java:Type)-[:DECLARES]->(m:Method)
            WHERE (t.fqn = $fqn OR t.name = $cname) {_pf("t")}
              AND m.name = $mname AND NOT m.name IN $skip
            RETURN t.fqn AS class_fqn, t.name AS class_name,
                   m.name AS name, m.signature AS signature,
                   m.visibility AS visibility, m.summary AS summary,
                   m.summaryAt AS summary_at,
                   m.effectiveLineCount AS line_count,
                   m.cyclomaticComplexity AS complexity
            LIMIT 3
            """,
            fqn=class_fqn, cname=class_name, mname=method_name,
            skip=list(_SKIP_METHODS), project=project,
        )
        if not rows:
            return {"error": f"方法未找到: {class_fqn}#{method_name}"}

        m = rows[0]
        resolved_fqn = m["class_fqn"]

        annotations, callees, resolved_callees, callers = await _gather(
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[:DECLARES]->(m:Method {name:$mname})"
                "-[:ANNOTATED_BY]->()-[:OF_TYPE]->(ann:Type) "
                "RETURN ann.name AS name, ann.fqn AS fqn LIMIT 20",
                fqn=resolved_fqn, mname=method_name,
            ),
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[:DECLARES]->(m:Method {name:$mname})"
                "-[:INVOKES]->(callee:Method)<-[:DECLARES]-(ct:Java:Type) "
                "WHERE NOT callee.name IN $skip "
                "RETURN DISTINCT ct.fqn AS class_fqn, callee.name AS method_name, "
                "callee.summary AS summary LIMIT 30",
                fqn=resolved_fqn, mname=method_name, skip=list(_SKIP_METHODS),
            ),
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[:DECLARES]->(m:Method {name:$mname})"
                "-[:RESOLVED_INVOKES]->(impl:Method)<-[:DECLARES]-(ct:Java:Type) "
                "RETURN DISTINCT ct.fqn AS class_fqn, impl.name AS method_name, "
                "impl.summary AS summary LIMIT 20",
                fqn=resolved_fqn, mname=method_name,
            ),
            # callers: 必须同时走 INVOKES 和 RESOLVED_INVOKES，否则 DI 注入链断裂
            self.graph.run(
                "MATCH (t:Java:Type {fqn:$fqn})-[:DECLARES]->(m:Method {name:$mname})"
                "<-[:INVOKES|RESOLVED_INVOKES]-(caller:Method)<-[:DECLARES]-(ct:Java:Type) "
                "WHERE NOT caller.name IN $skip "
                "RETURN DISTINCT ct.fqn AS class_fqn, caller.name AS method_name, "
                "caller.summary AS summary LIMIT 30",
                fqn=resolved_fqn, mname=method_name, skip=list(_SKIP_METHODS),
            ),
        )

        def _fmt(rs):
            return [{"class_fqn": r["class_fqn"], "method": r["method_name"],
                     "summary": r.get("summary")} for r in rs]

        return {
            "method_id": f"{resolved_fqn}#{method_name}",
            "class_fqn": resolved_fqn,
            "class_name": m["class_name"],
            "method": {
                "name": m["name"], "signature": m["signature"],
                "visibility": m.get("visibility"), "summary": m.get("summary"),
                "summary_at": m.get("summary_at"), "line_count": m.get("line_count"),
                "complexity": m.get("complexity"),
            },
            "annotations": [{"name": a["name"], "fqn": a["fqn"]} for a in annotations],
            "callees": _fmt(callees),
            "resolved_callees": _fmt(resolved_callees),
            "callers": _fmt(callers),
        }

    # ── call chain ────────────────────────────────────────────────────────────

    async def trace_call_chain(
        self,
        class_fqn: str,
        method_name: str,
        direction: str = "callees",
        depth: int = 2,
        project: Optional[str] = None,
    ) -> dict:
        depth = max(1, min(depth, 5))
        class_name = class_fqn.split(".")[-1]

        if direction == "callees":
            query = f"""
                MATCH (t:Java:Type)-[:DECLARES]->(start:Method)
                WHERE (t.fqn = $fqn OR t.name = $cname) {_pf("t")} AND start.name = $mname
                MATCH (start)-[:INVOKES|RESOLVED_INVOKES*1..{depth}]->(callee:Method)
                      <-[:DECLARES]-(ct:Java:Type)
                WHERE NOT callee.name IN $skip
                RETURN DISTINCT ct.fqn AS class_fqn, ct.name AS class_name,
                                callee.name AS method_name, callee.summary AS summary
                LIMIT 50
            """
        else:
            query = f"""
                MATCH (t:Java:Type)-[:DECLARES]->(target:Method)
                WHERE (t.fqn = $fqn OR t.name = $cname) {_pf("t")} AND target.name = $mname
                MATCH (caller:Method)-[:INVOKES|RESOLVED_INVOKES*1..{depth}]->(target)
                MATCH (ct:Java:Type)-[:DECLARES]->(caller)
                WHERE NOT caller.name IN $skip
                RETURN DISTINCT ct.fqn AS class_fqn, ct.name AS class_name,
                                caller.name AS method_name, caller.summary AS summary
                LIMIT 50
            """

        rows = await self.graph.run(
            query, fqn=class_fqn, cname=class_name, mname=method_name,
            skip=list(_SKIP_METHODS), project=project,
        )
        return {
            "method_id": f"{class_fqn}#{method_name}",
            "direction": direction, "depth": depth,
            "count": len(rows),
            "results": [
                {"class_fqn": r["class_fqn"], "class_name": r["class_name"],
                 "method": r["method_name"], "summary": r.get("summary")}
                for r in rows
            ],
        }

    # ── Spring specific ───────────────────────────────────────────────────────

    async def find_implementations(
        self, interface_fqn: str, project: Optional[str] = None
    ) -> dict:
        interface_name = interface_fqn.split(".")[-1]
        rows = await self.graph.run(
            f"""
            MATCH (impl:Java:Type)-[:IMPLEMENTS|EXTENDS*1..]->(iface:Java:Type)
            WHERE (iface.fqn = $fqn OR iface.name = $iname)
              AND impl:Class AND impl.abstract IS NULL {_pf("impl")}
            RETURN DISTINCT impl.fqn AS fqn, impl.name AS name, labels(impl) AS labels
            ORDER BY impl.fqn LIMIT 50
            """,
            fqn=interface_fqn, iname=interface_name, project=project,
        )
        return {
            "interface": interface_fqn, "count": len(rows),
            "implementations": [
                {"fqn": r["fqn"], "name": r["name"],
                 "spring": self._spring_labels(r.get("labels", []))}
                for r in rows
            ],
        }

    async def find_api_endpoints(
        self,
        name_filter: Optional[str] = None,
        limit: int = 20,
        project: Optional[str] = None,
    ) -> dict:
        name_cond = "AND (m.name CONTAINS $nf OR t.name CONTAINS $nf)" if name_filter else ""
        rows = await self.graph.run(
            f"""
            MATCH (t:Java:Type)-[:DECLARES]->(m:Method)-[:ANNOTATED_BY]->()-[:OF_TYPE]->(ann:Type)
            WHERE ann.fqn IN $web_anns {_pf("t")} {name_cond}
            RETURN DISTINCT t.fqn AS class_fqn, t.name AS class_name,
                            m.name AS method_name, m.signature AS signature,
                            m.summary AS summary, ann.name AS http_annotation
            ORDER BY t.fqn, m.name LIMIT $limit
            """,
            web_anns=_WEB_ANNOTATIONS, nf=name_filter or "",
            limit=min(limit, 100), project=project,
        )
        return {
            "count": len(rows),
            "endpoints": [
                {
                    "id": f"{r['class_fqn']}#{r['method_name']}",
                    "class_fqn": r["class_fqn"], "class_name": r["class_name"],
                    "method": r["method_name"], "signature": r["signature"],
                    "summary": r.get("summary"),
                    "http_method": (r.get("http_annotation") or "")
                        .replace("Mapping", "").upper() or "REQUEST",
                }
                for r in rows
            ],
        }

    async def find_spring_beans(
        self,
        stereotype: str = "all",
        name_filter: Optional[str] = None,
        limit: int = 20,
        project: Optional[str] = None,
    ) -> dict:
        stereo_cond = f"AND t:{stereotype}" if stereotype != "all" else ""
        name_cond = "AND (t.name CONTAINS $nf OR t.fqn CONTAINS $nf)" if name_filter else ""
        rows = await self.graph.run(
            f"""
            MATCH (t:Java:Type:Spring:Injectable)
            WHERE 1=1 {_pf("t")} {stereo_cond} {name_cond}
            RETURN t.fqn AS fqn, t.name AS name, labels(t) AS labels
            ORDER BY t.fqn LIMIT $limit
            """,
            nf=name_filter or "", limit=min(limit, 100), project=project,
        )
        return {
            "count": len(rows),
            "beans": [
                {"fqn": r["fqn"], "name": r["name"],
                 "stereotypes": self._spring_labels(r.get("labels", []))}
                for r in rows
            ],
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _spring_labels(labels: list[str]) -> list[str]:
        keep = {"Service", "Controller", "Repository", "Component", "Injectable"}
        return [l for l in (labels or []) if l in keep]

    @staticmethod
    def _spring_stereotype_from_annotations(annotations: list[dict]) -> list[str]:
        result = []
        for a in annotations:
            name = a.get("name", "")
            mapped = _SPRING_STEREOTYPE_MAP.get(name)
            if mapped and mapped not in result:
                result.append(mapped)
        return result


async def _gather(*coros):
    """并发执行多个 coroutine"""
    import asyncio
    return await asyncio.gather(*coros)
