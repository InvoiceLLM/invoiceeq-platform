#!/usr/bin/env python3
"""
Code-level dependency / change-impact graph for a Python + TS/TSX/JS/JSX codebase.

This is a DIFFERENT tool from dependency_parser.py. That one maps markdown
docs to markdown docs. This one maps actual source files to the source files
they import, so you can answer: "if I change agents/query_agent.py, what
else in this repo could break?"

Usage:
    # Build the graph for one app
    python code_dependency_graph.py Prod_Invoice_LLM/apps/invoice-be -o be_code_graph.json --lang py

    python code_dependency_graph.py Prod_Invoice_LLM/apps/invoice-fe -o fe_code_graph.json --lang ts

    # Ask "what breaks if I change this file" (direct + transitive dependents)
    python code_dependency_graph.py Prod_Invoice_LLM/apps/invoice-be --impact agents/query_agent.py

Notes / limits (read before trusting this for anything):
- Python resolution walks the scanned directory to build a dotted-module ->
  file map, then resolves `import x.y.z` / `from x.y import z` / relative
  imports (`from . import z`, `from ..pkg import z`) against that map.
  Imports it can't resolve locally (stdlib, pip packages) are treated as
  external and dropped -- this is a signal, not a hard fact: dynamic imports
  (`importlib.import_module(some_var)`), imports inside `try/except`, and
  string-built import paths are invisible to a static parser and will not
  appear as edges.
- TS/TSX/JS/JSX resolution is regex-based (import/export .. from '...',
  require('...'), dynamic import('...')). Only relative imports
  (./ or ../) and the '@/' Next.js-style root alias are resolved; other bare
  aliases (tsconfig "paths" beyond '@/') are not read, so those edges will
  be missing unless you pass --alias again for each one.
- Both scans automatically skip node_modules, .venv, venv, myenv, __pycache__,
  .git, .next, dist, build, .pytest_cache, and test directories are included
  (not excluded) since tests are real consumers of the code they import --
  pass --exclude-dir to skip more.
- This tells you direct static import relationships and their transitive
  closure. It does NOT understand runtime behavior, dependency injection,
  FastAPI route registration via string paths, or Next.js file-based routing
  (a page file "importing" nothing can still be reachable via its path).
  Treat the impact list as "definitely check these", not "only these".
"""

import os
import re
import sys
import json
import argparse
from typing import Dict, List, Set, Tuple

DEFAULT_EXCLUDE_DIRS = {
    "node_modules", ".venv", "venv", "env", "myenv", "__pycache__", ".git",
    ".next", "dist", "build", "site-packages", ".mypy_cache", ".ruff_cache",
    ".tox", "coverage", "htmlcov", ".pytest_cache", "out", ".turbo", ".cache",
}

PY_EXT = ".py"
TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

IMPORT_FROM_RE = re.compile(r'''(?:^|\n)\s*(?:export\s+)?(?:import|export)[^;\n]*?\bfrom\s+["']([^"']+)["']''')
BARE_IMPORT_RE = re.compile(r'''(?:^|\n)\s*import\s+["']([^"']+)["']''')
REQUIRE_RE = re.compile(r'''require\(\s*["']([^"']+)["']\s*\)''')
DYNAMIC_IMPORT_RE = re.compile(r'''import\(\s*["']([^"']+)["']\s*\)''')


def is_excluded_dir(name: str, extra: Set[str]) -> bool:
    lname = name.lower()
    if lname in DEFAULT_EXCLUDE_DIRS or lname in extra:
        return True
    # Next.js build output isn't always literally ".next" -- a project can
    # point distDir at ".next-proxy", ".next-sandbox", etc. for parallel
    # build targets. Any dir starting with ".next" is build output, never
    # source, so exclude the whole family rather than only the exact name.
    if lname.startswith(".next"):
        return True
    return False


def to_posix(p: str) -> str:
    return p.replace(os.sep, "/")


def walk_files(directory: str, exts: Tuple[str, ...], extra_exclude: Set[str]) -> List[str]:
    out = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not is_excluded_dir(d, extra_exclude)]
        for f in files:
            if f.endswith(exts):
                out.append(os.path.join(root, f))
    return out


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

def build_py_module_map(root: str, files: List[str]) -> Dict[str, str]:
    """dotted module path (from scan root) -> node id (relative file path)."""
    mod_map = {}
    for f in files:
        rel = os.path.relpath(f, root)
        node_id = to_posix(rel)
        parts = rel[:-len(PY_EXT)].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        dotted = ".".join(parts)
        if dotted:
            mod_map[dotted] = node_id
        # also register the package dir itself if this is __init__.py
    return mod_map


def parse_py_imports(filepath: str):
    """Returns list of (module_dotted_or_None, level, imported_names)."""
    import ast
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=filepath)
    except SyntaxError:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name, 0, None))
        elif isinstance(node, ast.ImportFrom):
            results.append((node.module, node.level or 0, [a.name for a in node.names]))
    return results


def resolve_py_target(module: str, level: int, source_node_id: str, mod_map: Dict[str, str], root: str):
    if level and level > 0:
        # relative import: resolve against the source file's package dir
        base_parts = source_node_id.split("/")[:-1]  # directory of the source file
        # each level beyond 1 goes up one more package
        up = level - 1
        if up > 0:
            base_parts = base_parts[:-up] if up <= len(base_parts) else []
        if module:
            base_parts = base_parts + module.split(".")
        dotted = ".".join(base_parts)
        return mod_map.get(dotted)
    if not module:
        return None
    # absolute import -- try the full dotted path, then progressively shorter
    # prefixes (handles `import pkg.sub` resolving to pkg/sub/__init__.py etc.)
    parts = module.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in mod_map:
            return mod_map[candidate]
    return None


def build_py_graph(root: str, extra_exclude: Set[str], verbose: bool):
    files = walk_files(root, (PY_EXT,), extra_exclude)
    mod_map = build_py_module_map(root, files)
    nodes = []
    edges = []
    for f in files:
        node_id = to_posix(os.path.relpath(f, root))
        nodes.append({"id": node_id, "language": "python"})
        seen_targets = set()
        for module, level, _names in parse_py_imports(f):
            target = resolve_py_target(module, level, node_id, mod_map, root)
            if target is None or target == node_id:
                if verbose and module:
                    print(f"  [unresolved-py] {node_id} -> {'.' * level}{module or ''}", file=sys.stderr)
                continue
            # A file can `from X import a` and later `from X import b` (or
            # re-import the same module inside a function), producing several
            # ImportFrom/Import nodes for the same target. Dedupe to one edge
            # per (source, target) pair so total_dependencies reflects real
            # file-to-file relationships instead of import-statement count.
            if target in seen_targets:
                continue
            seen_targets.add(target)
            edges.append({"source": node_id, "target": target, "predicate": "IMPORTS"})
    return nodes, edges


# ---------------------------------------------------------------------------
# TS / TSX / JS / JSX
# ---------------------------------------------------------------------------

def extract_ts_specifiers(content: str) -> List[str]:
    specs = []
    specs += IMPORT_FROM_RE.findall(content)
    specs += BARE_IMPORT_RE.findall(content)
    specs += REQUIRE_RE.findall(content)
    specs += DYNAMIC_IMPORT_RE.findall(content)
    return specs


def resolve_ts_target(spec: str, source_node_id: str, files_by_norm: Dict[str, str], root: str, alias_prefixes: List[str]):
    if spec.startswith("./") or spec.startswith("../"):
        base_dir = os.path.dirname(source_node_id)
        candidate = os.path.normpath(os.path.join(base_dir, spec))
    else:
        matched_alias = None
        for alias, target_dir in alias_prefixes:
            if spec.startswith(alias):
                matched_alias = (alias, target_dir)
                break
        if not matched_alias:
            return None
        alias, target_dir = matched_alias
        candidate = os.path.normpath(os.path.join(target_dir, spec[len(alias):]))

    candidate = to_posix(candidate)
    candidate_norm = candidate.lower()

    if candidate_norm in files_by_norm:
        return files_by_norm[candidate_norm]
    for ext in TS_EXTS:
        if (candidate_norm + ext) in files_by_norm:
            return files_by_norm[candidate_norm + ext]
    for ext in TS_EXTS:
        idx = f"{candidate_norm}/index{ext}"
        if idx in files_by_norm:
            return files_by_norm[idx]
    return None


def build_ts_graph(root: str, extra_exclude: Set[str], alias_prefixes: List[str], verbose: bool):
    files = walk_files(root, TS_EXTS, extra_exclude)
    node_ids = [to_posix(os.path.relpath(f, root)) for f in files]
    files_by_norm = {nid.lower(): nid for nid in node_ids}

    nodes = []
    edges = []
    for f, node_id in zip(files, node_ids):
        nodes.append({"id": node_id, "language": "typescript"})
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue
        seen_targets = set()
        for spec in extract_ts_specifiers(content):
            target = resolve_ts_target(spec, node_id, files_by_norm, root, alias_prefixes)
            if target is None or target == node_id:
                if verbose and (spec.startswith(".") or any(spec.startswith(a) for a, _ in alias_prefixes)):
                    print(f"  [unresolved-ts] {node_id} -> {spec}", file=sys.stderr)
                continue
            # Same file can import from the same module twice (named import
            # plus a later type-only import, etc.) -- dedupe to one edge.
            if target in seen_targets:
                continue
            seen_targets.add(target)
            edges.append({"source": node_id, "target": target, "predicate": "IMPORTS"})
    return nodes, edges


# ---------------------------------------------------------------------------
# Impact query
# ---------------------------------------------------------------------------

def compute_impact(nodes, edges, target_id: str):
    reverse: Dict[str, Set[str]] = {}
    all_ids = {n["id"] for n in nodes}
    for e in edges:
        reverse.setdefault(e["target"], set()).add(e["source"])

    if target_id not in all_ids:
        close = [n for n in all_ids if n.endswith(target_id) or target_id in n]
        return None, close

    visited = set()
    frontier = {target_id}
    layers = []
    while frontier:
        next_frontier = set()
        for node in frontier:
            for dependent in reverse.get(node, ()):
                if dependent not in visited and dependent != target_id:
                    next_frontier.add(dependent)
        next_frontier -= visited
        if not next_frontier:
            break
        layers.append(sorted(next_frontier))
        visited |= next_frontier
        frontier = next_frontier
    return layers, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build a code-level import graph and query change impact.")
    parser.add_argument("directory", help="App root to scan (e.g. Prod_Invoice_LLM/apps/invoice-be)")
    parser.add_argument("-o", "--output", default="code_dependency_graph.json")
    parser.add_argument("--lang", choices=["auto", "py", "ts"], default="auto")
    parser.add_argument("--exclude-dir", action="append", default=[])
    parser.add_argument("--alias", action="append", default=["@/:."],
                         help="TS path alias as PREFIX:TARGET_DIR relative to scanned root, repeatable. Default '@/:.' (Next.js root import alias).")
    parser.add_argument("--impact", help="Report what (transitively) imports this file (path relative to `directory`). Skips writing the graph file.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory.")
        return

    extra_exclude = {d.lower() for d in args.exclude_dir}
    alias_prefixes = []
    for a in args.alias:
        if ":" in a:
            prefix, target = a.split(":", 1)
            alias_prefixes.append((prefix, target))

    lang = args.lang
    if lang == "auto":
        has_py = any(f.endswith(PY_EXT) for f in os.listdir(args.directory)) or \
                 walk_files(args.directory, (PY_EXT,), extra_exclude)
        lang = "py" if has_py else "ts"

    if lang == "py":
        nodes, edges = build_py_graph(args.directory, extra_exclude, args.verbose)
    else:
        nodes, edges = build_ts_graph(args.directory, extra_exclude, alias_prefixes, args.verbose)

    if args.impact:
        target = to_posix(os.path.normpath(args.impact))
        layers, suggestions = compute_impact(nodes, edges, target)
        if layers is None:
            print(f"'{target}' not found as a node.")
            if suggestions:
                print("Did you mean one of:")
                for s in suggestions[:10]:
                    print(" -", s)
            return
        if not layers:
            print(f"Nothing in this scan statically imports '{target}' (directly or transitively).")
            return
        print(f"Files that depend on '{target}' (by import distance):")
        for depth, layer in enumerate(layers, start=1):
            print(f"  distance {depth}:")
            for item in layer:
                print(f"    - {item}")
        return

    graph = {
        "metadata": {
            "total_files": len(nodes),
            "total_dependencies": len(edges),
            "directory": os.path.abspath(args.directory),
            "language": lang,
        },
        "nodes": nodes,
        "edges": edges,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    print(f"Scanned '{args.directory}' ({lang}).")
    print(f"  - Files (nodes): {len(nodes)}")
    print(f"  - Import edges: {len(edges)}")
    print(f"  - Saved to: {args.output}")


if __name__ == "__main__":
    main()
