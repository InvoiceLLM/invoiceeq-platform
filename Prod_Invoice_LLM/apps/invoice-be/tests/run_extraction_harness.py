"""
InvoiceEQ_Ground_Truth.xlsx extraction harness (Step 2 of the ground-truth test plan).

Uploads all 27 test PDFs through the real /invoices/upload and /outbound-invoices/upload
endpoints (real auth path -- mock bearer tokens, ALLOW_MOCK_AUTH=true, resolved by the
real dependencies.py the same way a real token would be), then runs the SAME extraction
code the queue worker would run, synchronously in-process (no local queue worker running
in this dev setup -- same reason tests/sync_processing.py exists for tests/e2e).

Writes a COPY of the ground truth workbook: InvoiceEQ_Actual_Results.xlsx, with new
"Actual ..." columns on the Invoices sheet plus an "Errors" sheet. Never edits
InvoiceEQ_Ground_Truth.xlsx.

Gap 466 (2026-09-05) -- this harness is now the model-swap GATE, not just a recorder.
It also scores every row (field-level match on Tax, Total, Status, Alert Type), captures
LLM token usage from telemetry's `llm_agent_call` events when extraction runs in this
process, and prices it with `utils/model_registry`. Output per run:

  * a "Scores" sheet in InvoiceEQ_Actual_Results.xlsx (per-field verdicts per invoice),
  * tests/InvoiceEQ_Scores_<label>.json -- invoice/field accuracy %, per-field accuracy,
    p50/p95 latency, tokens, USD cost, and the registry snapshot that was in force,
  * exit code 1 when field accuracy is below --min-accuracy (default 0: report only).

Run the baseline on the current primary first, then each candidate with the backend
started under that candidate's env:

  uv run --with openpyxl python tests/run_extraction_harness.py --label gpt-5-mini
  uv run --with openpyxl python tests/run_extraction_harness.py --label luna --min-accuracy 90

Known, disclosed limitation: "Actual Subtotal" is always left blank. The extraction
agent does extract a subtotal (agents/extraction_agent.py's schema) and uses it for the
line-item math-verification alert, but it is never written onto the Invoice row -- there
is no `subtotal` column on the model. Not retrievable from any API without an application
code change, which is out of scope for this harness.

Mock-auth quirk this script works around (test orchestration only, no app code touched):
dependencies.py's `test_<uuid>` mock token format embeds a tenant_id in the token string,
but the mock identity's user_id (MOCK_USER_ID = "user_test_default") is a fixed constant,
not derived from the token. Once a User row for that id exists, its *stored* tenant_id
wins on every later request, regardless of what a later token embeds. So this script
processes one tenant's whole batch at a time and re-points that single shared mock user's
tenant_id in the DB before starting each tenant's batch.
"""
import json
import os
import sys
import time
import traceback
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
import statistics
from datetime import datetime, timezone

import httpx
import openpyxl
from sqlmodel import Session, select

from database import engine
from models import Invoice, Tenant, User
from utils.model_registry import cost_usd, registry_snapshot, resolve_model

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
GROUND_TRUTH_PATH = os.path.join(TESTS_DIR, "InvoiceEQ_Ground_Truth.xlsx")
RESULTS_PATH = os.path.join(TESTS_DIR, "InvoiceEQ_Actual_Results.xlsx")
TENANTS_PATH = os.path.join(TESTS_DIR, "test_tenants_local.json")
BASE_URL = "http://localhost:8000/api/v1"
MOCK_USER_ID = "user_test_default"  # dependencies.py::MOCK_USER_ID

NEW_COLUMNS = [
    "Actual Subtotal",
    "Actual Tax",
    "Actual Total",
    "Actual Status",
    "Actual Alert Type",
    "Actual Notes/Errors",
]


def load_tenants():
    with open(TENANTS_PATH) as f:
        return json.load(f)


def sync_mock_user_tenant(tenant_id: str):
    """Point the single shared mock user row at `tenant_id`. Test-orchestration only --
    does not touch dependencies.py. If no row exists yet, does nothing; the next mock
    request creates one fresh and picks up the token's tenant_id correctly on its own."""
    with Session(engine) as s:
        user = s.exec(select(User).where(User.clerk_user_id == MOCK_USER_ID)).first()
        if user is not None:
            user.tenant_id = tenant_id
            s.add(user)
            s.commit()


def read_invoices_sheet():
    wb = openpyxl.load_workbook(GROUND_TRUTH_PATH, data_only=True)
    ws = wb["Invoices"]
    header = [c.value for c in ws[1]]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        rows.append(dict(zip(header, r)))
    return rows


def process_one(tenant_label: str, tenant_id: str, row: dict) -> dict:
    pdf_rel = row["PDF Filename"]
    pdf_path = os.path.join(TESTS_DIR, pdf_rel)
    direction = (row["Direction"] or "").strip().lower()
    headers = {"Authorization": f"Bearer test_{tenant_id}"}

    result = {c: None for c in NEW_COLUMNS}
    notes = []

    if not os.path.exists(pdf_path):
        result["Actual Status"] = "ERROR"
        result["Actual Notes/Errors"] = f"PDF not found on disk: {pdf_rel}"
        return result

    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        try:
            with open(pdf_path, "rb") as f:
                if direction == "inbound":
                    resp = client.post(
                        "/invoices/upload",
                        headers=headers,
                        files={"files": (os.path.basename(pdf_path), f, "application/pdf")},
                    )
                elif direction == "outbound":
                    resp = client.post(
                        "/outbound-invoices/upload",
                        headers=headers,
                        files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                    )
                else:
                    result["Actual Status"] = "ERROR"
                    result["Actual Notes/Errors"] = f"Unrecognised Direction value: {row['Direction']!r}"
                    return result
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            result["Actual Status"] = "ERROR"
            result["Actual Notes/Errors"] = f"Upload call failed: {e}"
            return result

        invoice_id = body["job_ids"][0] if direction == "inbound" else body["invoice_id"]

        # Real file_path/batch_id the upload endpoint actually stamped -- needed to run
        # the same handler the queue worker would run, since there is no local worker.
        with Session(engine) as s:
            db_inv = s.get(Invoice, invoice_id)
            if db_inv is None:
                result["Actual Status"] = "ERROR"
                result["Actual Notes/Errors"] = f"Upload returned invoice_id {invoice_id} but no such row exists."
                return result
            file_path = db_inv.file_path
            real_batch_id = str(db_inv.batch_id)

        try:
            if direction == "inbound":
                from queue_worker.handlers import handle_process_invoice
                handle_process_invoice(batch_id=real_batch_id, file_path=file_path, tenant_id=str(tenant_id))
            else:
                from queue_worker.outbound_handlers import handle_process_outbound_invoice
                handle_process_outbound_invoice(batch_id=real_batch_id, file_path=file_path, tenant_id=str(tenant_id))
        except Exception as e:
            # Handler already persists FAILED onto the row before re-raising (Gap 84) --
            # keep going and read that back below, don't treat this as a harness error.
            notes.append(f"Processing raised (status persisted as FAILED by the handler): {e}")

        # Read final state. Inbound has a real single-invoice GET; outbound does not
        # (only a list endpoint with no tax_amount/alerts) -- read the DB row directly
        # for outbound instead, disclosed here rather than silently improvised.
        if direction == "inbound":
            try:
                r2 = client.get(f"/invoices/{invoice_id}", headers=headers)
                r2.raise_for_status()
                data = r2.json()
                result["Actual Status"] = data.get("status")
                result["Actual Tax"] = data.get("tax_amount")
                result["Actual Total"] = data.get("grand_total")
                alerts = data.get("sa_alerts") or []
            except Exception as e:
                result["Actual Status"] = "ERROR"
                notes.append(f"Status read-back failed: {e}")
                alerts = []
        else:
            notes.append("Outbound tax_amount/alerts read directly from DB: no outbound API exposes them.")
            with Session(engine) as s:
                db_inv = s.get(Invoice, invoice_id)
                result["Actual Status"] = db_inv.status if db_inv else "ERROR"
                result["Actual Tax"] = db_inv.tax_amount if db_inv else None
                result["Actual Total"] = db_inv.grand_total if db_inv else None
                alerts = (db_inv.sa_alerts or []) if db_inv else []

        alert_types = sorted({a.get("type") for a in alerts if isinstance(a, dict) and a.get("type")})
        result["Actual Alert Type"] = ";".join(alert_types) if alert_types else ("None" if result["Actual Status"] not in (None, "ERROR") else None)

    # Gap 466 matrix: line items for precision/recall against the LineItems sheet.
    with Session(engine) as s:
        db_inv = s.get(Invoice, invoice_id)
        result["_items"] = list((db_inv.items or []) if db_inv else [])

    notes.append("Actual Subtotal not retrievable: extraction computes it but it is never persisted onto the Invoice row (see harness docstring).")
    result["Actual Notes/Errors"] = " | ".join(notes)
    return result


# ---------------------------------------------------------------------------
# Gap 466: scoring + in-process token capture
# ---------------------------------------------------------------------------
SCORED_FIELDS = (
    # (ground-truth column, actual column, comparator)
    ("Expected Tax/VAT/GST", "Actual Tax", "money"),
    ("Expected Total", "Actual Total", "money"),
    ("Expected Status", "Actual Status", "text"),
    ("Expected Alert Type", "Actual Alert Type", "alerts"),
)
MONEY_TOLERANCE = 0.011  # one cent either way -- printed vs stored float rounding


def _as_float(v):
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _alert_set(v) -> set:
    if v is None:
        return set()
    txt = str(v).strip()
    if not txt or txt.lower() in ("none", "-"):
        return set()
    return {a.strip() for a in txt.replace(",", ";").split(";") if a.strip()}


def field_matches(kind: str, expected, actual) -> bool:
    if kind == "money":
        e, a = _as_float(expected), _as_float(actual)
        if e is None and a is None:
            return True
        if e is None or a is None:
            return False
        return abs(e - a) <= MONEY_TOLERANCE
    if kind == "alerts":
        return _alert_set(expected) == _alert_set(actual)
    return str(expected or "").strip().upper() == str(actual or "").strip().upper()


def read_line_items_sheet() -> dict:
    """LineItems sheet -> {invoice_id: [ {qty, unit_rate, amount}, ... ]}. Printed amount is the
    reference (the extractor is told to transcribe, not recompute)."""
    wb = openpyxl.load_workbook(GROUND_TRUTH_PATH, data_only=True)
    if "LineItems" not in wb.sheetnames:
        return {}
    ws = wb["LineItems"]
    header = [c.value for c in ws[1]]
    out = defaultdict(list)
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        row = dict(zip(header, r))
        out[row["Invoice ID"]].append({
            "description": row.get("Description"),
            "qty": _as_float(row.get("Qty")),
            "unit_rate": _as_float(row.get("Unit Rate")),
            "amount": _as_float(row.get("Printed Amount (on PDF)")),
        })
    return dict(out)


def _line_match(exp: dict, act: dict) -> bool:
    """A ground-truth line matches an extracted item when every GT numeric that exists
    (qty, unit rate, printed amount) is within one cent of the extracted value."""
    pairs = (
        (exp.get("qty"), _as_float(act.get("quantity"))),
        (exp.get("unit_rate"), _as_float(act.get("unit_price"))),
        (exp.get("amount"), _as_float(act.get("amount"))),
    )
    checked = 0
    for e, a in pairs:
        if e is None:
            continue
        checked += 1
        if a is None or abs(e - a) > MONEY_TOLERANCE:
            return False
    return checked > 0


def score_line_items(expected: list, actual: list) -> dict:
    """Greedy one-to-one matching. Returns tp / predicted / expected counts."""
    remaining = list(actual or [])
    tp = 0
    for exp in expected or []:
        for i, act in enumerate(remaining):
            if isinstance(act, dict) and _line_match(exp, act):
                tp += 1
                remaining.pop(i)
                break
    return {"tp": tp, "predicted": len(actual or []), "expected": len(expected or [])}


def score_row(gt: dict, actual: dict) -> dict:
    """Per-field verdicts for one invoice. An ERROR row scores every field False."""
    errored = actual.get("Actual Status") in (None, "ERROR")
    verdicts = {}
    for gt_col, act_col, kind in SCORED_FIELDS:
        verdicts[act_col] = (not errored) and field_matches(kind, gt.get(gt_col), actual.get(act_col))
    verdicts["all_fields"] = all(verdicts[a] for _, a, _ in SCORED_FIELDS)
    return verdicts


class _LlmEventCapture(logging.Handler):
    """Collects `llm_agent_call` events emitted in this process.

    telemetry._emit_event logs them on `invoice_be_telemetry` /
    `invoice_worker_telemetry` with the attributes in `extra_fields`. When
    extraction runs in the backend's process instead, nothing is captured and
    the summary says so rather than reporting zero cost as a fact.
    """

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.events: list[dict] = []

    def emit(self, record):
        if record.getMessage() != "llm_agent_call":
            return
        attrs = getattr(record, "extra_fields", None) or {}
        self.events.append(dict(attrs))


def _install_capture() -> _LlmEventCapture:
    cap = _LlmEventCapture()
    for name in ("invoice_be_telemetry", "invoice_worker_telemetry"):
        lg = logging.getLogger(name)
        lg.addHandler(cap)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)
    return cap


def _pct(values: list, q: float):
    if not values:
        return None
    xs = sorted(values)
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 3)


def build_summary(label: str, results: dict, verdicts: dict, latencies: dict, events: list) -> dict:
    scored = list(verdicts.values())
    n = len(scored)
    per_field = {}
    for _, act_col, _ in SCORED_FIELDS:
        hits = sum(1 for v in scored if v[act_col])
        per_field[act_col] = {"correct": hits, "total": n, "accuracy_pct": round(100.0 * hits / n, 1) if n else None}
    all_hits = sum(1 for v in scored if v["all_fields"])
    field_total = n * len(SCORED_FIELDS)
    field_hits = sum(sum(1 for _, a, _ in SCORED_FIELDS if v[a]) for v in scored)
    lat = list(latencies.values())
    li_tp = sum(v.get("line_items", {}).get("tp", 0) for v in scored)
    li_pred = sum(v.get("line_items", {}).get("predicted", 0) for v in scored)
    li_exp = sum(v.get("line_items", {}).get("expected", 0) for v in scored)
    li_p = round(100.0 * li_tp / li_pred, 1) if li_pred else None
    li_r = round(100.0 * li_tp / li_exp, 1) if li_exp else None
    li_f1 = round(2 * li_p * li_r / (li_p + li_r), 1) if li_p and li_r else None
    tokens_in = sum(int(e.get("tokens_in") or 0) for e in events)
    tokens_out = sum(int(e.get("tokens_out") or 0) for e in events)
    primary = resolve_model("primary")
    cost = sum(cost_usd(e.get("model") or primary.deployment, e.get("tokens_in") or 0, e.get("tokens_out") or 0) for e in events)
    return {
        "label": label,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model_primary": primary.deployment,
        "api_version": primary.api_version,
        "registry": registry_snapshot(),
        "invoices": n,
        "errors": sum(1 for r in results.values() if r.get("Actual Status") in (None, "ERROR")),
        "invoice_accuracy_pct": round(100.0 * all_hits / n, 1) if n else None,
        "field_accuracy_pct": round(100.0 * field_hits / field_total, 1) if field_total else None,
        "per_field": per_field,
        "line_items": {"tp": li_tp, "predicted": li_pred, "expected": li_exp, "precision_pct": li_p, "recall_pct": li_r, "f1_pct": li_f1},
        "cost_per_invoice_usd": round(cost / n, 5) if (events and n) else None,
        "latency_s": {
            "p50": _pct(lat, 0.5),
            "p95": _pct(lat, 0.95),
            "max": _pct(lat, 1.0),
            "mean": round(statistics.mean(lat), 3) if lat else None,
        },
        "llm_calls": len(events),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "models_seen": sorted({str(e.get("model")) for e in events if e.get("model")}),
        "cost_usd": round(cost, 4) if events else None,
        "cost_note": None if events else (
            "no llm_agent_call events captured in this process (extraction ran in the backend); "
            "read tokens/cost from the AI Control Tower workbook for this run window"
        ),
    }


def write_scores_sheet(wb, gt_rows: list, verdicts: dict, latencies: dict):
    if "Scores" in wb.sheetnames:
        del wb["Scores"]
    ws = wb.create_sheet("Scores")
    ws.append(["ID"] + [a for _, a, _ in SCORED_FIELDS] + ["All fields", "Lines TP", "Lines predicted", "Lines expected", "Latency s"])
    for gt in gt_rows:
        v = verdicts.get(gt["ID"])
        if v is None:
            continue
        ws.append(
            [gt["ID"]]
            + ["PASS" if v[a] else "FAIL" for _, a, _ in SCORED_FIELDS]
            + ["PASS" if v["all_fields"] else "FAIL"]
            + [v.get("line_items", {}).get(k, 0) for k in ("tp", "predicted", "expected")]
            + [round(latencies.get(gt["ID"], 0.0), 2)]
        )


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="InvoiceEQ extraction harness + model-swap gate (Gap 466)")
    ap.add_argument("--label", default=None, help="name for this run's score file (default: primary deployment name)")
    ap.add_argument("--min-accuracy", type=float, default=0.0, help="exit 1 if field accuracy %% is below this (0 = report only)")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--deployment", default=None, help="Azure deployment to extract with, for this process only (Gap 466 matrix). Extraction runs in-process, so the backend at --base-url only handles the upload.")
    ap.add_argument("--ids", default=None, help="comma list of ground-truth IDs to run (smoke test); default all 27")
    ap.add_argument("--scores-out", default=None, help="write the summary JSON here instead of tests/InvoiceEQ_Scores_<label>.json")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    global BASE_URL
    BASE_URL = args.base_url
    if args.deployment:
        from config import get_settings
        _s = get_settings()
        _s.AZURE_OPENAI_DEPLOYMENT_NAME = args.deployment
        _s.AZURE_OPENAI_FAST_DEPLOYMENT_NAME = ""
        print(f"Deployment override for this process: {args.deployment} (api {_s.AZURE_OPENAI_API_VERSION})")
    label = args.label or resolve_model("primary").deployment
    capture = _install_capture()
    tenants = load_tenants()
    ground_truth_rows = read_invoices_sheet()

    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        ground_truth_rows = [r for r in ground_truth_rows if r["ID"] in wanted]
    by_tenant = defaultdict(list)
    for row in ground_truth_rows:
        by_tenant[row["Tenant"]].append(row)

    print(f"Loaded {len(ground_truth_rows)} ground-truth rows across {len(by_tenant)} tenants.")

    all_results = {}  # ID -> result dict
    errors = []  # list of {ID, PDF, Error}
    verdicts = {}  # ID -> per-field verdicts (Gap 466)
    latencies = {}  # ID -> seconds
    gt_by_id = {r["ID"]: r for r in ground_truth_rows}
    line_items_gt = read_line_items_sheet()

    for tenant_label, rows in by_tenant.items():
        tenant_id = tenants.get(tenant_label)
        if not tenant_id:
            for row in rows:
                errors.append({"ID": row["ID"], "PDF Filename": row["PDF Filename"],
                               "Error": f"No local tenant_id known for label {tenant_label!r}"})
            continue

        print(f"\n=== {tenant_label} ({tenant_id}) -- {len(rows)} invoices ===")
        sync_mock_user_tenant(tenant_id)

        for row in rows:
            inv_id = row["ID"]
            t0 = time.time()
            try:
                result = process_one(tenant_label, tenant_id, row)
            except Exception as e:
                result = {c: None for c in NEW_COLUMNS}
                result["Actual Status"] = "ERROR"
                result["Actual Notes/Errors"] = f"Harness-level exception: {e}"
                errors.append({"ID": inv_id, "PDF Filename": row["PDF Filename"],
                               "Error": f"{e}\n{traceback.format_exc()}"})
            elapsed = time.time() - t0
            all_results[inv_id] = result
            latencies[inv_id] = elapsed
            verdicts[inv_id] = score_row(gt_by_id[inv_id], result)
            verdicts[inv_id]["line_items"] = score_line_items(line_items_gt.get(inv_id, []), result.get("_items") or [])
            verdict_txt = "PASS" if verdicts[inv_id]["all_fields"] else "FAIL"
            print(f"  {inv_id}: {result['Actual Status']} ({elapsed:.1f}s) {verdict_txt}")
            if result["Actual Status"] in ("ERROR", None):
                errors.append({"ID": inv_id, "PDF Filename": row["PDF Filename"],
                               "Error": result.get("Actual Notes/Errors") or "Unknown -- status is None"})

    # --- Write InvoiceEQ_Actual_Results.xlsx: copy of the ground truth + new columns + Errors sheet ---
    wb = openpyxl.load_workbook(GROUND_TRUTH_PATH, data_only=False)
    ws = wb["Invoices"]
    header = [c.value for c in ws[1]]
    id_col_idx = header.index("ID") + 1

    start_col = ws.max_column + 1
    for i, col_name in enumerate(NEW_COLUMNS):
        ws.cell(row=1, column=start_col + i, value=col_name)

    for r in range(2, ws.max_row + 1):
        inv_id = ws.cell(row=r, column=id_col_idx).value
        if inv_id is None:
            continue
        result = all_results.get(inv_id)
        if result is None:
            continue
        for i, col_name in enumerate(NEW_COLUMNS):
            ws.cell(row=r, column=start_col + i, value=result[col_name])

    if "Errors" in wb.sheetnames:
        del wb["Errors"]
    err_ws = wb.create_sheet("Errors")
    err_ws.append(["ID", "PDF Filename", "Error"])
    for e in errors:
        err_ws.append([e["ID"], e["PDF Filename"], e["Error"]])

    write_scores_sheet(wb, ground_truth_rows, verdicts, latencies)
    wb.save(RESULTS_PATH)
    print(f"\nWrote {RESULTS_PATH}")
    print(f"Total: {len(all_results)} processed, {len(errors)} errors/anomalies logged in the Errors sheet.")

    summary = build_summary(label, all_results, verdicts, latencies, capture.events)
    safe_label = label.replace("/", "_").replace(":", "_")
    scores_path = args.scores_out or os.path.join(TESTS_DIR, f"InvoiceEQ_Scores_{safe_label}.json")
    os.makedirs(os.path.dirname(os.path.abspath(scores_path)), exist_ok=True)
    with open(scores_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Wrote {scores_path}")
    lat = summary["latency_s"]
    print(
        f"[{label}] invoice accuracy {summary['invoice_accuracy_pct']}% | "
        f"field accuracy {summary['field_accuracy_pct']}% | p50 {lat['p50']}s p95 {lat['p95']}s | "
        f"tokens {summary['tokens_in']}/{summary['tokens_out']} | cost {summary['cost_usd']} USD"
    )
    for col, stat in summary["per_field"].items():
        print(f"    {col:<18} {stat['correct']}/{stat['total']} ({stat['accuracy_pct']}%)")
    li = summary["line_items"]
    print(f"    line items         P {li['precision_pct']}% R {li['recall_pct']}% F1 {li['f1_pct']}% ({li['tp']}/{li['predicted']}/{li['expected']})")
    if args.min_accuracy and (summary["field_accuracy_pct"] or 0) < args.min_accuracy:
        print(f"GATE FAILED: field accuracy {summary['field_accuracy_pct']}% < {args.min_accuracy}%")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
