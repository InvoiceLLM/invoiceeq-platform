"""One-off, local-only: pre-generate and commit `LARGE`/`SMALL`'s PDFs.

Run this after changing anything about `LARGE`/`SMALL` in `large_invoice_fixture.py`
(line count, vendor, invoice number -- anything that feeds the cache-key hash),
then commit the new file(s) under `benchmarks/fixtures/large_invoice/`.

Needs the `reportlab` dev dependency (`uv sync`, no `--no-dev`) and the whole
repo checked out (`tests/e2e/pdf_builder.py`) -- i.e. a local/dev machine, never
a deployed container. This script itself is not imported by anything at
runtime; it exists purely so the committed PDFs are reproducible instead of a
one-off nobody can regenerate.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

from benchmarks.large_invoice_fixture import LARGE, SMALL  # noqa: E402


def main() -> None:
    for spec in (SMALL, LARGE):
        path = spec.pdf_path()
        print(f"{spec.key:6s} {spec.invoice_number}: {path}")


if __name__ == "__main__":
    main()
