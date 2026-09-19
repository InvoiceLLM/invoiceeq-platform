import json, os, sys, time
from datetime import datetime, timezone
import httpx

TENANT = "00000000-0000-0000-0000-000000000000"
BASE = "http://127.0.0.1:8000/api/v1"
UPLOAD_DIR = r"C:/Users/S Banerjee/Desktop/Invoice_LLM/showcase/vpi_demo/upload"
CN_PATH = r"C:/Users/S Banerjee/Desktop/Invoice_LLM/showcase/vpi_demo/invoices_pdf/inbound_creditnote_BharatHardware_BHF-CN-2010.pdf"

headers = {"Authorization": "Bearer test_" + TENANT}

TERMINAL = {"EXTRACTED", "EXTRACT_FAILED"}

CASES = [
    ("A1", "PO_PO-VPI-1043_SHR.pdf", "Going by this order, how much of Shree Packaging balance is still unpaid?", None),
    ("A2", "BankStatement_HDFC_4471_Aug2026.pdf", "Of the vendor payments on this statement, is any of them still showing as unpaid in our books?", None),
    ("A3", "PA_PA-VPI-0072_BHA.pdf", "After this advice, what is left on our Bharat Hardware account?", None),
    ("A4", "DC_DC-NMT-2291_NAT.pdf", "Check this against what National MRO invoiced us.", "no_poll_then_poll"),
    ("A5", "PO_PO-VPI-1041_RAJ.pdf", "Is this a sales order one of our customers sent us, or a purchase we placed?", None),
    ("A6", "BankStatement_HDFC_4471_Aug2026.pdf", "This statement has no party column. Which of these lines are money we owed and which are money owed to us?", None),
    ("A7", "PA_PA-VPI-0071_OM.pdf", "What do we still owe Om Stationery Mart?", None),
    ("A8", "PA_PA-VPI-0071_OM.pdf", "What is our outstanding payable balance with Om Stationery Mart?", None),
    ("A9", "DC_DC-RSC-0812_RAJ.pdf", "What is the rupee value of this delivery, going by the challan itself?", None),
    ("A10", None, "Which invoice number does this credit note quote?", None),
    ("A11", None, "Bharat sent this. Does it change what we pay on the 15 September run?", None),
    ("B2", "PO_PO-VPI-1042_GBP.pdf", "Is the Ganesh Bearings invoice within this PO?", None),
    ("B5", "DC_DC-NMT-2291_NAT.pdf", "Check delivery against invoice", None),
    ("B6", "DC_DC-BHF-0455_BHA.pdf", "Any short delivery here?", None),
    ("B9", "PA_PA-VPI-0073_SHR.pdf", "What do we still owe Shree Packaging?", None),
    ("B10", "BankStatement_HDFC_4471_Aug2026.pdf", "Match this statement to our books", None),
    ("B11", None, "Bharat sent this - what do we actually owe them?", None),
]

def say(t):
    try:
        print(t, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(t.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)

def poll_terminal(client, att_id, row, max_tries=100):
    for _ in range(max_tries):
        if row.get("extraction_status") in TERMINAL:
            return row
        time.sleep(3)
        row = client.get("/chat/attachments/" + att_id, headers=headers).raise_for_status().json()
    return row

def ask(client, sess, question, attachment_id):
    body = {"content": question, "attachment_id": attachment_id}
    started = time.time()
    answer, error, payload = "", None, {}
    try:
        resp = client.post("/chat/sessions/" + sess + "/message", params={"sync": "true"}, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
        answer = payload.get("content") or ""
    except Exception as e:
        error = str(e)[:800]
    latency = round(time.time() - started, 1)
    return answer, error, payload, latency, body

def maybe_confirm(client, att_id, sess, answer, body):
    confirmed = False
    payload = None
    trigger_strings = ["Confirm which", "please check these carefully", "Would you like me to read"]
    if answer and any(s in answer for s in trigger_strings):
        current = client.get("/chat/attachments/" + att_id, headers=headers).raise_for_status().json()
        candidates = current.get("candidate_invoice_ids") or []
        if candidates:
            client.post("/chat/attachments/" + att_id + "/confirm-matches", headers=headers,
                        json={"invoice_ids": candidates}).raise_for_status()
            confirmed = True
            body["attachment_intent"] = "compare"
            try:
                resp = client.post("/chat/sessions/" + sess + "/message", params={"sync": "true"},
                                    headers=headers, json=body)
                resp.raise_for_status()
                payload = resp.json()
                answer = payload.get("content") or ""
            except Exception:
                pass
    return answer, confirmed, payload

results = []
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

with httpx.Client(base_url=BASE, timeout=300.0) as client:
    for case_id, filename, question, special in CASES:
        path = CN_PATH if filename is None else os.path.join(UPLOAD_DIR, filename)
        sess = client.post("/chat/sessions", headers=headers,
                            json={"title": "after-fix-" + case_id + "-" + stamp}).raise_for_status().json()["id"]
        with open(path, "rb") as fh:
            resp = client.post("/chat/sessions/" + sess + "/attachments", headers=headers,
                                files={"file": (os.path.basename(path), fh, "application/pdf")})
        resp.raise_for_status()
        row = resp.json()
        att_id = row["id"]

        label = filename if filename else "credit_note_BHF-CN-2010"
        record = {"case": case_id, "attachment_file": label,
                   "question": question, "session_id": sess, "turns": []}

        if special == "no_poll_then_poll":
            say("[" + case_id + "] TURN A (no poll) status_at_ask=" + str(row.get("extraction_status")))
            answer, error, payload, latency, body = ask(client, sess, question, att_id)
            say("[" + case_id + "] TURN A Q: " + question)
            say("[" + case_id + "] TURN A latency=" + str(latency) + "s error=" + str(error))
            say("[" + case_id + "] TURN A A: " + answer)
            record["turns"].append({"label": "A_immediate", "status_at_ask": row.get("extraction_status"),
                                     "answer": answer, "error": error, "payload": payload, "latency_s": latency})
            row = client.get("/chat/attachments/" + att_id, headers=headers).raise_for_status().json()
            row = poll_terminal(client, att_id, row)
            say("[" + case_id + "] post-poll status=" + str(row.get("extraction_status")) + " cands=" + str(row.get("candidate_invoice_ids")))
            sess_b = client.post("/chat/sessions", headers=headers,
                                  json={"title": "after-fix-" + case_id + "B-" + stamp}).raise_for_status().json()["id"]
            answer2, error2, payload2, latency2, body2 = ask(client, sess_b, question, att_id)
            answer2b, confirmed, payload2b = maybe_confirm(client, att_id, sess_b, answer2, body2)
            if payload2b is not None:
                answer2, payload2 = answer2b, payload2b
            say("[" + case_id + "] TURN B Q: " + question)
            say("[" + case_id + "] TURN B confirmed=" + str(confirmed) + " latency=" + str(latency2) + "s error=" + str(error2))
            say("[" + case_id + "] TURN B A: " + answer2)
            record["turns"].append({"label": "B_after_terminal", "status_at_ask": row.get("extraction_status"),
                                     "candidate_invoice_ids": row.get("candidate_invoice_ids"),
                                     "confirmed": confirmed, "answer": answer2, "error": error2,
                                     "payload": payload2, "latency_s": latency2})
            record["attachment_row_final"] = row
            say("=" * 100)
            results.append(record)
            continue

        row = poll_terminal(client, att_id, row)
        say("[" + case_id + "] attach " + label + " doc_type=" + str(row.get("doc_type")) +
            " status=" + str(row.get("extraction_status")) + " number=" + str(row.get("doc_number")) +
            " party=" + str(row.get("party_name")) + " total=" + str(row.get("grand_total")) +
            " tier=" + str(row.get("match_tier")) + " cands=" + str(row.get("candidate_invoice_ids")))

        answer, error, payload, latency, body = ask(client, sess, question, att_id)
        answer2, confirmed, payload2 = maybe_confirm(client, att_id, sess, answer, body)
        if payload2 is not None:
            answer, payload = answer2, payload2

        say("[" + case_id + "] Q: " + question)
        say("[" + case_id + "] confirmed=" + str(confirmed) + " latency=" + str(latency) + "s error=" + str(error))
        say("[" + case_id + "] A: " + answer)
        say("=" * 100)
        record["turns"].append({"label": "single", "status_at_ask": row.get("extraction_status"),
                                 "candidate_invoice_ids": row.get("candidate_invoice_ids"),
                                 "confirmed": confirmed, "answer": answer, "error": error,
                                 "payload": payload, "latency_s": latency})
        record["attachment_row_final"] = row
        results.append(record)

out_path = sys.argv[1] if len(sys.argv) > 1 else "regression_after_fixes_out.json"
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=2, default=str)
say("\nWrote " + out_path)
