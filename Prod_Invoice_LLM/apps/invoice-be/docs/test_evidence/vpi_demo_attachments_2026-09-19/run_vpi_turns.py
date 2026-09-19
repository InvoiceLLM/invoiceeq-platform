import json, os, sys, time
from datetime import datetime, timezone
import httpx

TENANT = "00000000-0000-0000-0000-000000000000"
BASE = "http://127.0.0.1:8000/api/v1"
UPLOAD_DIR = r"C:/Users/S Banerjee/Desktop/Invoice_LLM/showcase/vpi_demo/upload"
CN_PATH = r"C:/Users/S Banerjee/Desktop/Invoice_LLM/showcase/vpi_demo/invoices_pdf/inbound_creditnote_BharatHardware_BHF-CN-2010.pdf"

headers = {"Authorization": f"Bearer test_{TENANT}"}

TURNS = [
    (1, "PO_PO-VPI-1041_RAJ.pdf", "Does this PO match the Rajesh Steel invoice?"),
    (2, "PO_PO-VPI-1042_GBP.pdf", "Is the Ganesh Bearings invoice within this PO?"),
    (3, "PO_PO-VPI-1043_SHR.pdf", "Compare with Shree Packaging's August invoice"),
    (4, "DC_DC-RSC-0812_RAJ.pdf", "Was everything on this challan invoiced?"),
    (5, "DC_DC-NMT-2291_NAT.pdf", "Check delivery against invoice"),
    (6, "DC_DC-BHF-0455_BHA.pdf", "Any short delivery here?"),
    (7, "PA_PA-VPI-0071_OM.pdf", "Which invoice does this payment settle?"),
    (8, "PA_PA-VPI-0072_BHA.pdf", "Is Bharat Hardware fully paid?"),
    (9, "PA_PA-VPI-0073_SHR.pdf", "What do we still owe Shree Packaging?"),
    (10, "BankStatement_HDFC_4471_Aug2026.pdf", "Match this statement to our books"),
    (11, None, "Bharat sent this - what do we actually owe them?"),
]

def say(t):
    try:
        print(t)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(t.encode(enc, errors="replace").decode(enc, errors="replace"))

results = []
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

with httpx.Client(base_url=BASE, timeout=300.0) as client:
    for num, filename, question in TURNS:
        path = CN_PATH if filename is None else os.path.join(UPLOAD_DIR, filename)
        sess = client.post("/chat/sessions", headers=headers,
                            json={"title": f"vpi-attach-turn-{num}-{stamp}"}).raise_for_status().json()["id"]
        with open(path, "rb") as fh:
            resp = client.post(f"/chat/sessions/{sess}/attachments", headers=headers,
                                files={"file": (os.path.basename(path), fh, "application/pdf")})
        resp.raise_for_status()
        row = resp.json()
        for _ in range(80):
            if row.get("extraction_status") != "PENDING":
                break
            time.sleep(3)
            row = client.get(f"/chat/attachments/{row['id']}", headers=headers).raise_for_status().json()
        say(f"[turn {num}] attach {filename or 'CREDIT_NOTE'} doc_type={row.get('doc_type')} "
            f"status={row.get('extraction_status')} number={row.get('doc_number')} "
            f"party={row.get('party_name')} total={row.get('grand_total')} "
            f"tier={row.get('match_tier')} cands={row.get('candidate_invoice_ids')}")

        body = {"content": question, "attachment_id": row["id"]}
        started = time.time()
        answer, error = "", None
        try:
            resp = client.post(f"/chat/sessions/{sess}/message", params={"sync": "true"},
                                headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
            answer = payload.get("content") or ""
        except Exception as e:
            error = str(e)[:500]
            payload = {}

        confirmed = False
        if answer and ("Confirm which" in answer or "please check these carefully" in answer or "Would you like me to read" in answer):
            current = client.get(f"/chat/attachments/{row['id']}", headers=headers).raise_for_status().json()
            candidates = current.get("candidate_invoice_ids") or []
            if candidates:
                client.post(f"/chat/attachments/{row['id']}/confirm-matches", headers=headers,
                            json={"invoice_ids": candidates}).raise_for_status()
                confirmed = True
                body["attachment_intent"] = "compare"
                try:
                    resp = client.post(f"/chat/sessions/{sess}/message", params={"sync": "true"},
                                        headers=headers, json=body)
                    resp.raise_for_status()
                    payload = resp.json()
                    answer = payload.get("content") or ""
                    error = None
                except Exception as e:
                    error = str(e)[:500]

        latency = round(time.time() - started, 1)
        say(f"[turn {num}] Q: {question}")
        say(f"[turn {num}] confirmed={confirmed} latency={latency}s error={error}")
        say(f"[turn {num}] A: {answer}")
        say("="*100)
        results.append({
            "turn": num, "attachment_file": filename or "credit_note_BHF-CN-2010",
            "question": question, "attachment_row": row, "session_id": sess,
            "answer": answer, "raw_payload": payload, "confirmed": confirmed,
            "latency_s": latency, "error": error,
        })

out_path = sys.argv[1] if len(sys.argv) > 1 else "vpi_turns_out.json"
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=2, default=str)
say(f"\nWrote {out_path}")
