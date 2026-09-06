"""The 16-turn attachment-chat probe, as a versioned script — Feature 29 task 29.8.

    uv run --with reportlab python scripts/attach_chat_eval.py \
        --label gpt-5.6-luna --tenant <us-tenant-uuid> \
        --out docs/extraction_benchmark/runs/<run>/gpt-5.6-luna__attachchat.json \
        --flush-cache

WHY THIS EXISTS AS A FILE. The probe that produced
`runs/matrix-20260905T092330Z/*__attachchat.json` — the run that found Gaps 470,
472 and 473 and probe turns A4/A7/B3/B4/B5 failing identically on gpt-5.6-luna,
gpt-5-mini and gpt-5.6-terra — was an ad-hoc script in a session scratchpad. Its
JSON survived; the script did not. Every one of those gaps says "the 16-turn
probe re-run is still owed", and a re-run that cannot be reproduced turn-for-turn
is not evidence of anything. So the turn set, the documents, the grading regexes
and the confirm-card handling now live here, in the repo, versioned with the code
they measure.

WHAT IT MEASURES. Two chat sessions against a tenant that already has the
matching invoices ingested:

* **Session A** (5 documents, the per-session cap): a PO that matches cleanly, a
  PO plus its credit note, a quotation whose invoice differs on one line, a
  statement of account to reconcile — and two plain questions with no attachment
  at all, asked in the same session.
* **Session B** (3 documents): a delivery note, a remittance advice, a service
  contract carrying a tax rate — plus two more plain questions.

16 turns: 9 single-document, 3 two-document, 4 with no attachment. The plain
turns are not padding: they are the control that says a failure is about
attachments rather than about the tenant's data.

GRADING IS DETERMINISTIC (hard rule 3). Every turn carries `required` and
`forbidden` regexes and passes only when every `required` matches and no
`forbidden` one does. No model judges this probe — the judge (`run_agent_eval.py`)
scores the 36-turn golden set, where the answers are open prose; here the right
answer contains a specific invoice number and a specific figure, and a regex is
both cheaper and more honest about what was checked.

THE CONFIRM CARD IS A DESIGNED STEP, NOT A FAILURE. Feature 26's confirmation
gate (D4) refuses to compare an attachment against an invoice nobody has
confirmed. A turn that gets the card is answered the way the FE would answer it
— confirm the candidates, re-ask with `attachment_intent="compare"` — and the
turn is recorded with `confirm_step: true`. Counting the card as a failure would
score the safety gate as a defect.

WHAT A RE-RUN MUST CONTROL FOR, and does:

* **The answer cache.** `--flush-cache` deletes every `chat_answer_cache*` key
  before the first turn. Without it a second model is scored on the first model's
  answers, which is exactly the trap Feature 29 task 29.12 re-keys the cache to
  close.
* **Fresh sessions.** Session titles carry the label and a UTC stamp, so no run
  inherits another's conversation history (`recent_turn_digest()` is real
  context, and turn B2 reads differently if A7 is in the same thread).
* **Which model actually answered.** The deployment names in force are read from
  `config.get_settings()` at start-up and written into the JSON. A run labelled
  `gpt-5.6-terra` that was really served by Luna is worse than no run, and the
  label alone cannot prove which happened.

The tenant is NOT created here. It is the US benchmark tenant with the seven
invoices these documents refer to (SOS-100442, APS-410093, TSD-620458,
BRL-200981, CMC-330217, RFG-500712 and outbound IEQ-US-9001) already ingested;
pass its id with `--tenant`. Requires the backend on :8000 with mock auth and the
queue worker running, the same as the extraction harness.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The buyer on every generated document. One constant so a change cannot make
#: two documents disagree about who the customer is.
US_BUYER = "Infinevo Cloud Inc., 120 Innovation Way, Austin, TX 78702, USA"

#: The confirm-matches card and the read-or-compare card, as the user sees them.
#: Matched on the answer text rather than on a payload key because the probe
#: talks to the same HTTP contract the FE does, and `MessageResponse` does not
#: currently forward every attachment key (filed as Gap 474).
_CARD_PATTERN = re.compile(
    r"(Confirm which one|Would you like me to read|please check these carefully)",
    re.IGNORECASE,
)


def say(text):
    """`print()` that cannot kill a 15-minute run.

    The console on this machine is cp1252 and model prose is not: a single
    non-breaking hyphen (U+2011) in one answer aborted a probe at turn A9 with
    `UnicodeEncodeError`, losing the eight turns already scored. The JSON is
    written as UTF-8 and keeps the real characters; only the progress line is
    degraded.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _pdf(path, title, header_lines, table_head, rows, footer_lines):
    """One generated document. reportlab is imported lazily so `--help` works
    without it."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=letter)
    y = [750]

    def w(text, dy=17, size=10.5, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(50, y[0], text)
        y[0] -= dy

    w(title, 26, 16, True)
    for line in header_lines:
        w(line)
    y[0] -= 8
    if table_head:
        w(table_head, 17, 10, True)
    for row in rows:
        w(row, 16, 10)
    y[0] -= 8
    for line in footer_lines:
        w(line, 15, 9.5)
    c.save()
    return path


def build_documents(docs_dir):
    """The eight documents, regenerated byte-for-byte on every run.

    Regenerated rather than committed as fixtures on purpose: the figures in them
    are the same figures the `required` regexes below assert on, so keeping the
    two in one file makes it impossible to change a document and forget to change
    what the probe expects of it.
    """
    os.makedirs(docs_dir, exist_ok=True)
    d = {}
    d["po_summit"] = _pdf(
        os.path.join(docs_dir, "PO-US-7001_summit.pdf"),
        "PURCHASE ORDER",
        [
            f"Buyer: {US_BUYER}",
            "PO No: PO-US-7001    PO Date: 05/28/2026    Payment Terms: Net 30",
            "Vendor: Summit Office Supplies, Austin, TX",
        ],
        "Line  Description                     Qty     Unit Price ($)   Amount ($)",
        ["1     Laptop stands                   10      45.00            450.00"],
        [
            "Subtotal: $450.00    Sales Tax (0%): $0.00    Order Total: $450.00",
            "No sales tax: B2B service item.",
            "This is a Purchase Order and does not authorize payment. Invoice against this PO number only.",
        ],
    )
    d["po_apex"] = _pdf(
        os.path.join(docs_dir, "PO-US-7002_apex.pdf"),
        "PURCHASE ORDER",
        [
            f"Buyer: {US_BUYER}",
            "PO No: PO-US-7002    PO Date: 05/30/2026    Payment Terms: Net 30",
            "Vendor: Apex Print Solutions, Denver, CO",
        ],
        "Line  Description                     Qty     Unit Price ($)   Amount ($)",
        ["1     Business cards (5,000 qty)      5000    0.08             400.00"],
        [
            "Subtotal: $400.00    Sales Tax (8%): $32.00    Order Total: $432.00",
            "This is a Purchase Order and does not authorize payment. Invoice against this PO number only.",
        ],
    )
    d["cn_apex"] = _pdf(
        os.path.join(docs_dir, "CN-APS-0021_apex_credit_note.pdf"),
        "CREDIT NOTE",
        [
            "Issued by: Apex Print Solutions, 900 Larimer St, Denver, CO 80204",
            f"Bill To: {US_BUYER}",
            "Credit Note No: CN-APS-0021    Date: 06/20/2026    Against Invoice: APS-410093",
        ],
        "Line  Description                                   Amount ($)",
        [
            "1     Correction: business cards over-billed (5,000 x $0.08 = $400.00, billed $420.00)   -20.00",
            "2     Sales tax 8% on correction                                                          -1.60",
        ],
        [
            "Total Credit: -$21.60",
            "Apply this credit against invoice APS-410093. Revised amount due on APS-410093: $432.00.",
        ],
    )
    d["qt_titan"] = _pdf(
        os.path.join(docs_dir, "QTN-TSD-3310_titan_quotation.pdf"),
        "QUOTATION",
        [
            "From: Titan Steel Distributors, 44 Foundry Rd, Pittsburgh, PA 15212",
            f"To: {US_BUYER}",
            "Quotation No: QTN-TSD-3310    Date: 06/01/2026    Validity: 30 days    Your PO ref: PO-71004",
        ],
        "Line  Description         Qty    Unit Price ($)   Amount ($)",
        [
            "1     Steel beams         20     310.00           6,200.00",
            "2     Steel plates        15     210.00           3,150.00",
            "3     Delivery            1      250.00           250.00",
        ],
        [
            "Subtotal: $9,600.00    Sales Tax (6%): $576.00    Quoted Total: $10,176.00",
            "This is a quotation, not an invoice. Prices firm for 30 days.",
        ],
    )
    d["soa_blueridge"] = _pdf(
        os.path.join(docs_dir, "SOA-BRL-2026-06_blue_ridge_statement.pdf"),
        "STATEMENT OF ACCOUNT",
        [
            "From: Blue Ridge Logistics, 1800 Tryon St, Charlotte, NC 28202",
            f"Customer: {US_BUYER}",
            "Statement Date: 06/30/2026    Period: 06/01/2026 - 06/30/2026    Account: INFINEVO-US",
        ],
        "Date         Reference      Description               Amount ($)    Balance ($)",
        [
            "06/10/2026   BRL-200981     Invoice - freight          2,386.31      2,386.31",
            "06/24/2026   BRL-201044     Invoice - freight            980.00      3,366.31",
        ],
        [
            "Total Outstanding: $3,366.31",
            "Please remit within terms. Queries: ar@blueridgelogistics.example",
        ],
    )
    d["dn_cascade"] = _pdf(
        os.path.join(docs_dir, "DN-CMC-5540_cascade_delivery_note.pdf"),
        "DELIVERY NOTE / PACKING SLIP",
        [
            "Shipper: Cascade Manufacturing Co, 2200 NW Industrial Ave, Portland, OR 97210",
            f"Ship To: {US_BUYER}",
            "Delivery Note No: DN-CMC-5540    Date: 06/12/2026    Your PO: PO-88342    Carrier: Pacific Freight",
        ],
        "Line  Description            Qty Shipped   UOM",
        [
            "1     CNC machined parts     50            pcs",
            "2     Custom tooling         2             sets",
        ],
        [
            "No prices on this document. Goods shipped in full against PO-88342.",
            "Received in good condition: ______________",
        ],
    )
    d["ra_northpoint"] = _pdf(
        os.path.join(docs_dir, "RA-NPR-8871_northpoint_remittance.pdf"),
        "REMITTANCE ADVICE",
        [
            "From: NorthPoint Retail Inc., 233 S Wacker Dr, Chicago, IL 60606",
            f"To: {US_BUYER}",
            "Remittance No: RA-NPR-8871    Payment Date: 07/02/2026    Method: ACH    Bank Ref: ACH-77120934",
        ],
        "Invoice        Invoice Date   Gross ($)     Deductions ($)   Paid ($)",
        ["IEQ-US-9001    06/25/2026     2,500.00      0.00             2,500.00"],
        [
            "Total Paid: $2,500.00",
            "This payment settles the invoice(s) listed above in full.",
        ],
    )
    d["ct_redwood"] = _pdf(
        os.path.join(docs_dir, "CT-RFG-2026_redwood_service_contract.pdf"),
        "SERVICE CONTRACT / RATE AGREEMENT",
        [
            "Between: Redwood Facilities Group, 5100 Westheimer Rd, Houston, TX 77056 (Provider)",
            f"and: {US_BUYER} (Client)",
            "Contract No: CT-RFG-2026-04    Term: 04/01/2026 - 03/31/2027    Billing: monthly in arrears",
        ],
        "Item  Service                          Rate",
        [
            "1     Janitorial services (monthly)    $1,200.00 per month",
            "2     Consumable supplies              at cost, capped at $300.00 per month",
        ],
        [
            "Taxes: Texas sales tax at 8.25% applies to the full monthly invoice subtotal.",
            "Payment terms: Net 30 from invoice date. Invoices must reference PO-61190.",
        ],
    )
    return d


#: The turn set. `(attachment keys | None, intent | None, question, required, forbidden)`.
#: Ids are assigned as `<session><n>` — A1..A9, B1..B7 — and those ids are what
#: Gaps 470/472/473 and the chat report cite, so they must not be reordered.
SESSIONS = [
    (
        "A",
        ["po_summit", "po_apex", "cn_apex", "qt_titan", "soa_blueridge"],
        [
            (["po_summit"], "read",
             "What is this document, who is the vendor, and what is the order total?",
             [r"purchase order", r"Summit", r"450"], []),
            (["po_summit"], "compare",
             "Which invoice in our system does this PO relate to, and does it match on quantity, price and total?",
             [r"SOS-100442", r"(match|agree|consistent|same|no discrepanc)"],
             [r"(mismatch|does not match|doesn't match)"]),
            (["po_apex"], "compare",
             "Compare this PO with the matching Apex Print Solutions invoice. Any discrepancies?",
             [r"APS-410093", r"(420|20\.00|discrepan|mismatch|differ|over)"], []),
            # A4 — Gap 472. Two documents, and the answer is 452 - 20 = 432.
            (["po_apex", "cn_apex"], "read",
             "Using the PO and the credit note together: after the credit is applied, "
             "what do we owe Apex, and does that equal the PO total?",
             [r"432", r"(yes|equal|match|same)"], []),
            (["qt_titan"], "compare",
             "Check the Titan Steel invoice against this quotation line by line. "
             "Which line differs and by how much?",
             [r"TSD-620458", r"(steel plates|plates)", r"(360|3,?510|3,?150)"], []),
            (["qt_titan", "po_summit"], "compare",
             "Of these two documents, which one has an invoice that matches it exactly "
             "and which one has a billing discrepancy?",
             [r"Summit", r"Titan", r"(discrepan|differ|mismatch|over)"], []),
            # A7 — Gap 470. Every reference named, not counted.
            (["soa_blueridge"], "reconcile",
             "Reconcile this statement against our records. Which lines do we have "
             "invoices for and which are missing?",
             [r"BRL-200981", r"BRL-201044",
              r"(missing|not (found|in|on)|no (record|invoice)|unmatched|cannot find|can't find)"], []),
            (None, None,
             "What is the combined grand total of invoices BRL-200981 and TSD-620458?",
             [r"12,?943\.91"], []),
            (None, None,
             "Why was no sales tax charged on the Cascade Manufacturing Co invoice CMC-330217?",
             [r"(exempt|OR-EX-88231|certificate)"], []),
        ],
    ),
    (
        "B",
        ["dn_cascade", "ra_northpoint", "ct_redwood"],
        [
            (["dn_cascade"], "read",
             "What was delivered on this delivery note and against which PO?",
             [r"50", r"(CNC|machined)", r"PO-88342"], []),
            (["dn_cascade"], "compare",
             "Do the delivered quantities match the Cascade Manufacturing invoice CMC-330217?",
             [r"CMC-330217", r"(match|agree|consistent|same)"],
             [r"(short[- ]shipped|do not match|does not match|don't match)"]),
            # B3 — Gap 470. The remittance names the invoice it pays.
            (["ra_northpoint"], "reconcile",
             "Which of our outbound invoices does this remittance pay, and is it paid in full?",
             [r"IEQ-US-9001", r"(full|2,?500)"], []),
            # B4 — Gap 473. 8.25% of 1,500.00 = 123.75, against 90.00 invoiced.
            (["ct_redwood"], "compare",
             "Per this contract, is the sales tax on Redwood invoice RFG-500712 correct? "
             "Show the expected figure.",
             [r"RFG-500712", r"123\.75", r"(90|incorrect|wrong|under|discrepan|differ)"], []),
            # B5 — task 29.7. Two documents, neither compared to the other.
            (["dn_cascade", "ct_redwood"], "compare",
             "Looking at both documents, which vendor invoice needs follow-up with the "
             "vendor and why?",
             [r"Redwood", r"(tax|123\.75|90)"], []),
            (None, None,
             "Which inbound invoice has the highest grand total?",
             [r"(TSD-620458|Titan)", r"10,?557\.60"], []),
            (None, None,
             "List the inbound invoices that carry no PO number.",
             [r"SOS-100442", r"APS-410093"],
             [r"BRL-200981|CMC-330217|RFG-500712|TSD-620458"]),
        ],
    ),
]


def flush_answer_cache():
    """Delete every `chat_answer_cache*` key, or say why it could not.

    Not optional housekeeping: the answer cache is keyed on the question, not on
    the model, so a second model scored without this is scored on the first
    model's answers. Returns the number of keys deleted, or None on failure —
    the caller records that in the JSON so a run cannot silently be a cache hit.
    """
    try:
        import redis
        from config import get_settings

        client = redis.Redis.from_url(get_settings().REDIS_URL)
        deleted = 0
        for key in client.scan_iter(match="chat_answer_cache*", count=500):
            client.delete(key)
            deleted += 1
        return deleted
    except Exception as e:  # a probe that cannot flush must SAY so, not proceed quietly
        say(f"WARNING: answer-cache flush failed: {e}")
        return None


def deployments_in_force():
    """Which deployment actually served this run, read from settings.

    A run labelled `gpt-5.6-terra` that was really served by Luna is worse than
    no run at all, and the `--label` argument cannot prove which happened.
    """
    try:
        from config import get_settings

        s = get_settings()
        return {
            name: getattr(s, name, None)
            for name in (
                "AZURE_OPENAI_DEPLOYMENT_NAME",
                "AZURE_OPENAI_FAST_DEPLOYMENT_NAME",
                "AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME",
                "AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME",
                "AZURE_OPENAI_API_VERSION",
            )
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def run_probe(*, label, tenant_id, base_url, docs_dir, timeout, flush):
    documents = build_documents(docs_dir)
    headers = {"Authorization": f"Bearer test_{tenant_id}"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    cache_flushed = flush_answer_cache() if flush else "not requested"
    results, attachments_seen = [], {}

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for session_name, keys, turns in SESSIONS:
            session_id = (
                client.post(
                    "/chat/sessions",
                    headers=headers,
                    json={"title": f"attach-probe-{label}-{session_name}-{stamp}"},
                )
                .raise_for_status()
                .json()["id"]
            )
            attached = {}
            for key in keys:
                path = documents[key]
                with open(path, "rb") as fh:
                    resp = client.post(
                        f"/chat/sessions/{session_id}/attachments",
                        headers=headers,
                        files={"file": (os.path.basename(path), fh, "application/pdf")},
                    )
                resp.raise_for_status()
                row = resp.json()
                # Extraction runs on the queue worker; poll rather than sleep a
                # fixed amount, because a cold worker is slower than a warm one
                # and a fixed wait would make the probe flaky, not faster.
                for _ in range(80):
                    if row.get("extraction_status") != "PENDING":
                        break
                    time.sleep(3)
                    row = (
                        client.get(f"/chat/attachments/{row['id']}", headers=headers)
                        .raise_for_status()
                        .json()
                    )
                attached[key] = row
                attachments_seen[key] = row
                say(
                    f"[{session_name} attach {key}] doc_type={row.get('doc_type')} "
                    f"status={row.get('extraction_status')} number={row.get('doc_number')} "
                    f"party={row.get('party_name')} total={row.get('grand_total')} "
                    f"tier={row.get('match_tier')} "
                    f"cands={len(row.get('candidate_invoice_ids') or [])}"
                )

            for index, (turn_keys, intent, question, required, forbidden) in enumerate(turns, 1):
                body = {"content": question}
                if turn_keys:
                    body["attachment_id"] = attached[turn_keys[0]]["id"]
                    if len(turn_keys) > 1:
                        body["attachment_ids"] = [attached[k]["id"] for k in turn_keys]
                    # "reconcile" is not an FE intent — it is what the backend
                    # infers for an advisory document (Gap 432). Sending it would
                    # test a value the product never sends.
                    if intent and intent != "reconcile":
                        body["attachment_intent"] = intent

                started = time.time()
                answer, error, payload = "", None, {}
                try:
                    resp = client.post(
                        f"/chat/sessions/{session_id}/message",
                        params={"sync": "true"},
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                    answer = payload.get("content") or ""
                except Exception as e:
                    error = str(e)[:300]

                confirmed = False
                if turn_keys and _CARD_PATTERN.search(answer or ""):
                    # The designed UX step. Answer it the way the FE would, then
                    # re-ask the same question.
                    for key in turn_keys:
                        current = (
                            client.get(f"/chat/attachments/{attached[key]['id']}", headers=headers)
                            .raise_for_status()
                            .json()
                        )
                        candidates = current.get("candidate_invoice_ids") or []
                        if candidates and not current.get("confirmed_invoice_ids"):
                            client.post(
                                f"/chat/attachments/{attached[key]['id']}/confirm-matches",
                                headers=headers,
                                json={"invoice_ids": candidates},
                            ).raise_for_status()
                            confirmed = True
                    body["attachment_intent"] = "compare"
                    try:
                        resp = client.post(
                            f"/chat/sessions/{session_id}/message",
                            params={"sync": "true"},
                            headers=headers,
                            json=body,
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                        answer = payload.get("content") or ""
                        error = None
                    except Exception as e:
                        answer, error = "", str(e)[:300]

                latency = round(time.time() - started, 1)
                passed = (
                    not error
                    and all(re.search(p, answer, re.I) for p in required)
                    and not any(re.search(p, answer, re.I) for p in forbidden)
                )
                turn_id = f"{session_name}{index}"
                results.append(
                    {
                        "id": turn_id,
                        "attachments": turn_keys,
                        "intent": intent,
                        "question": question,
                        "answer": answer,
                        "latency_s": latency,
                        "error": error,
                        "passed": bool(passed),
                        "required": required,
                        "forbidden": forbidden,
                        "confirm_step": confirmed,
                    }
                )
                flat = (answer or "")[:240].replace("\n", " ")
                say(
                    f"[{turn_id}] {'PASS' if passed else 'FAIL'} {latency}s "
                    f"att={turn_keys}{' +confirm' if confirmed else ''} :: {flat}"
                    f"{' ERR ' + error if error else ''}"
                )

    def bucket(predicate):
        rows = [r for r in results if predicate(r)]
        return f"{sum(1 for r in rows if r['passed'])}/{len(rows)}"

    latencies = sorted(r["latency_s"] for r in results)
    return {
        "label": label,
        "tenant_id": tenant_id,
        "run_started_utc": stamp,
        "deployments_in_force": deployments_in_force(),
        "answer_cache_keys_flushed": cache_flushed,
        "attachments": attachments_seen,
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
        "single_doc": bucket(lambda r: r["attachments"] and len(r["attachments"]) == 1),
        "two_docs": bucket(lambda r: r["attachments"] and len(r["attachments"]) == 2),
        "no_attachment": bucket(lambda r: not r["attachments"]),
        "p95_s": latencies[int(0.95 * (len(latencies) - 1))] if latencies else None,
        "turns": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="model label, e.g. gpt-5.6-luna")
    parser.add_argument("--tenant", required=True, help="US benchmark tenant uuid")
    parser.add_argument("--out", required=True, help="path to write the run JSON")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument(
        "--docs-dir",
        default=None,
        help="where the 8 PDFs are generated (default: <out dir>/attach_docs)",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--flush-cache",
        action="store_true",
        help="delete every chat_answer_cache* key first — required for a "
        "model-to-model comparison to mean anything",
    )
    args = parser.parse_args(argv)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    docs_dir = args.docs_dir or os.path.join(out_dir, "attach_docs")

    summary = run_probe(
        label=args.label,
        tenant_id=args.tenant,
        base_url=args.base_url,
        docs_dir=docs_dir,
        timeout=args.timeout,
        flush=args.flush_cache,
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(
        f"\n{summary['label']}: {summary['passed']}/{summary['total']} passed; "
        f"single-doc {summary['single_doc']}, two-doc {summary['two_docs']}, "
        f"no-attachment {summary['no_attachment']}, p95 {summary['p95_s']}s "
        f"-> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
