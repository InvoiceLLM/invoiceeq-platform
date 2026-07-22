"""Daily regional accuracy benchmark harness.

Generates a fresh N-invoice-per-region batch (see generator.py), uploads each
PDF to a running invoice-be instance, polls until extraction finishes,
compares the result against known ground truth, runs a small RAG-chat
question sample against the batch, then deletes every invoice it created.
Produces a root-cause-grouped markdown + JSON report.

Usage:
    uv run python -m tests.benchmark.run_benchmark \
        --base-url http://localhost:8000/api/v1 \
        --regions US,INDIA,UK --count 10 --day-seed 1

Not run in CI - this hits real Azure OpenAI/Document Intelligence and is
meant to be run manually against a reachable invoice-be instance (see the
approved plan for the temporary-external-ingress procedure against dev).
"""
import argparse
import concurrent.futures
import json
import sys
import time
from datetime import datetime, date
from pathlib import Path

import httpx

from tests.benchmark.catalog import REGIONS
from tests.benchmark.generator import generate_daily_batch, GeneratedInvoice
from tests.benchmark.chat_questions import build_daily_chat_questions, grade_answer
from tests.e2e.pdf_builder import build_invoice_pdf
from tests.sync_processing import process_invoice_sync

POLL_INTERVAL_S = 3
POLL_TIMEOUT_S = 180
AMOUNT_ABS_TOLERANCE = 0.05
AMOUNT_REL_TOLERANCE = 0.005  # 0.5%

# Extraction is I/O-bound (Azure OpenAI + Doc Intelligence network calls), so
# threads parallelize it despite the GIL. Capped rather than unbounded to
# avoid tripping 429 throttling on those deployments - the pipeline has no
# retry/backoff for that today.
MAX_WORKERS = 5

# Written after every Nth completed extraction (overwriting the same report
# files main() would write at the end) so a hung/killed run - like the one
# that lost 28 finished invoices with nothing on disk to show for it -
# leaves a recoverable partial report instead of nothing.
CHECKPOINT_EVERY = 5

REPORT_DIR = Path(__file__).parent / "reports"
PDF_SCRATCH_DIR = Path(__file__).parent / "_scratch"


def _amounts_close(actual, expected) -> bool:
    if actual is None or expected is None:
        return actual == expected
    return abs(actual - expected) <= max(AMOUNT_ABS_TOLERANCE, AMOUNT_REL_TOLERANCE * abs(expected))


def _render_pdf(gen: GeneratedInvoice, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{gen.name}.pdf"
    build_invoice_pdf(str(path), **gen.pdf_kwargs)
    return path


def _upload(client: httpx.Client, base_url: str, pdf_path: Path) -> str:
    with open(pdf_path, "rb") as f:
        resp = client.post(
            f"{base_url}/invoices/upload",
            files={"files": (pdf_path.name, f, "application/pdf")},
            timeout=60,
        )
    resp.raise_for_status()
    body = resp.json()
    job_ids = body["job_ids"]
    if not job_ids:
        raise RuntimeError(f"Upload of {pdf_path.name} produced no job_ids (likely a duplicate-hash skip)")
    return job_ids[0], body["batch_id"]


def _poll(client: httpx.Client, base_url: str, invoice_id: str) -> dict:
    """Processing already ran synchronously (see sync_processing.process_invoice_sync)
    by the time this is called, so this just fetches the persisted result — the
    retry loop only covers the tiny DB-commit-visibility window, not real processing time."""
    deadline = time.time() + POLL_TIMEOUT_S
    last = None
    while time.time() < deadline:
        resp = client.get(f"{base_url}/invoices/{invoice_id}", timeout=30)
        resp.raise_for_status()
        last = resp.json()
        if last.get("status") in ("COMPLETED", "AUDIT_REQUIRED", "FAILED", "DUPLICATE"):
            return last
        time.sleep(1)
    return last or {"status": "TIMEOUT"}


# Multiple independent checks can legitimately catch the same underlying flaw -
# e.g. a bad line-item amount can be caught by the subtotal-sum check
# (line_items_mismatch), the per-line calc check (line_item_calculation_mismatch),
# or the Gap 36 OCR-faithfulness check (line_item_not_verified_in_source).
# Grading on an exact alert-type match produced false failures where the
# invoice was correctly flagged AUDIT_REQUIRED but by a *different*, equally
# valid check than the one the generator's ground truth predicted. Group
# alert types by what they're actually detecting and accept any type in the
# same family as a match.
_ALERT_TYPE_FAMILIES = [
    {"tax_mismatch", "total_not_verified_in_source"},
    {"line_items_mismatch", "line_item_calculation_mismatch", "line_item_not_verified_in_source"},
]


def _alert_type_matches(expected: str, actual_types: list[str]) -> bool:
    if expected in actual_types:
        return True
    family = next((f for f in _ALERT_TYPE_FAMILIES if expected in f), None)
    return bool(family) and any(t in family for t in actual_types)


def _compare(gen: GeneratedInvoice, actual: dict) -> dict:
    """Returns {"pass": bool, "root_cause": str|None, "detail": str}."""
    gt = gen.ground_truth
    expected_status = gt.get("expected_status")
    actual_status = actual.get("status")

    if actual_status == "TIMEOUT":
        return {"pass": False, "root_cause": "processing_timeout", "detail": f"Never left PROCESSING within {POLL_TIMEOUT_S}s"}

    if actual_status == "FAILED":
        return {"pass": False, "root_cause": "extraction_failed", "detail": str(actual.get("sa_alerts"))}

    if actual_status != expected_status:
        return {
            "pass": False,
            "root_cause": "status_misclassification",
            "detail": f"expected {expected_status}, got {actual_status}; alerts={actual.get('sa_alerts')}",
        }

    if expected_status == "AUDIT_REQUIRED":
        expected_alert = gt.get("expected_alert_type")
        alert_types = [a.get("type") for a in (actual.get("sa_alerts") or [])]
        if expected_alert and not _alert_type_matches(expected_alert, alert_types):
            return {"pass": False, "root_cause": "wrong_alert_type", "detail": f"expected alert '{expected_alert}', got {alert_types}"}
        return {"pass": True, "root_cause": None, "detail": "audit-required correctly flagged"}

    # COMPLETED path: check numeric fields
    if not _amounts_close(actual.get("grand_total"), gt.get("expected_grand_total")):
        return {"pass": False, "root_cause": "amount_mismatch_total", "detail": f"grand_total expected {gt.get('expected_grand_total')}, got {actual.get('grand_total')}"}

    if not _amounts_close(actual.get("tax_amount"), gt.get("expected_tax_amount")):
        return {"pass": False, "root_cause": "amount_mismatch_tax", "detail": f"tax_amount expected {gt.get('expected_tax_amount')}, got {actual.get('tax_amount')}"}

    if "expected_po_number" in gt and gt["expected_po_number"] is None and actual.get("po_number"):
        return {"pass": False, "root_cause": "hallucinated_optional_field", "detail": f"po_number should be null, got {actual.get('po_number')}"}

    if "expected_due_date" in gt and gt["expected_due_date"] is None and actual.get("due_date"):
        return {"pass": False, "root_cause": "hallucinated_optional_field", "detail": f"due_date should be null, got {actual.get('due_date')}"}

    return {"pass": True, "root_cause": None, "detail": "ok"}


def _run_chat_pass(client: httpx.Client, base_url: str, batches_by_region: dict) -> list[dict]:
    questions = build_daily_chat_questions(batches_by_region)
    if not questions:
        return []

    resp = client.post(f"{base_url}/chat/sessions", json={"title": "Benchmark RAG QA"}, timeout=30)
    resp.raise_for_status()
    session_id = resp.json()["id"]

    results = []
    for q in questions:
        try:
            resp = client.post(
                f"{base_url}/chat/sessions/{session_id}/message",
                json={"content": q.question},
                timeout=90,
            )
            resp.raise_for_status()
            answer = resp.json().get("content", "")
        except Exception as e:
            answer = f"<error: {e}>"

        verdict = grade_answer(q, answer)
        results.append({
            "region": q.region,
            "invoice_number": q.invoice_number,
            "kind": q.kind,
            "question": q.question,
            "expected": q.expected,
            "answer": answer,
            "verdict": verdict,
        })

    # Task 6.11 regression: re-ask the first question verbatim (new session, so it
    # can't be reading from chat_history) and confirm the answer is byte-identical —
    # proves the Redis cache actually short-circuits re-computation rather than
    # just being written and never read.
    if questions:
        first_q = questions[0]
        try:
            resp = client.post(f"{base_url}/chat/sessions", json={"title": "Benchmark RAG QA (cache check)"}, timeout=30)
            resp.raise_for_status()
            cache_session_id = resp.json()["id"]
            resp = client.post(
                f"{base_url}/chat/sessions/{cache_session_id}/message",
                json={"content": first_q.question},
                timeout=90,
            )
            resp.raise_for_status()
            repeat_answer = resp.json().get("content", "")
            original_answer = results[0]["answer"]
            cache_verdict = "pass" if repeat_answer == original_answer else "fail"
        except Exception as e:
            repeat_answer = f"<error: {e}>"
            cache_verdict = "fail"

        results.append({
            "region": first_q.region,
            "invoice_number": first_q.invoice_number,
            "kind": "cache_hit_check",
            "question": first_q.question,
            "expected": "identical answer to the first ask (Task 6.11 Redis cache)",
            "answer": repeat_answer,
            "verdict": cache_verdict,
        })

    return results


def _cleanup_preexisting_invoices(client: httpx.Client, base_url: str) -> int:
    """Defensive pre-run cleanup: the mock tenant's invoice table can carry leftover
    rows from unrelated ad-hoc test/sanity runs (this harness's own `finally` block
    only cleans up invoices *it* created). Aggregate questions like audit_count
    compute expected values from only this run's ground truth, so stale rows from
    other runs silently inflate the live count and produce a false failure. Deletes
    everything for the mock tenant before generating this run's batch."""
    deleted = 0
    while True:
        resp = client.get(f"{base_url}/invoices", params={"limit": 100}, timeout=30)
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break
        for item in items:
            try:
                client.delete(f"{base_url}/invoices/{item['id']}", timeout=30)
                deleted += 1
            except Exception:
                pass
    return deleted


def _process_one(client: httpx.Client, base_url: str, scratch: Path, region: str, gen: GeneratedInvoice) -> dict:
    """One invoice end-to-end: render, upload, extract, poll, grade. Never
    raises - failures at any stage become a failed result dict, since this
    runs inside a worker thread where an uncaught exception would just be
    silently swallowed by the executor until .result() is called."""
    pdf_path = _render_pdf(gen, scratch)
    try:
        invoice_id, batch_id = _upload(client, base_url, pdf_path)
    except Exception as e:
        return {"region": region, "name": gen.name, "pass": False, "root_cause": "upload_failed", "detail": str(e)}

    try:
        process_invoice_sync(invoice_id, batch_id)
    except Exception as e:
        return {
            "region": region, "name": gen.name, "invoice_id": invoice_id,
            "pass": False, "root_cause": "extraction_failed", "detail": str(e),
        }

    actual = _poll(client, base_url, invoice_id)
    verdict = _compare(gen, actual)
    return {
        "region": region, "name": gen.name, "invoice_id": invoice_id,
        "invoice_number": gen.ground_truth.get("invoice_number"),
        "complexity": "high" if len(gen.pdf_kwargs["rows"]) >= 7 else "medium",
        **verdict,
    }


def _write_checkpoint(day_seed: int, regions: list[str], count: int, extraction_results: list[dict], total: int) -> None:
    report = {
        "day_seed": day_seed,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "regions": regions,
        "count_per_region": count,
        "extraction_results": extraction_results,
        "chat_results": [],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"day{day_seed}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    header = f"**IN PROGRESS - {len(extraction_results)}/{total} extractions done, RAG chat pass not started yet**\n\n"
    (REPORT_DIR / f"day{day_seed}.md").write_text(header + _summarize(report), encoding="utf-8")
    print(f"Checkpoint written: {len(extraction_results)}/{total} extractions.")


def run(regions: list[str], count: int, day_seed: int, base_url: str) -> dict:
    scratch = PDF_SCRATCH_DIR / f"day{day_seed}"
    batches_by_region = {r: generate_daily_batch(r, day_seed, count) for r in regions}
    tasks = [(region, gen) for region, batch in batches_by_region.items() for gen in batch]
    total = len(tasks)

    extraction_results = []
    created_invoice_ids = []

    with httpx.Client() as client:
        try:
            cleaned = _cleanup_preexisting_invoices(client, base_url)
            if cleaned:
                print(f"Cleaned up {cleaned} pre-existing invoice(s) from the mock tenant before starting.")

            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(_process_one, client, base_url, scratch, region, gen): (region, gen)
                    for region, gen in tasks
                }
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result.get("invoice_id"):
                        created_invoice_ids.append(result["invoice_id"])
                    extraction_results.append(result)
                    if len(extraction_results) % CHECKPOINT_EVERY == 0:
                        _write_checkpoint(day_seed, regions, count, extraction_results, total)

            chat_results = _run_chat_pass(client, base_url, batches_by_region)

        finally:
            for invoice_id in created_invoice_ids:
                try:
                    client.delete(f"{base_url}/invoices/{invoice_id}", timeout=30)
                except Exception:
                    pass

    return {
        "day_seed": day_seed,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "regions": regions,
        "count_per_region": count,
        "extraction_results": extraction_results,
        "chat_results": chat_results,
    }


def _summarize(report: dict) -> str:
    ext = report["extraction_results"]
    total = len(ext)
    passed = sum(1 for r in ext if r["pass"])

    by_cause = {}
    for r in ext:
        if not r["pass"]:
            cause = r.get("root_cause") or "unknown"
            by_cause.setdefault(cause, []).append(r)

    lines = [
        f"# Benchmark Report - Day Seed {report['day_seed']} ({report['run_at']})",
        "",
        f"**Extraction accuracy: {passed}/{total} ({passed/total*100:.1f}%)**",
        "",
        "## Per-region breakdown",
    ]
    for region in report["regions"]:
        region_results = [r for r in ext if r["region"] == region]
        region_pass = sum(1 for r in region_results if r["pass"])
        lines.append(f"- {region}: {region_pass}/{len(region_results)} ({region_pass/len(region_results)*100:.1f}%)")

    lines += ["", "## Failures grouped by root cause"]
    if not by_cause:
        lines.append("None.")
    for cause, items in sorted(by_cause.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"\n### {cause} ({len(items)})")
        for r in items:
            lines.append(f"- [{r['region']}] {r['name']} (`{r.get('invoice_id', '?')}`): {r['detail']}")

    chat = report["chat_results"]
    if chat:
        chat_pass = sum(1 for c in chat if c["verdict"] == "pass")
        lines += ["", f"## RAG chat sample: {chat_pass}/{len(chat)} passed", ""]
        for c in chat:
            lines.append(f"- [{c['region']}/{c['kind']}] **{c['verdict'].upper()}** — Q: \"{c['question']}\" | expected={c['expected']} | A: \"{c['answer'][:200]}\"")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--regions", default="US,INDIA,UK")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--day-seed", type=int, default=int(date.today().strftime("%Y%m%d")))
    args = parser.parse_args()

    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
    for r in regions:
        if r not in REGIONS:
            print(f"Unknown region '{r}', must be one of {list(REGIONS)}", file=sys.stderr)
            sys.exit(1)

    report = run(regions, args.count, args.day_seed, args.base_url.rstrip("/"))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"day{args.day_seed}.json"
    md_path = REPORT_DIR / f"day{args.day_seed}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    summary = _summarize(report)
    md_path.write_text(summary, encoding="utf-8")

    print(summary)
    print(f"\nFull report: {json_path}")


if __name__ == "__main__":
    main()
