import ast
import os
from collections import defaultdict
from pathlib import Path

from .contracts import AgentContext, AgentFinding, AgentReport, AgentStatus


_MAX_MODULES = 1024
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_SOURCE_BYTES = 32 * 1024 * 1024
_MAX_TREE_ENTRIES = 20000


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self):
        self.scope_depth = 0
        self.imports = []

    def visit_FunctionDef(self, node):
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_AsyncFunctionDef(self, node):
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_Import(self, node):
        self.imports.append((node, self.scope_depth == 0))

    def visit_ImportFrom(self, node):
        self.imports.append((node, self.scope_depth == 0))


def _module_name(app_root: Path, source_path: Path) -> str:
    relative = source_path.relative_to(app_root.parent)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_exists(repo_root: Path, module_name: str) -> bool:
    if module_name == "app":
        return (repo_root / "app" / "__init__.py").is_file()
    if not module_name.startswith("app."):
        return False
    relative = Path(*module_name.split("."))
    module_file = repo_root / relative.with_suffix(".py")
    package_file = repo_root / relative / "__init__.py"
    return module_file.is_file() or package_file.is_file()


def _relative_base(
    current_module: str,
    level: int,
    module: str | None,
    *,
    package_initializer: bool = False,
) -> str | None:
    parts = current_module.split(".")
    package_parts = parts if package_initializer else parts[:-1]
    ascend = level - 1
    if level < 1 or ascend >= len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - ascend]
    if module:
        base_parts.extend(module.split("."))
    return ".".join(base_parts)


def _discover_python_sources(
    app_root: Path,
) -> tuple[list[Path], list[str], bool]:
    """Enumerate Python files without following symlink directories.

    The entry budget is enforced while walking, before building a complete
    recursive file list. Only in-tree regular Python files are returned.
    """
    root = app_root.resolve()
    pending = [root]
    sources: list[Path] = []
    skipped_symlinks: list[str] = []
    seen_entries = 0

    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                seen_entries += 1
                if seen_entries > _MAX_TREE_ENTRIES:
                    return sorted(sources), sorted(skipped_symlinks), True

                path = Path(entry.path)
                if entry.is_symlink():
                    try:
                        is_directory_link = entry.is_dir(follow_symlinks=True)
                    except OSError:
                        is_directory_link = False
                    if is_directory_link or entry.name.endswith(".py"):
                        skipped_symlinks.append(path.relative_to(root.parent).as_posix())
                    continue

                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".py"):
                    try:
                        if path.resolve().is_relative_to(root):
                            sources.append(path)
                        else:
                            skipped_symlinks.append(path.relative_to(root.parent).as_posix())
                    except OSError:
                        skipped_symlinks.append(path.relative_to(root.parent).as_posix())

    return sorted(sources), sorted(skipped_symlinks), False


def _resolve_import_targets(
    node: ast.Import | ast.ImportFrom,
    current_module: str,
    repo_root: Path,
    *,
    package_initializer: bool = False,
) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    unresolved: list[str] = []

    if isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.name
            if name == "app" or name.startswith("app."):
                if _module_exists(repo_root, name):
                    targets.append(name)
                else:
                    unresolved.append(name)
        return sorted(set(targets)), sorted(set(unresolved))

    if node.level:
        base = _relative_base(\n            current_module, node.level, node.module,\n            package_initializer=package_initializer,\n        )
        if base is None:
            unresolved.append(f"relative-import-level-{node.level}")
            return targets, unresolved
        if base == "app" or base.startswith("app."):
            if not _module_exists(repo_root, base):
                unresolved.append(base)
            else:
                targets.append(base)
            if node.module is None:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    if candidate == "app" or candidate.startswith("app."):
                        if _module_exists(repo_root, candidate):
                            targets.append(candidate)
        return sorted(set(targets)), sorted(set(unresolved))

    base = node.module
    if not base or not (base == "app" or base.startswith("app.")):
        return targets, unresolved

    if _module_exists(repo_root, base):
        targets.append(base)
    else:
        unresolved.append(base)

    if base == "app":
        for alias in node.names:
            if alias.name == "*":
                continue
            candidate = f"{base}.{alias.name}"
            if _module_exists(repo_root, candidate):
                targets.append(candidate)

    return sorted(set(targets)), sorted(set(unresolved))


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find strongly connected components iteratively (no Python recursion)."""
    nodes = set(graph)
    for targets in graph.values():
        nodes.update(targets)

    adjacency = {node: sorted(graph.get(node, set())) for node in nodes}
    reverse: dict[str, list[str]] = {node: [] for node in nodes}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].append(source)
    for targets in reverse.values():
        targets.sort()

    visited: set[str] = set()
    finish_order: list[str] = []
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[str, Any]] = [(start, iter(adjacency[start]))]
        while stack:
            node, children = stack[-1]
            try:
                target = next(children)
            except StopIteration:
                finish_order.append(node)
                stack.pop()
                continue
            if target not in visited:
                visited.add(target)
                stack.append((target, iter(adjacency[target])))

    assigned: set[str] = set()
    cycles: list[list[str]] = []
    for start in reversed(finish_order):
        if start in assigned:
            continue
        component: list[str] = []
        stack = [start]
        assigned.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for target in reverse[node]:
                if target not in assigned:
                    assigned.add(target)
                    stack.append(target)
        component.sort()
        if len(component) > 1 or (component and component[0] in graph.get(component[0], set())):
            cycles.append(component)
    return sorted(cycles)


class ArchitectureAgent:
    """Read-only AST analysis of app imports and module-boundary constraints."""

    role = "architecture"

    def run(self, context: AgentContext) -> AgentReport:
        repo_root = context.repo_root.resolve()
        app_root = repo_root / "app"
        if not app_root.is_dir():
            return AgentReport(
                role=self.role,
                status=AgentStatus.BLOCKED,
                findings=[
                    AgentFinding(
                        code="ARCH_APP_PACKAGE_MISSING",
                        severity="high",
                        message="The repository has no app/ source directory to inspect.",
                        remediation="Run the architecture specialist against the canonical OLA source checkout.",
                    )
                ],
                metrics={"source_commit": context.source_commit, "module_count": 0},
            )

        try:
            source_paths, skipped_symlinks, tree_entry_limit = _discover_python_sources(app_root)
        except OSError as exc:
            return AgentReport(
                role=self.role,
                status=AgentStatus.BLOCKED,
                findings=[
                    AgentFinding(
                        code="ARCH_SOURCE_DISCOVERY_BLOCKED",
                        severity="high",
                        message=f"Unable to enumerate source tree ({type(exc).__name__}).",
                        remediation="Restore repository read access and rerun the architecture scan.",
                    )
                ],
                metrics={"source_commit": context.source_commit, "module_count": 0},
            )

        if tree_entry_limit:
            return AgentReport(
                role=self.role,
                status=AgentStatus.BLOCKED,
                findings=[
                    AgentFinding(
                        code="ARCH_SCAN_TREE_ENTRY_LIMIT",
                        severity="high",
                        message=f"Source tree entry count exceeded the {_MAX_TREE_ENTRIES}-entry scan budget.",
                        remediation="Reduce the scan scope or split the repository into independently bounded packages.",
                    )
                ],
                metrics={
                    "source_commit": context.source_commit,
                    "module_count": len(source_paths),
                    "max_tree_entries": _MAX_TREE_ENTRIES,
                },
            )

        if len(source_paths) > _MAX_MODULES:
            return AgentReport(
                role=self.role,
                status=AgentStatus.BLOCKED,
                findings=[
                    AgentFinding(
                        code="ARCH_SCAN_MODULE_LIMIT",
                        severity="high",
                        message=f"Architecture scan found more than {_MAX_MODULES} Python modules.",
                        remediation="Split the scan into bounded package scopes and verify each scope independently.",
                    )
                ],
                metrics={
                    "source_commit": context.source_commit,
                    "module_count": len(source_paths),
                    "max_modules": _MAX_MODULES,
                },
            )

        module_sources: dict[str, tuple[Path, ast.Module]] = {}
        graph: dict[str, set[str]] = defaultdict(set)
        findings: list[AgentFinding] = []
        module_level_edges = 0
        deferred_imports = 0
        unresolved_count = 0
        syntax_error_count = 0
        composition_root_violations = 0
        total_source_bytes = 0

        for symlink_path in skipped_symlinks:
            findings.append(
                AgentFinding(
                    code="ARCH_SOURCE_SYMLINK_SKIPPED",
                    severity="medium",
                    message="A symlinked source path was excluded from the architecture scan.",
                    evidence_refs=(symlink_path,),
                    remediation="Replace the symlink with an explicitly reviewed in-repository source file.",
                )
            )

        for source_path in source_paths:
            relative_path = source_path.relative_to(repo_root).as_posix()
            if source_path.is_symlink() or not source_path.resolve().is_relative_to(app_root.resolve()):
                findings.append(
                    AgentFinding(
                        code="ARCH_SOURCE_SYMLINK_SKIPPED",
                        severity="medium",
                        message="A symlinked Python source file was excluded from the architecture scan.",
                        evidence_refs=(relative_path,),
                        remediation="Replace the symlink with an explicitly reviewed in-repository source file.",
                    )
                )
                continue
            try:
                source_bytes = source_path.stat().st_size
                total_source_bytes += source_bytes
                if total_source_bytes > _MAX_TOTAL_SOURCE_BYTES:
                    findings.append(
                        AgentFinding(
                            code="ARCH_SCAN_TOTAL_SOURCE_BYTES_LIMIT",
                            severity="high",
                            message=f"Aggregate Python source exceeds the {_MAX_TOTAL_SOURCE_BYTES}-byte scan budget.",
                            evidence_refs=(relative_path,),
                            remediation="Split the architecture scan into smaller bounded source scopes.",
                        )
                    )
                    break
                if source_bytes > _MAX_SOURCE_BYTES:
                    findings.append(
                        AgentFinding(
                            code="ARCH_SOURCE_FILE_TOO_LARGE",
                            severity="high",
                            message=f"Python source exceeds the {_MAX_SOURCE_BYTES}-byte scan limit.",
                            evidence_refs=(relative_path,),
                            remediation="Split the module into smaller cohesive files before enabling automated architecture checks.",
                        )
                    )
                    continue
                source_text = source_path.read_text(encoding="utf-8")
                tree = ast.parse(source_text, filename=relative_path)
            except UnicodeDecodeError:
                syntax_error_count += 1
                findings.append(
                    AgentFinding(
                        code="ARCH_SOURCE_ENCODING_ERROR",
                        severity="high",
                        message="Python source is not valid UTF-8.",
                        evidence_refs=(relative_path,),
                        remediation="Save the source file as UTF-8 and rerun the architecture scan.",
                    )
                )
                continue
            except SyntaxError as exc:
                syntax_error_count += 1
                findings.append(
                    AgentFinding(
                        code="ARCH_SYNTAX_ERROR",
                        severity="high",
                        message=f"Python syntax error at line {exc.lineno}: {exc.msg}.",
                        evidence_refs=(f"{relative_path}:{exc.lineno or 1}",),
                        remediation="Fix the syntax error before accepting the architecture report.",
                    )
                )
                continue
            except RecursionError:
                findings.append(
                    AgentFinding(
                        code="ARCH_AST_DEPTH_LIMIT",
                        severity="high",
                        message="Python AST parsing exceeded the interpreter recursion limit.",
                        evidence_refs=(relative_path,),
                        remediation="Reduce syntactic nesting or split the module into smaller functions/files.",
                    )
                )
                continue
            except OSError as exc:
                findings.append(
                    AgentFinding(
                        code="ARCH_SOURCE_READ_BLOCKED",
                        severity="high",
                        message=f"Unable to read Python source ({type(exc).__name__}).",
                        evidence_refs=(relative_path,),
                        remediation="Restore readable source access and rerun the architecture scan.",
                    )
                )
                continue

            module = _module_name(app_root, source_path)
            module_sources[module] = (source_path, tree)
            graph.setdefault(module, set())

            visitor = _ImportVisitor()
            try:
                visitor.visit(tree)
            except RecursionError:
                findings.append(
                    AgentFinding(
                        code="ARCH_AST_DEPTH_LIMIT",
                        severity="high",
                        message="AST traversal exceeded the interpreter recursion limit.",
                        evidence_refs=(relative_path,),
                        remediation="Reduce syntactic nesting or split the module into smaller functions/files.",
                    )
                )
                continue
            for node, is_module_level in visitor.imports:
                targets, unresolved = _resolve_import_targets(
                    node,
                    module,
                    repo_root,
                    package_initializer=source_path.name == "__init__.py",
                )
                for target in unresolved:
                    unresolved_count += 1
                    findings.append(
                        AgentFinding(
                            code="ARCH_UNRESOLVED_INTERNAL_IMPORT",
                            severity="high",
                            message=f"Internal import target '{target}' cannot be resolved within the app package.",
                            evidence_refs=(f"{relative_path}:{node.lineno}",),
                            remediation="Correct the module path or add the missing in-repository Python module.",
                        )
                    )
                for target in targets:
                    if target == "app.main" and module != "app.main":
                        composition_root_violations += 1
                        findings.append(
                            AgentFinding(
                                code="ARCH_API_COMPOSITION_ROOT_IMPORT",
                                severity="high",
                                message=f"Module '{module}' imports app.main; the API composition root must not be a dependency of application modules.",
                                evidence_refs=(f"{relative_path}:{node.lineno}",),
                                remediation="Move the shared capability into a lower-level module and keep app.main as the composition root.",
                            )
                        )
                    if is_module_level:
                        graph[module].add(target)
                        module_level_edges += 1
                    else:
                        deferred_imports += 1

        cycles = _strongly_connected_components(graph)
        for cycle in cycles:
            composition = " -> ".join(cycle + [cycle[0]])
            refs = tuple(
                f"{module_sources[module][0].relative_to(repo_root).as_posix()}"
                for module in cycle
                if module in module_sources
            )
            findings.append(
                AgentFinding(
                    code="ARCH_IMPORT_CYCLE",
                    severity="high",
                    message=f"Module-level import cycle detected: {composition}.",
                    evidence_refs=refs,
                    remediation="Invert the dependency or extract shared contracts into a lower-level module.",
                )
            )

        blocked_codes = {
            "ARCH_SCAN_TOTAL_SOURCE_BYTES_LIMIT",
            "ARCH_AST_DEPTH_LIMIT",
        }
        fatal_codes = {
            "ARCH_SYNTAX_ERROR",
            "ARCH_SOURCE_ENCODING_ERROR",
            "ARCH_UNRESOLVED_INTERNAL_IMPORT",
            "ARCH_API_COMPOSITION_ROOT_IMPORT",
            "ARCH_IMPORT_CYCLE",
            "ARCH_SOURCE_FILE_TOO_LARGE",
        }
        if any(item.code in blocked_codes for item in findings):
            status = AgentStatus.BLOCKED
        elif any(item.code in fatal_codes for item in findings):
            status = AgentStatus.FAIL
        elif findings:
            status = AgentStatus.UNKNOWN
        else:
            status = AgentStatus.PASS

        return AgentReport(
            role=self.role,
            status=status,
            findings=findings,
            metrics={
                "source_commit": context.source_commit,
                "module_count": len(module_sources),
                "module_level_import_edges": module_level_edges,
                "deferred_imports": deferred_imports,
                "cycle_count": len(cycles),
                "syntax_error_count": syntax_error_count,
                "unresolved_internal_imports": unresolved_count,
                "composition_root_violations": composition_root_violations,
                "scanned_source_bytes": total_source_bytes,
                "max_modules": _MAX_MODULES,
                "max_source_bytes_per_module": _MAX_SOURCE_BYTES,
                "max_total_source_bytes": _MAX_TOTAL_SOURCE_BYTES,
                "max_tree_entries": _MAX_TREE_ENTRIES,
            },
        )
