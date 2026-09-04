#!/usr/bin/env python3
"""
Dependency Parser for Markdown Functionality Files
This script recursively scans a directory of Markdown files, extracts metadata
(such as titles and descriptions), detects explicit and implicit dependencies
between them, and outputs a structured JSON graph (nodes and edges).

It leverages three detection strategies:
1. Markdown Links: e.g., [User Auth](auth.md)
2. Wiki Links: e.g., [[payment-gateway]]
3. Explicit YAML Frontmatter or inline metadata: e.g., "Depends on: billing" or YAML "dependencies: [auth]"

Fixes vs. the original version:
- Node ids are now the file's *relative path* (posix-style), not the bare
  filename. The original used `os.path.basename(filepath).lower()` as the id,
  which silently collapsed every file with the same name (e.g. 39 different
  README.md files across the repo, 8 different SKILL.md files) into a single
  graph node. Any edge pointing at "readme.md" was therefore ambiguous and
  could resolve to the wrong file. Ids are now unique per file.
- Dependency links are resolved against the actual file tree: first by path
  relative to the linking file's directory, then by a same-directory or
  unique-basename match. A link whose target name matches more than one file
  and can't be disambiguated is dropped (logged to stderr) instead of being
  silently wired to an arbitrary file.
- Directories that are build output / dependencies / caches, not project
  docs, are skipped during the scan: node_modules, .venv, venv, env, myenv,
  __pycache__, .git, .pytest_cache, .next, dist, build, site-packages,
  .mypy_cache, .ruff_cache, .tox, coverage, htmlcov. Configurable via
  --exclude-dir (repeatable) and --exclude-name-contains (repeatable) so this
  doesn't have to be manually re-cleaned after every `npm install` /
  `pip install`.
"""

import os
import re
import sys
import json
import argparse
from typing import Dict, List, Set, Any, Optional

# Regular expressions for dependency extraction
MARKDOWN_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+\.md)\)')
WIKI_LINK_RE = re.compile(r'\[\[([^\]]+)\]\]')
DEPENDS_ON_TEXT_RE = re.compile(r'(?:depends\s+on|dependencies|requires):\s*\[?([a-zA-Z0-9_\-\s,\.]+)(?:\])?', re.IGNORECASE)
TITLE_RE = re.compile(r'^#\s+(.+)$', re.MULTILINE)

# Directories that are never project documentation: dependencies, caches,
# build output, virtualenvs. Matched by exact directory name (case-insensitive).
DEFAULT_EXCLUDE_DIRS = {
    "node_modules", ".venv", "venv", "env", "myenv", "__pycache__", ".git",
    ".pytest_cache", ".next", "dist", "build", "site-packages",
    ".mypy_cache", ".ruff_cache", ".tox", "coverage", "htmlcov",
    ".pytest_cache", "out", ".turbo", ".cache",
}


def is_excluded_dir(name: str, extra_exact: Set[str], extra_contains: List[str]) -> bool:
    lname = name.lower()
    if lname in DEFAULT_EXCLUDE_DIRS or lname in extra_exact:
        return True
    for token in extra_contains:
        if token.lower() in lname:
            return True
    return False


def parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Parses simple YAML-like frontmatter if present."""
    frontmatter = {}
    remaining_content = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            remaining_content = parts[2]
            for line in fm_text.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip().lower()
                    val = val.strip().strip('"\'')
                    # Parse simple list
                    if val.startswith('[') and val.endswith(']'):
                        val = [item.strip().strip('"\'') for item in val[1:-1].split(',') if item.strip()]
                    frontmatter[key] = val
    return frontmatter, remaining_content


def to_posix(rel_path: str) -> str:
    return rel_path.replace(os.sep, '/')


def node_id_for(directory: str, filepath: str) -> str:
    """Stable, unique node id: path relative to the scan root, posix-style."""
    rel = os.path.relpath(filepath, directory)
    return to_posix(rel)


def extract_raw_links(content: str, frontmatter: Dict[str, Any]) -> List[str]:
    """Collect raw (unresolved) dependency targets as written in the file."""
    raw_targets: List[str] = []

    fm_deps = frontmatter.get('dependencies') or frontmatter.get('depends_on')
    if fm_deps:
        if isinstance(fm_deps, list):
            raw_targets.extend(str(d).strip() for d in fm_deps)
        elif isinstance(fm_deps, str):
            raw_targets.append(fm_deps.strip())

    for _, target in MARKDOWN_LINK_RE.findall(content):
        raw_targets.append(target.strip())

    for target in WIKI_LINK_RE.findall(content):
        t = target.strip()
        if not t.lower().endswith('.md'):
            t += '.md'
        raw_targets.append(t)

    for match in DEPENDS_ON_TEXT_RE.findall(content):
        for p in (p.strip() for p in match.split(',')):
            if p:
                if not p.lower().endswith('.md'):
                    p += '.md'
                raw_targets.append(p)

    return raw_targets


def extract_metadata(filepath: str) -> Dict[str, Any]:
    """Parses a single markdown file to extract its title, description, and raw links."""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        raw_content = f.read()

    frontmatter, content = parse_frontmatter(raw_content)

    title = frontmatter.get('title')
    if not title:
        title_match = TITLE_RE.search(content)
        title = title_match.group(1).strip() if title_match else os.path.splitext(os.path.basename(filepath))[0]

    description = frontmatter.get('description')
    if not description:
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        description_candidate = ""
        for p in paragraphs:
            clean_p = p.replace('\n', ' ').strip()
            if not clean_p.startswith('#') and not clean_p.startswith('-') and not clean_p.startswith('*'):
                description_candidate = clean_p[:150] + '...' if len(clean_p) > 150 else clean_p
                break
        description = description_candidate if description_candidate else "No description provided."

    raw_links = extract_raw_links(content, frontmatter)

    return {
        "title": title,
        "description": description,
        "raw_links": raw_links,
        "filepath": filepath,
    }


def build_indexes(directory: str, md_files: List[str]):
    """Build lookup indexes used to resolve dependency targets to node ids."""
    by_full_rel: Dict[str, str] = {}   # normalized relative path -> node id
    by_dir_and_name: Dict[tuple, str] = {}  # (dir_rel, basename_lower) -> node id
    by_basename: Dict[str, List[str]] = {}  # basename_lower -> [node ids]

    for f in md_files:
        nid = node_id_for(directory, f)
        rel_dir = os.path.dirname(nid)
        basename_lower = os.path.basename(nid).lower()

        by_full_rel[nid.lower()] = nid
        by_dir_and_name[(rel_dir, basename_lower)] = nid
        by_basename.setdefault(basename_lower, []).append(nid)

    return by_full_rel, by_dir_and_name, by_basename


def resolve_target(raw_target: str, source_id: str, by_full_rel, by_dir_and_name, by_basename) -> Optional[str]:
    """Resolve a raw link target string to a unique node id, or None if unresolvable."""
    target = raw_target.strip().strip('"\'')
    target = target.split('#')[0]  # drop any #anchor
    if not target:
        return None

    source_dir = os.path.dirname(source_id)

    # 1. Resolve as a path relative to the linking file's directory.
    candidate = to_posix(os.path.normpath(os.path.join(source_dir, target)))
    if candidate.lower() in by_full_rel:
        return by_full_rel[candidate.lower()]

    # 2. Resolve as a path relative to the scan root.
    candidate_root = to_posix(os.path.normpath(target))
    if candidate_root.lower() in by_full_rel:
        return by_full_rel[candidate_root.lower()]

    basename_lower = os.path.basename(target).lower()

    # 3. Same-directory file with this basename.
    same_dir_match = by_dir_and_name.get((source_dir, basename_lower))
    if same_dir_match:
        return same_dir_match

    # 4. Globally unique basename match.
    matches = by_basename.get(basename_lower, [])
    if len(matches) == 1:
        return matches[0]

    # Ambiguous (or no match at all) -- don't guess.
    return None


def build_graph(directory: str, extra_exclude_exact: Set[str], extra_exclude_contains: List[str], verbose: bool = False) -> Dict[str, Any]:
    """Scans directory for markdown files and builds the graph structure."""
    md_files = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not is_excluded_dir(d, extra_exclude_exact, extra_exclude_contains)]
        for file in files:
            if file.lower().endswith('.md'):
                md_files.append(os.path.join(root, file))

    by_full_rel, by_dir_and_name, by_basename = build_indexes(directory, md_files)

    nodes = []
    edges = []
    dropped_ambiguous = 0

    for filepath in md_files:
        meta = extract_metadata(filepath)
        node_id = node_id_for(directory, filepath)

        nodes.append({
            "id": node_id,
            "name": meta["title"],
            "type": "capability",
            "description": meta["description"],
            "source_path": to_posix(os.path.relpath(filepath, directory)),
        })

        seen_targets = set()
        for raw in meta["raw_links"]:
            resolved = resolve_target(raw, node_id, by_full_rel, by_dir_and_name, by_basename)
            if resolved is None:
                if verbose and os.path.basename(raw):
                    print(f"  [unresolved] {node_id} -> '{raw}'", file=sys.stderr)
                continue
            if resolved == node_id:
                continue  # self-dependency
            if resolved in seen_targets:
                continue
            seen_targets.add(resolved)
            edges.append({
                "source": node_id,
                "target": resolved,
                "predicate": "DEPENDS_ON",
            })

    return {
        "metadata": {
            "total_files": len(nodes),
            "total_dependencies": len(edges),
            "directory": os.path.abspath(directory),
        },
        "nodes": nodes,
        "edges": edges,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a dependency JSON graph from Markdown files.")
    parser.add_argument("directory", nargs="?", default=".", help="Directory containing markdown files (default: current directory)")
    parser.add_argument("-o", "--output", default="dependency_graph.json", help="Path to write the output JSON file")
    parser.add_argument("--exclude-dir", action="append", default=[], help="Additional directory name to exclude (exact match, repeatable)")
    parser.add_argument("--exclude-name-contains", action="append", default=[], help="Exclude any directory whose name contains this substring (repeatable)")
    parser.add_argument("--verbose", action="store_true", help="Print unresolved link targets to stderr")

    args = parser.parse_args()

    if not os.path.exists(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist.")
        return

    extra_exact = {d.lower() for d in args.exclude_dir}

    print(f"Scanning '{args.directory}' for Markdown files...")
    graph = build_graph(args.directory, extra_exact, args.exclude_name_contains, verbose=args.verbose)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    print(f"Successfully compiled graph!")
    print(f"  - Detected Files (Nodes): {graph['metadata']['total_files']}")
    print(f"  - Detected Links (Edges): {graph['metadata']['total_dependencies']}")
    print(f"  - Saved to: {args.output}")


if __name__ == "__main__":
    main()
