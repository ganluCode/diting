"""Python 扫描器 — AST + Jedi 源码分析 → Neo4j

移植自老代码 python_analyzer.py，适配新的插件架构：
- 使用 GraphClient 替代直接驱动调用
- 使用 pydantic dataclass 代替手写 dataclass
- 保留全部 AST + Jedi 分析逻辑
"""
import ast
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from diting.graph.client import GraphClient
from diting.languages.base import ScanResult
from diting.languages.python.schema import PYTHON_SCHEMA

logger = logging.getLogger(__name__)

try:
    import jedi
    HAS_JEDI = True
except ImportError:
    HAS_JEDI = False
    logger.warning("jedi not installed — cross-file call resolution disabled. pip install jedi")

_IGNORE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "node_modules",
    ".eggs", "dist", "build", ".nox",
}


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ModuleInfo:
    fqn: str; name: str; file_path: str; package: str
    line_count: int = 0; docstring: str = ""

@dataclass
class ClassInfo:
    fqn: str; name: str; module_fqn: str
    bases: list = field(default_factory=list)
    decorators: list = field(default_factory=list)
    line_number: int = 0; end_line: int = 0
    docstring: str = ""; is_dataclass: bool = False

@dataclass
class FunctionInfo:
    fqn: str; name: str; module_fqn: str
    class_fqn: str = ""
    parameters: list = field(default_factory=list)
    decorators: list = field(default_factory=list)
    line_number: int = 0; end_line: int = 0; docstring: str = ""
    is_method: bool = False; is_static: bool = False
    is_classmethod: bool = False; is_property: bool = False; is_async: bool = False

@dataclass
class ImportInfo:
    module_fqn: str; target: str; alias: str = ""
    is_from: bool = False; imported_names: list = field(default_factory=list)

@dataclass
class CallInfo:
    caller_fqn: str; callee_name: str
    line_number: int = 0; resolved_fqn: str = ""


# ── AST Analyzer ─────────────────────────────────────────────────────────────

class PythonASTAnalyzer(ast.NodeVisitor):
    def __init__(self, module_fqn: str, source: str, file_path: str):
        self.module_fqn = module_fqn
        self.source = source
        self.file_path = file_path
        self.classes: list[ClassInfo] = []
        self.functions: list[FunctionInfo] = []
        self.imports: list[ImportInfo] = []
        self.calls: list[CallInfo] = []
        self._current_class = ""
        self._current_func = ""

    def analyze(self):
        try:
            tree = ast.parse(self.source, filename=self.file_path)
        except SyntaxError as e:
            logger.warning("Syntax error, skipping %s: %s", self.file_path, e)
            return self
        self.visit(tree)
        return self

    def _dec_name(self, dec) -> str:
        if isinstance(dec, ast.Name): return dec.id
        if isinstance(dec, ast.Attribute):
            parts, node = [], dec
            while isinstance(node, ast.Attribute):
                parts.append(node.attr); node = node.value
            if isinstance(node, ast.Name): parts.append(node.id)
            return ".".join(reversed(parts))
        if isinstance(dec, ast.Call): return self._dec_name(dec.func)
        return ""

    def _base_name(self, base) -> str:
        if isinstance(base, ast.Name): return base.id
        if isinstance(base, ast.Attribute):
            parts, node = [], base
            while isinstance(node, ast.Attribute):
                parts.append(node.attr); node = node.value
            if isinstance(node, ast.Name): parts.append(node.id)
            return ".".join(reversed(parts))
        return ""

    def visit_ClassDef(self, node: ast.ClassDef):
        fqn = (f"{self.module_fqn}.{self._current_class}.{node.name}"
               if self._current_class else f"{self.module_fqn}.{node.name}")
        bases = [b for b in [self._base_name(x) for x in node.bases] if b]
        decs = [d for d in [self._dec_name(x) for x in node.decorator_list] if d]
        self.classes.append(ClassInfo(
            fqn=fqn, name=node.name, module_fqn=self.module_fqn,
            bases=bases, decorators=decs,
            line_number=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node) or "",
            is_dataclass="dataclass" in decs or "dataclasses.dataclass" in decs,
        ))
        prev = self._current_class
        self._current_class = fqn
        self.generic_visit(node)
        self._current_class = prev

    def visit_FunctionDef(self, node): self._visit_func(node, False)
    def visit_AsyncFunctionDef(self, node): self._visit_func(node, True)

    def _visit_func(self, node, is_async: bool):
        if self._current_class:
            fqn = f"{self._current_class}.{node.name}"
            is_method = True
        else:
            fqn = f"{self.module_fqn}.{node.name}"
            is_method = False

        decs = [d for d in [self._dec_name(x) for x in node.decorator_list] if d]
        params = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
        self.functions.append(FunctionInfo(
            fqn=fqn, name=node.name, module_fqn=self.module_fqn,
            class_fqn=self._current_class if is_method else "",
            parameters=params, decorators=decs,
            line_number=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node) or "",
            is_method=is_method, is_static="staticmethod" in decs,
            is_classmethod="classmethod" in decs, is_property="property" in decs,
            is_async=is_async,
        ))
        prev = self._current_func
        self._current_func = fqn
        self.generic_visit(node)
        self._current_func = prev

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(ImportInfo(
                module_fqn=self.module_fqn, target=alias.name,
                alias=alias.asname or "", is_from=False,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        self.imports.append(ImportInfo(
            module_fqn=self.module_fqn, target=node.module or "",
            is_from=True, imported_names=[a.name for a in node.names],
        ))

    def visit_Call(self, node: ast.Call):
        if not self._current_func:
            self.generic_visit(node)
            return
        callee = self._call_name(node.func)
        if callee:
            self.calls.append(CallInfo(
                caller_fqn=self._current_func, callee_name=callee,
                line_number=node.lineno,
            ))
        self.generic_visit(node)

    def _call_name(self, node) -> str:
        if isinstance(node, ast.Name): return node.id
        if isinstance(node, ast.Attribute):
            v = self._call_name(node.value)
            return f"{v}.{node.attr}" if v else node.attr
        return ""


# ── Jedi resolver ─────────────────────────────────────────────────────────────

class JediResolver:
    def __init__(self, project_path: str):
        self.project = jedi.Project(path=project_path) if HAS_JEDI else None

    def resolve_calls(self, file_path: str, source: str, calls: list[CallInfo]):
        if not self.project:
            return
        try:
            script = jedi.Script(source, path=file_path, project=self.project)
        except Exception as e:
            logger.debug("Jedi init failed %s: %s", file_path, e)
            return
        lines = source.splitlines()
        for call in calls:
            try:
                simple = call.callee_name.rsplit(".", 1)[-1]
                col = lines[call.line_number - 1].find(simple) if 0 < call.line_number <= len(lines) else 0
                names = script.goto(call.line_number, col, follow_imports=True)
                if names and names[0].full_name:
                    call.resolved_fqn = names[0].full_name
            except Exception:
                pass


# ── Project scanner ───────────────────────────────────────────────────────────

class PythonProjectScanner:
    def __init__(self, project_path: str, project_id: str):
        self.project_path = Path(project_path).resolve()
        self.project_id = project_id
        self.resolver = JediResolver(str(self.project_path))
        self.modules: list[ModuleInfo] = []
        self.packages: set[str] = set()
        self.classes: list[ClassInfo] = []
        self.functions: list[FunctionInfo] = []
        self.imports: list[ImportInfo] = []
        self.calls: list[CallInfo] = []

    def scan(self):
        py_files = self._find_py_files()
        logger.info("Found %d .py files", len(py_files))

        for i, f in enumerate(py_files, 1):
            if i % 50 == 0:
                logger.info("  Progress: %d/%d", i, len(py_files))
            self._analyze_file(f)

        if HAS_JEDI:
            logger.info("Running Jedi on %d calls...", len(self.calls))
            resolved = 0
            for f in py_files:
                mod_fqn = self._file_to_module_fqn(f)
                file_calls = [c for c in self.calls if mod_fqn in c.caller_fqn]
                if not file_calls:
                    continue
                try:
                    source = f.read_text(encoding="utf-8", errors="ignore")
                    self.resolver.resolve_calls(str(f), source, file_calls)
                    resolved += sum(1 for c in file_calls if c.resolved_fqn)
                except Exception as e:
                    logger.debug("Jedi failed %s: %s", f, e)
            logger.info("  Jedi resolved %d/%d calls", resolved, len(self.calls))

        return self

    def _find_py_files(self) -> list[Path]:
        files = []
        for root, dirs, filenames in os.walk(self.project_path):
            dirs[:] = [d for d in dirs
                       if d not in _IGNORE_DIRS and not d.endswith(".egg-info")]
            for f in filenames:
                if f.endswith(".py"):
                    files.append(Path(root) / f)
        return sorted(files)

    def _analyze_file(self, py_file: Path):
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning("Read failed %s: %s", py_file, e)
            return

        module_fqn = self._file_to_module_fqn(py_file)
        package_fqn = self._file_to_package_fqn(py_file)

        if package_fqn:
            parts = package_fqn.split(".")
            for i in range(len(parts)):
                self.packages.add(".".join(parts[:i+1]))

        docstring = ""
        if source.strip():
            try:
                docstring = (ast.get_docstring(ast.parse(source)) or "")[:500]
            except Exception:
                pass

        self.modules.append(ModuleInfo(
            fqn=module_fqn, name=py_file.stem, file_path=str(py_file),
            package=package_fqn, line_count=len(source.splitlines()),
            docstring=docstring,
        ))

        analyzer = PythonASTAnalyzer(module_fqn, source, str(py_file))
        analyzer.analyze()
        self.classes.extend(analyzer.classes)
        self.functions.extend(analyzer.functions)
        self.imports.extend(analyzer.imports)
        self.calls.extend(analyzer.calls)

    def _file_to_module_fqn(self, py_file: Path) -> str:
        try:
            rel = py_file.relative_to(self.project_path)
        except ValueError:
            return py_file.stem
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
            if not parts:
                return self.project_id
        else:
            parts[-1] = parts[-1].removesuffix(".py")
        return ".".join(parts)

    def _file_to_package_fqn(self, py_file: Path) -> str:
        try:
            rel = py_file.relative_to(self.project_path)
        except ValueError:
            return ""
        parts = list(rel.parent.parts)
        return ".".join(parts) if parts else ""


# ── Neo4j writer ──────────────────────────────────────────────────────────────

class PythonNeo4jWriter:
    def __init__(self, graph: GraphClient):
        self.graph = graph

    async def write(self, scanner: PythonProjectScanner) -> ScanResult:
        pid = scanner.project_id
        t0 = time.time()
        result = ScanResult(project_id=pid, language="python")

        # Ensure indexes
        await self.graph.create_indexes(PYTHON_SCHEMA.index_statements())

        # Clean old data
        await self._clean_project(pid)

        # Write in order
        await self._write_packages(scanner.packages, pid)
        await self._write_modules(scanner.modules, pid)
        await self._write_classes(scanner.classes, pid)
        await self._write_functions(scanner.functions, pid)
        await self._write_inheritance(scanner.classes, pid)
        await self._write_imports(scanner.imports, pid)
        await self._write_calls(scanner.calls, pid)

        # Detect overrides
        overrides = await self.graph.run_scalar(
            """
            MATCH (child:Python:Class {project: $p})-[:EXTENDS]->(parent:Python:Class)
            MATCH (child)-[:DECLARES]->(cm:Python:Function)
            MATCH (parent)-[:DECLARES]->(pm:Python:Function)
            WHERE cm.name = pm.name AND cm.name <> '__init__'
            MERGE (cm)-[:OVERRIDES]->(pm)
            RETURN count(*) AS cnt
            """,
            p=pid,
        )
        logger.info("  OVERRIDES: %d", overrides or 0)

        elapsed = time.time() - t0
        result.files_scanned = len(scanner.modules)
        result.nodes_written = len(scanner.classes) + len(scanner.functions) + len(scanner.modules)
        result.details = {
            "packages": len(scanner.packages), "modules": len(scanner.modules),
            "classes": len(scanner.classes), "functions": len(scanner.functions),
            "elapsed": round(elapsed, 1),
        }
        logger.info("Python write complete (%.1fs)", elapsed)
        return result

    async def _clean_project(self, pid: str):
        for label in ("Function", "Class", "Module", "Package"):
            await self.graph.run(
                f"MATCH (n:Python:{label} {{project: $p}}) DETACH DELETE n", p=pid
            )
        logger.info("Cleaned project %s", pid)

    async def _write_packages(self, packages: set[str], pid: str):
        for pkg in sorted(packages):
            await self.graph.run(
                "MERGE (p:Python:Package {fqn: $fqn, project: $pid}) SET p.name = $name",
                fqn=pkg, pid=pid, name=pkg.rsplit(".", 1)[-1],
            )
            if "." in pkg:
                parent = pkg.rsplit(".", 1)[0]
                await self.graph.run(
                    "MATCH (parent:Python:Package {fqn:$p, project:$pid})"
                    " MATCH (child:Python:Package {fqn:$c, project:$pid})"
                    " MERGE (parent)-[:CONTAINS]->(child)",
                    p=parent, c=pkg, pid=pid,
                )
        logger.info("  Packages: %d", len(packages))

    async def _write_modules(self, modules: list[ModuleInfo], pid: str):
        for m in modules:
            await self.graph.run(
                "MERGE (mod:Python:Module {fqn:$fqn, project:$pid})"
                " SET mod.name=$name, mod.file_path=$fp, mod.line_count=$lc, mod.docstring=$doc",
                fqn=m.fqn, pid=pid, name=m.name, fp=m.file_path,
                lc=m.line_count, doc=m.docstring[:500],
            )
            if m.package:
                await self.graph.run(
                    "MATCH (p:Python:Package {fqn:$pkg, project:$pid})"
                    " MATCH (m:Python:Module {fqn:$mod, project:$pid})"
                    " MERGE (p)-[:CONTAINS]->(m)",
                    pkg=m.package, mod=m.fqn, pid=pid,
                )
        logger.info("  Modules: %d", len(modules))

    async def _write_classes(self, classes: list[ClassInfo], pid: str):
        for c in classes:
            await self.graph.run(
                "MERGE (cls:Python:Class {fqn:$fqn, project:$pid})"
                " SET cls.name=$name, cls.module_fqn=$mfqn, cls.line_number=$line,"
                "     cls.docstring=$doc, cls.is_dataclass=$is_dc",
                fqn=c.fqn, pid=pid, name=c.name, mfqn=c.module_fqn,
                line=c.line_number, doc=c.docstring[:500], is_dc=c.is_dataclass,
            )
            await self.graph.run(
                "MATCH (m:Python:Module {fqn:$mod, project:$pid})"
                " MATCH (c:Python:Class {fqn:$cls, project:$pid})"
                " MERGE (m)-[:CONTAINS]->(c)",
                mod=c.module_fqn, cls=c.fqn, pid=pid,
            )
        logger.info("  Classes: %d", len(classes))

    async def _write_functions(self, functions: list[FunctionInfo], pid: str):
        for f in functions:
            await self.graph.run(
                "MERGE (fn:Python:Function {fqn:$fqn, project:$pid})"
                " SET fn.name=$name, fn.module_fqn=$mfqn, fn.class_fqn=$cfqn,"
                "     fn.line_number=$line, fn.docstring=$doc, fn.is_method=$im,"
                "     fn.is_static=$is_static, fn.is_classmethod=$ic, fn.is_property=$ip,"
                "     fn.is_async=$ia, fn.parameter_count=$pc, fn.parameters=$params",
                fqn=f.fqn, pid=pid, name=f.name, mfqn=f.module_fqn, cfqn=f.class_fqn,
                line=f.line_number, doc=f.docstring[:500],
                im=f.is_method, is_static=f.is_static, ic=f.is_classmethod,
                ip=f.is_property, ia=f.is_async,
                pc=len(f.parameters), params=f.parameters,
            )
            if f.class_fqn:
                await self.graph.run(
                    "MATCH (c:Python:Class {fqn:$cls, project:$pid})"
                    " MATCH (fn:Python:Function {fqn:$func, project:$pid})"
                    " MERGE (c)-[:DECLARES]->(fn)",
                    cls=f.class_fqn, func=f.fqn, pid=pid,
                )
            else:
                await self.graph.run(
                    "MATCH (m:Python:Module {fqn:$mod, project:$pid})"
                    " MATCH (fn:Python:Function {fqn:$func, project:$pid})"
                    " MERGE (m)-[:CONTAINS]->(fn)",
                    mod=f.module_fqn, func=f.fqn, pid=pid,
                )
        logger.info("  Functions: %d", len(functions))

    async def _write_inheritance(self, classes: list[ClassInfo], pid: str):
        count = 0
        for c in classes:
            for base in c.bases:
                r = await self.graph.run_scalar(
                    "MATCH (child:Python:Class {fqn:$cfqn, project:$pid})"
                    " MATCH (parent:Python:Class {project:$pid})"
                    " WHERE parent.name=$bname OR parent.fqn ENDS WITH $bsuffix"
                    " MERGE (child)-[:EXTENDS]->(parent)"
                    " RETURN count(*) AS cnt",
                    cfqn=c.fqn, pid=pid, bname=base, bsuffix=f".{base}",
                )
                if r:
                    count += r
                else:
                    await self.graph.run(
                        "MATCH (c:Python:Class {fqn:$fqn, project:$pid})"
                        " SET c.external_bases = coalesce(c.external_bases, []) + $base",
                        fqn=c.fqn, pid=pid, base=base,
                    )
        logger.info("  EXTENDS: %d", count)

    async def _write_imports(self, imports: list[ImportInfo], pid: str):
        count = 0
        for imp in imports:
            r = await self.graph.run_scalar(
                "MATCH (src:Python:Module {fqn:$src, project:$pid})"
                " MATCH (tgt:Python:Module {project:$pid})"
                " WHERE tgt.fqn=$target OR tgt.fqn ENDS WITH $tsuffix"
                " MERGE (src)-[:IMPORTS {names:$names}]->(tgt)"
                " RETURN count(*) AS cnt",
                src=imp.module_fqn, pid=pid, target=imp.target,
                tsuffix=f".{imp.target}", names=imp.imported_names,
            )
            if r: count += r
        logger.info("  IMPORTS: %d", count)

    async def _write_calls(self, calls: list[CallInfo], pid: str):
        batch = [
            {
                "caller": c.caller_fqn,
                "callee": c.resolved_fqn or c.callee_name,
                "callee_name": c.callee_name.rsplit(".", 1)[-1],
                "line": c.line_number,
            }
            for c in calls
        ]
        if not batch:
            return
        count = await self.graph.run_scalar(
            """
            UNWIND $batch AS row
            MATCH (caller:Python:Function {fqn: row.caller, project: $pid})
            MATCH (callee:Python:Function {project: $pid})
            WHERE callee.fqn = row.callee OR callee.fqn ENDS WITH '.' + row.callee_name
            MERGE (caller)-[inv:INVOKES]->(callee)
            ON CREATE SET inv.line_number = row.line
            RETURN count(*) AS cnt
            """,
            batch=batch, pid=pid,
        )
        logger.info("  INVOKES: %d / %d calls", count or 0, len(calls))


# ── Public API ────────────────────────────────────────────────────────────────

class PythonScanner:
    def __init__(self, graph: GraphClient):
        self.graph = graph
        self._writer = PythonNeo4jWriter(graph)

    async def scan(self, project_path: Path, project_id: str) -> ScanResult:
        scanner = PythonProjectScanner(str(project_path), project_id)
        scanner.scan()
        return await self._writer.write(scanner)
