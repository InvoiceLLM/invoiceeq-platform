#!/usr/bin/env python
"""Stop guard — product source changed, but no tracker entry was filed with it.

Layer 2 of the anti-hardcoding harness. It enforces a rule this repo already has and has
been breaking silently: no code change lands without a matching Gap (or feature task) entry
filed as part of the same change. The entry is where the defect CLASS gets stated, and a
symptom-shaped entry is the cheapest early warning that the fix under it is local.

Blocks once per session. `stop_hook_active` and a per-session sentinel keep it from looping:
if the answer is "this genuinely needs no entry", saying so and stopping again is enough.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

SOURCE_SUFFIXES = (".py", ".ts", ".tsx")

EXCLUDED_PARTS = (
    "/node_modules/",
    "/.venv/",
    "/__pycache__/",
    "/.next",
    "/showcase/",
    "/.claude/",
)

REQUIRED_PART = "/apps/"

TRACKER_MARKERS = ("_features_tracker.md", "website_features_tracker.md")


def changed_files(repo: str) -> list[str]:
    files: list[str] = []
    for args in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        try:
            r = subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            files.extend(line.strip() for line in r.stdout.splitlines() if line.strip())
    return files


def is_product_source(path: str) -> bool:
    p = "/" + path.replace("\\", "/").lstrip("/")
    if not p.endswith(SOURCE_SUFFIXES):
        return False
    if REQUIRED_PART not in p:
        return False
    return not any(part in p for part in EXCLUDED_PARTS)


def is_tracker(path: str) -> bool:
    return any(path.replace("\\", "/").endswith(m) for m in TRACKER_MARKERS)


def sentinel_path(session_id: str) -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "nosession"
    return os.path.join(tempfile.gettempdir(), f"claude-gapgate-{safe}")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("stop_hook_active"):
        return 0

    session_id = str(payload.get("session_id", ""))
    sentinel = sentinel_path(session_id)
    if os.path.exists(sentinel):
        return 0

    repo = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    files = changed_files(repo)
    source = sorted({f for f in files if is_product_source(f)})
    if not source:
        return 0
    if any(is_tracker(f) for f in files):
        return 0

    try:
        with open(sentinel, "w", encoding="utf-8") as fh:
            fh.write(session_id)
    except OSError:
        pass

    shown = source[:10]
    more = f"\n  ... and {len(source) - len(shown)} more" if len(source) > len(shown) else ""

    reason = (
        "Product source changed but no tracker entry was filed in the same change:\n  "
        + "\n  ".join(shown)
        + more
        + "\n\nThis repo's rule: every code change carries a matching Gap or feature-task entry "
        "in the app's `*_features_tracker.md`, filed as part of the change — not after.\n\n"
        "Before filing it, check the entry's shape. An entry that describes a SYMPTOM "
        "(\"PO-VPI-1041 shows the wrong days\") rather than a DEFECT CLASS (\"a card computes "
        "days-from-term and labels it days-from-today\") is the signal that the fix under it is "
        "local. State the class, and say how many call sites have the defect versus how many "
        "you fixed.\n\n"
        "If this change genuinely needs no entry (harness, tooling, docs-only), say so and stop "
        "again — this gate fires once per session."
    )

    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
