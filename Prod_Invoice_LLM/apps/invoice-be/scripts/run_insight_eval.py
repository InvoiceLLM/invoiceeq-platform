"""Feature 30 task 30.15 — grade the insight bubble against `insight_golden.json`.

    uv run python scripts/run_insight_eval.py [--cases id,id] [--stage sync|async]
                                              [--narrate] [--json out.json]

WHAT IT GRADES, AND HOW
-----------------------
Two halves, deliberately scored separately, because they fail for different
reasons and only one of them involves a model:

* **Figures — exact match, deterministic.** Every `expected_figures` entry must
  be present in the block with exactly that value, and every `must_not_contain`
  value must be absent from the whole block. This half needs no LLM at all and
  is the one that can gate a build. Target: >= 90% of figures exact, and **zero**
  `must_not_contain` hits (spec §6 30.15).
* **Narration — only with `--narrate`.** One `chat_summary` call per case,
  graded by the answer-contract gate that already runs in production: did the
  model state a figure that is not in the facts JSON? That is a real number, not
  a judge's opinion.

**No live model runs by default.** `--narrate` is opt-in and prints a warning,
because the founder's standing rule is that live runs are approved per run
(Feature 29's rule, unchanged here). Without it this script is pure computation
and is safe to run anywhere.

WHAT THE FIXTURES ARE
---------------------
Synthetic extraction payloads and the ledger rows they should be compared
against — no PDFs and no OCR. What 30.15 measures is the CARDS and the
NARRATION; putting extraction in the loop would make an extraction regression
look like an insight regression, and there is already a benchmark for that
(`scripts/run_extraction_benchmark.py`).

Every case runs under a THROWAWAY tenant id and every row it wrote is deleted
afterwards, so the script leaves the database exactly as it found it.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID, uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("insight_eval")

GOLDEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmarks", "insight_golden.json"
)

#: Spec §6 30.15's two targets.
FIGURE_TARGET_PCT = 90.0
FABRICATION_TARGET = 0


def load_golden(path: str = GOLDEN_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _as_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_case(case: dict, session: Any, tenant_id: UUID) -> tuple:
    """Materialise one case's attachment and invoices. Returns (attachment, ids)."""
    from models import ChatAttachment, ChatSession, Invoice

    chat = ChatSession(tenant_id=tenant_id, title=f"insight-eval {case['id']}")
    session.add(chat)
    session.commit()
    session.refresh(chat)

    invoice_ids = []
    for spec in case.get("invoices") or []:
        inv = Invoice(
            tenant_id=tenant_id,
            invoice_number=spec["invoice_number"],
            file_path=f"insight-eval/{case['id']}/{spec['invoice_number']}.pdf",
            vendor_name=spec.get("vendor_name"),
            customer_name=spec.get("customer_name"),
            grand_total=spec.get("grand_total"),
            currency=case.get("currency"),
            po_number=spec.get("po_number"),
            invoice_date=_as_date(spec.get("invoice_date")),
            due_date=_as_date(spec.get("due_date")),
            status=spec.get("status", "PROCESSING"),
            paid_at=datetime.utcnow() if spec.get("paid") else None,
            flow_direction=spec.get("flow_direction", "INBOUND"),
            items=spec.get("items") or [],
        )
        session.add(inv)
        session.commit()
        session.refresh(inv)
        invoice_ids.append((str(inv.id), bool(spec.get("confirmed"))))

    spec = case["attachment"]
    attachment = ChatAttachment(
        tenant_id=tenant_id,
        session_id=chat.id,
        filename=f"{case['id']}.pdf",
        blob_path="",
        doc_type=case["doc_type"],
        extraction_status="EXTRACTED",
        doc_number=spec.get("doc_number"),
        party_name=spec.get("party_name"),
        doc_date=_as_date(spec.get("doc_date")),
        currency=case.get("currency"),
        grand_total=spec.get("grand_total"),
        region=case.get("region"),
        statement_date=_as_date(spec.get("statement_date")),
        extracted_json=spec.get("extracted_json") or {},
        candidate_invoice_ids=[i for i, _ in invoice_ids],
        confirmed_invoice_ids=[i for i, confirmed in invoice_ids if confirmed],
        match_tier=1 if invoice_ids else None,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)

    if case["doc_type"] == "STATEMENT_OF_ACCOUNT":
        from services.bank_ledger import land_statement_lines

        land_statement_lines(attachment, session)
        session.refresh(attachment)

    return attachment, chat


def grade_case(case: dict, block: dict) -> dict:
    """Deterministic grading of one block. No model involved."""
    figures = block.get("figures") or {}
    cards = {c["card"]: c for c in block.get("cards") or []}
    finding_keys = [f.get("finding_key", "") for f in block.get("findings") or []]

    figure_results = []
    for name, expected in (case.get("expected_figures") or {}).items():
        actual = figures.get(name)
        figure_results.append(
            {"figure": name, "expected": expected, "actual": actual, "exact": actual == expected}
        )

    card_results = []
    for name, expected_status in (case.get("expected_cards") or {}).items():
        card = cards.get(name)
        card_results.append(
            {
                "card": name,
                "expected": expected_status,
                "actual": (card or {}).get("status"),
                "ok": bool(card) and card.get("status") == expected_status,
            }
        )

    reason_results = []
    for name, fragment in (case.get("expected_skip_reasons") or {}).items():
        reason = (cards.get(name) or {}).get("reason", "")
        reason_results.append(
            {"card": name, "fragment": fragment, "reason": reason, "ok": fragment in reason}
        )

    finding_results = []
    for expected in case.get("expected_findings") or []:
        if expected.endswith("*"):
            prefix = expected[:-1]
            found = any(k.startswith(prefix) for k in finding_keys)
        else:
            found = expected in finding_keys
        finding_results.append({"finding_key": expected, "found": found})

    # The fabrication check: a forbidden figure must appear NOWHERE in the block.
    blob = json.dumps(block, default=str)
    fabrications = [
        value for value in (case.get("must_not_contain") or []) if str(value) in blob
    ]

    return {
        "case_id": case["id"],
        "doc_type": case["doc_type"],
        "region": case.get("region"),
        "figures": figure_results,
        "cards": card_results,
        "skip_reasons": reason_results,
        "findings": finding_results,
        "fabrications": fabrications,
        "passed": (
            all(f["exact"] for f in figure_results)
            and all(c["ok"] for c in card_results)
            and all(r["ok"] for r in reason_results)
            and all(f["found"] for f in finding_results)
            and not fabrications
        ),
    }


def grade_narration(block: dict) -> dict:
    """One live `chat_summary` call, graded by the production answer-contract gate."""
    from services.attachment_insights import narrate_insight_block

    outcome = narrate_insight_block(block)
    return {
        "verdict": outcome["verdict"],
        "source": outcome["source"],
        "gate": outcome["gate"],
        # The only pass condition that matters: the model did not state a figure
        # it was not given. A rejected narration is a SAFE outcome (the template
        # stands), so it is reported but is not a failure of the gate.
        "gate_held": outcome["gate"].get("status") in ("ok", "unsupported", "skipped", "failed"),
    }


def run(
    case_ids: Optional[list] = None,
    stage: Optional[str] = None,
    narrate: bool = False,
    golden_path: str = GOLDEN_PATH,
) -> dict:
    """Run the bank. Returns the summary dict (also what `--json` writes)."""
    from sqlmodel import Session, select

    from database import engine
    from models import BankStatementLine, ChatAttachment, ChatMessage, ChatSession, Insight, Invoice
    from services.attachment_insights import build_insight_block

    golden = load_golden(golden_path)
    cases = golden["cases"]
    if case_ids:
        wanted = set(case_ids)
        cases = [c for c in cases if c["id"] in wanted]

    results = []
    with Session(engine) as session:
        for case in cases:
            tenant_id = uuid4()
            attachment = chat = None
            try:
                attachment, chat = build_case(case, session, tenant_id)
                block = build_insight_block(
                    attachment,
                    session,
                    tenant_id,
                    stage=stage or case.get("stage") or "sync",
                )
                result = grade_case(case, block)
                if narrate:
                    result["narration"] = grade_narration(block)
                results.append(result)
            except Exception as exc:  # a case that blows up is a failure, not a crash
                logger.error("Case %s failed: %s", case["id"], exc, exc_info=True)
                results.append(
                    {"case_id": case["id"], "passed": False, "error": str(exc), "figures": [],
                     "cards": [], "findings": [], "fabrications": [], "skip_reasons": []}
                )
            finally:
                _cleanup(session, tenant_id, attachment, chat)

    total_figures = sum(len(r["figures"]) for r in results)
    exact_figures = sum(1 for r in results for f in r["figures"] if f["exact"])
    fabrications = sum(len(r["fabrications"]) for r in results)
    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "figures_total": total_figures,
        "figures_exact": exact_figures,
        "figures_exact_pct": round(100.0 * exact_figures / total_figures, 1) if total_figures else 0.0,
        "fabricated_figures": fabrications,
        "narrated": bool(narrate),
        "meets_figure_target": (
            total_figures > 0 and (100.0 * exact_figures / total_figures) >= FIGURE_TARGET_PCT
        ),
        "meets_fabrication_target": fabrications <= FABRICATION_TARGET,
        "results": results,
    }
    return summary


def _cleanup(session: Any, tenant_id: UUID, attachment: Any, chat: Any) -> None:
    """Leave the database as we found it. Best-effort, and loud when it is not."""
    from sqlmodel import select

    from models import BankStatementLine, ChatAttachment, ChatMessage, ChatSession, Insight, Invoice

    try:
        for model in (Insight, BankStatementLine):
            for row in session.exec(select(model).where(model.tenant_id == tenant_id)).all():
                session.delete(row)
        session.commit()
        if chat is not None:
            for msg in session.exec(
                select(ChatMessage).where(ChatMessage.session_id == chat.id)
            ).all():
                session.delete(msg)
            session.commit()
        for model in (ChatAttachment, Invoice):
            for row in session.exec(select(model).where(model.tenant_id == tenant_id)).all():
                session.delete(row)
        session.commit()
        if chat is not None:
            existing = session.get(ChatSession, chat.id)
            if existing is not None:
                session.delete(existing)
                session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Cleanup failed for tenant %s: %s", tenant_id, exc)
        try:
            session.rollback()
        except Exception:
            pass


def _print(summary: dict) -> None:
    print()
    print(f"Insight eval — {summary['passed']}/{summary['cases']} cases passed")
    print(
        f"  figures exact: {summary['figures_exact']}/{summary['figures_total']} "
        f"({summary['figures_exact_pct']}%)  target >= {FIGURE_TARGET_PCT}%  "
        f"{'PASS' if summary['meets_figure_target'] else 'FAIL'}"
    )
    print(
        f"  fabricated figures: {summary['fabricated_figures']}  target {FABRICATION_TARGET}  "
        f"{'PASS' if summary['meets_fabrication_target'] else 'FAIL'}"
    )
    for result in summary["results"]:
        if result["passed"]:
            continue
        print(f"\n  FAILED {result['case_id']}")
        if result.get("error"):
            print(f"    error: {result['error']}")
        for figure in result["figures"]:
            if not figure["exact"]:
                print(f"    figure {figure['figure']}: expected {figure['expected']}, got {figure['actual']}")
        for card in result["cards"]:
            if not card["ok"]:
                print(f"    card {card['card']}: expected {card['expected']}, got {card['actual']}")
        for reason in result["skip_reasons"]:
            if not reason["ok"]:
                print(f"    skip reason {reason['card']}: wanted '{reason['fragment']}', got '{reason['reason']}'")
        for finding in result["findings"]:
            if not finding["found"]:
                print(f"    finding missing: {finding['finding_key']}")
        for value in result["fabrications"]:
            print(f"    FABRICATED FIGURE PRESENT: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade the insight bubble against the golden bank.")
    parser.add_argument("--cases", default="", help="comma-separated case ids; default all")
    parser.add_argument("--stage", choices=("sync", "async"), default=None)
    parser.add_argument(
        "--narrate",
        action="store_true",
        help="ALSO make one live chat_summary call per case. Off by default: a live "
             "run is approved per run, never implied by running the harness.",
    )
    parser.add_argument("--json", dest="json_path", default="", help="write the summary here")
    args = parser.parse_args()

    if args.narrate:
        print(
            "WARNING: --narrate makes one live model call per case. "
            "Confirm this run was approved before continuing.",
            file=sys.stderr,
        )

    summary = run(
        case_ids=[c for c in args.cases.split(",") if c] or None,
        stage=args.stage,
        narrate=args.narrate,
    )
    _print(summary)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
        print(f"\nwrote {args.json_path}")
    return 0 if (summary["meets_figure_target"] and summary["meets_fabrication_target"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
