# ⚡ InvoiceLLM — External Partner API Testing Portal

Standalone, zero-dependency interactive API test portal and real-time HTTP inspector console for verifying all core endpoints of InvoiceLLM.

---

## 🚀 How to Run

### Method 1: Double-click to Open in Browser
Simply open [`testing/apis/index.html`](file:///d:/testllm/Invoice-LLM-SOLO-Dev/testing/apis/index.html) in Chrome, Edge, or Firefox.

### Method 2: Run via Local Python Web Server
From terminal:
```powershell
cd testing/apis
python -m http.server 8080
```
Then visit `http://localhost:8080` in your browser.

---

## 🧪 Available Live Tests

| Card | Endpoint | Auth Mechanism | What It Tests |
|---|---|---|---|
| **Test 1: Inbound Webhook** | `POST /api/v1/email/mailintegration` | `?key=AdmInvoiceSecret2026` | Simulates SendGrid email with attached PDF, stores in Azure Blob, enqueues for OCR. |
| **Test 2: Support Ticket API** | `POST /api/contact` | Public / None | Submits inquiry JSON, creates `INQ-2026-XXXX` reference number, dispatches SendGrid notification. |
| **Test 3: Upload Invoice** | `POST /api/v1/invoices/upload` | `Authorization: Bearer <token>` | Uploads PDF (custom or auto-generated), creates DB Invoice, triggers OCR & SENTINEL. |
| **Test 4: Identity Verification** | `GET /api/v1/auth/me` | `Authorization: Bearer <token>` | Validates session token, returns tenant ID, org name, user role, and plan credits. |

---

## 📡 Live HTTP Inspector Console

The inspector captures and displays in real time:
- **Dispatched Request:** HTTP Method + Full Target URL
- **Request Headers:** Auth headers, Content-Type
- **Request Payload:** JSON parameters or multipart file summaries
- **Response Metrics:** Status code (e.g. `200 OK`, `401 Unauthorized`), Latency timer (`185ms`)
- **Response Body:** Formatted syntax-highlighted JSON output
