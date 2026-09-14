#!/usr/bin/env python
"""PostToolUse guard — flags fixture-shaped literals added to product source.

Layer 1 of the anti-hardcoding harness (founder ask 2026-09-13). It implements the
mechanically-checkable half of the six checks:

  check 1  proper nouns in the diff        -> rules DOC_ID, GSTIN, VAT, FIXTURE_ECHO
  check 2  where the knowledge lives       -> rule DOMAIN_LIST
  check 5  property vs literal assertions  -> rule RAW_FIGURE (the F30 §11.3 guard)

It is ADVISORY. Exit code 2 puts the findings in front of the model as feedback; the edit
has already landed and is not reverted. The judgement checks (3, 4, 6) cannot be automated
and live in the gap-work / done skills instead.

Suppress a single line with a trailing `hardcode-ok: <reason>` comment. A reason is required —
the marker alone does not silence it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Scope: product source only. Tests, fixtures, docs and migrations are allowed —
# indeed required — to carry concrete data.
# ---------------------------------------------------------------------------

SOURCE_SUFFIXES = (".py", ".ts", ".tsx")

EXCLUDED_PARTS = (
    "/tests/",
    "/test_",
    "/docs/",
    "/benchmarks/",
    "/scripts/",
    "/alembic/versions/",
    "/node_modules/",
    "/.venv/",
    "/__pycache__/",
    "/.next",
    "/showcase/",
    "/.claude/",
)

# Only product code is in scope; anything outside the apps tree is infra or tooling.
REQUIRED_PART = "/apps/"

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

# Document identifiers: RAJ-2009, PO-VPI-1041, INV-2026-0114.
DOC_ID_RE = re.compile(r"\b[A-Z]{2,5}-(?:[A-Z]{2,5}-)?\d{3,}\b")

# Standards and vocabulary that happen to share the shape above.
DOC_ID_ALLOW = {
    "SHA-256", "SHA-512", "SHA-1", "UTF-8", "UTF-16", "ISO-8601", "ISO-4217",
    "ISO-3166", "RFC-822", "RFC-2822", "RFC-3339", "AES-256", "RS-256", "HS-256",
    "GPT-4", "GPT-5", "EN-16931", "HTTP-401", "HTTP-403", "HTTP-404", "HTTP-500",
}

# A real GSTIN: 2 state digits, 5 PAN letters, 4 digits, entity letter, Z, checksum.
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]{2}\b")

# A concrete EU VAT registration number (the country prefix alone is fine — that is
# a code table; the prefix plus a specific registration is one company).
VAT_RE = re.compile(
    r"\b(?:ATU|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)\d{8,12}\b"
)

# Two or more string literals in a membership test — the shape of a synonym table,
# an ignorable-narration list, or a vendor allowlist. F30 §11.2 rejected all three.
DOMAIN_LIST_RE = re.compile(
    r"""\bin\s*[\(\[\{]\s*(?:["'][^"']{2,}["']\s*,\s*){1,}["'][^"']{2,}["']"""
)

# The same thing bound to a name rather than tested inline — the shape of the ignorable
# narration list, the item-synonym table and the vendor allowlist that F30 §11.2 rejected.
DOMAIN_COLLECTION_RE = re.compile(
    r"""=\s*(?:frozenset|set|tuple|list)?\s*[\(\[\{]\s*"""
    r"""(?:["'][^"']{2,}["']\s*,\s*){2,}["'][^"']{2,}["']"""
)

# An interpolated value next to money vocabulary with no formatting applied —
# "437190.0 of this order has not been invoiced yet". F30 §11.3's guard test.
MONEY_WORDS_RE = re.compile(
    r"(?:₹|€|£|\$|(?:amount|amounts|total|totals|value|balance|outstanding|invoiced"
    r"|owed|paid|pay|payable|due|bills|billed|charge|charges|charged|costs|cost|spend"
    r"|refund|credit|debit|shortfall|excess))",
    re.IGNORECASE,
)
FSTRING_RE = re.compile(r"""(?:f"[^"]*"|f'[^']*'|`[^`]*`)""")
# `money_text()` / `days_text()` / `count_text()` ARE the formatters this rule asks for,
# so a line that calls one is already compliant. Also accepts a `*_text` local that a
# formatter already produced.
FORMATTED_RE = re.compile(
    r"(?:money\s*\(|money_text\s*\(|days_text\s*\(|count_text\s*\(|\{[a-z_]*_text\}"
    r"|:,|:\.\d|toLocaleString|formatCurrency|\.toFixed)"
)
PLACEHOLDER_RE = re.compile(r"\$?\{[^{}]+\}")

SUPPRESS_RE = re.compile(r"hardcode-ok:\s*\S+")

COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''")


def in_scope(path: str) -> bool:
    p = path.replace("\\", "/")
    if not p.endswith(SOURCE_SUFFIXES):
        return False
    if REQUIRED_PART not in p:
        return False
    return not any(part in p for part in EXCLUDED_PARTS)


def is_tracked(repo: str, path: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return r.returncode == 0


def added_lines(repo: str, path: str) -> list[tuple[int, str]]:
    """Added lines in the working tree vs HEAD, as (line_no, text).

    A brand-new file has no diff against HEAD, so every one of its lines counts as added —
    otherwise the guard would be silent on exactly the files most likely to carry a fresh
    hardcoded shortcut.
    """
    if not is_tracked(repo, path):
        full = os.path.join(repo, path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                return list(enumerate(fh.read().splitlines(), start=1))
        except OSError:
            return []

    try:
        diff = subprocess.run(
            ["git", "diff", "--no-color", "-U0", "HEAD", "--", path],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    out: list[tuple[int, str]] = []
    line_no = 0
    for raw in diff.splitlines():
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            out.append((line_no, raw[1:]))
            line_no += 1
    return out


def strip_docstrings(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Drop docstring bodies.

    A worked example inside a docstring is documentation, not a hardcoded literal.
    Flagging it trains everyone to ignore this guard — which is worse than the miss.
    Added on 2026-09-13 after the guard's own first real edit tripped on "0 days"
    inside a docstring it was writing.
    """
    out: list[tuple[int, str]] = []
    in_doc = False
    delim = ""
    for line_no, text in lines:
        stripped = text.strip()
        if in_doc:
            if delim in text:
                in_doc = False
                delim = ""
            continue
        opened = False
        for d in ('"""', "'''"):
            if stripped.startswith(d):
                if not (len(stripped) > len(d) and stripped.endswith(d)):
                    in_doc = True
                    delim = d
                opened = True
                break
        if not opened:
            out.append((line_no, text))
    return out


def is_comment(text: str) -> bool:
    return text.strip().startswith(COMMENT_PREFIXES)


def fixture_echo(repo: str, literals: list[str]) -> set[str]:
    """Literals that also appear under tests/ or benchmarks/.

    The strongest single signal that a line was written to satisfy one case: the same
    string is both the fix and the fixture.
    """
    hits: set[str] = set()
    for lit in literals[:25]:
        try:
            r = subprocess.run(
                [
                    "git", "grep", "-l", "-F", lit, "--",
                    "*/tests/*", "*/benchmarks/*", "*_golden.json",
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            hits.add(lit)
    return hits


def scan(repo: str, path: str) -> list[str]:
    findings: list[str] = []
    candidates: list[str] = []
    seen_literals: dict[str, int] = {}

    for line_no, text in strip_docstrings(added_lines(repo, path)):
        if SUPPRESS_RE.search(text):
            continue

        comment = is_comment(text)

        def flag(rule: str, detail: str) -> None:
            findings.append(f"  {path}:{line_no}  [{rule}] {detail}")

        if not comment:
            for m in DOC_ID_RE.findall(text):
                if m not in DOC_ID_ALLOW:
                    flag("DOC_ID", f"document identifier {m!r} in product source")

            for m in GSTIN_RE.findall(text):
                flag("GSTIN", f"a specific GSTIN {m!r} — belongs in a fixture or a table")

            for m in VAT_RE.findall(text):
                flag("VAT", f"a specific VAT registration {m!r} — belongs in a fixture or a table")

            if DOMAIN_LIST_RE.search(text) or DOMAIN_COLLECTION_RE.search(text):
                flag(
                    "DOMAIN_LIST",
                    "a membership test over string literals. If these are domain facts "
                    "(vendor names, item synonyms, narration keywords, rule text) they belong "
                    "in a registry, table or threshold config, not in an if.",
                )

            for frag in FSTRING_RE.findall(text):
                if (
                    PLACEHOLDER_RE.search(frag)
                    and MONEY_WORDS_RE.search(frag)
                    and not FORMATTED_RE.search(text)
                ):
                    flag(
                        "RAW_FIGURE",
                        "an interpolated value next to money vocabulary with no formatter. "
                        "Route every number-to-text through money() (F30 §11.3).",
                    )
                    break

            # A party name or a document reference, not any two-word phrase. Shared
            # domain vocabulary ("0 days", "no invoice") legitimately appears in both a
            # fixture and the code; "Shree Packaging Pvt Ltd" does not.
            for lit in re.findall(r"""["']([^"'\n]{10,60})["']""", text):
                if any(c.isalpha() for c in lit) and lit.strip().count(" ") >= 2:
                    candidates.append(lit)
                    seen_literals.setdefault(lit, line_no)

    for lit in sorted(fixture_echo(repo, sorted(set(candidates)))):
        findings.append(
            f"  {path}:{seen_literals.get(lit, 0)}  [FIXTURE_ECHO] {lit!r} also appears under "
            f"tests/ or benchmarks/ — the fix and the fixture share a literal"
        )

    return findings


def main() -> int:
    # Windows consoles default to cp1252; the findings carry section signs and em-dashes,
    # and a UnicodeEncodeError here would take the whole guard down silently.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool = payload.get("tool_name", "")
    if tool not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return 0

    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path or not in_scope(path):
        return 0

    repo = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    try:
        rel = os.path.relpath(path, repo).replace("\\", "/")
    except ValueError:
        rel = path.replace("\\", "/")

    findings = scan(repo, rel)
    if not findings:
        return 0

    print(
        "Anti-hardcoding guard — %d signal(s) in this edit:\n\n%s\n\n"
        "Apply the founder's test (Feature 30 §11.2) to each line before moving on:\n"
        "  Would this line need editing when a new vendor, language, item, bank or\n"
        "  document type arrives? If yes, it is the wrong fix.\n\n"
        "This is advisory, not a block. Either move the data into a registry/table/threshold,\n"
        "or keep the line and append `hardcode-ok: <reason>` saying why it is genuinely static."
        % (len(findings), "\n".join(findings)),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
