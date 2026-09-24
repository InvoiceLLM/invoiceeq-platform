# InvoiceEQ — API & Webhook End-to-End Testing Guide
Platform: https://invoicellm.admsofttech.com
Tools Needed: Postman (free) + Webhook.site (free, browser)
Language: Hinglish (Hindi + English mixed)
Last Updated: 2026-09-23

---

## SETUP — Pehle Yeh Karo (Do This First)

### Step 1: Postman Setup

1. Postman download karo — https://www.postman.com/downloads/ (free)
2. New Collection banao: InvoiceEQ API Tests
3. Collection ke andar Environment banao: InvoiceEQ Dev
4. Yeh variables set karo:

| Variable    | Value                                             |
|-------------|---------------------------------------------------|
| base_url    | https://invoicellm.admsofttech.com                |
| api_key     | (Step 2 ke baad milegi — abhi khali chhodo)       |
| invoice_id  | (testing ke time fill hoga)                       |
| webhook_id  | (testing ke time fill hoga)                       |

### Step 2: API Key Generate Karo

1. Browser mein open karo: https://invoicellm.admsofttech.com/settings/security
2. Admin account se login karo
3. "API Keys" section mein jao
4. "Generate API Key" / "Rotate Key" button click karo
5. Woh key copy karo — yeh sirf ek baar dikhti hai!
6. Format hoga: inv_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
7. Yeh key Postman Environment mein api_key variable mein paste karo

### Step 3: Webhook Receiver Setup (Webhook.site)

1. Browser mein open karo: https://webhook.site
2. Automatically ek unique URL milega: https://webhook.site/abc-1234-xyz-9876
3. Yeh URL copy karke rakh lo — webhook testing mein kaam aayegi

---

## Authentication — Header Kaise Lagaate Hain

Har API call mein yeh header mandatory hai:

  Key:   Authorization
  Value: Bearer {{api_key}}

Postman mein shortcut: Collection level pe Authorization tab mein:
  - Type: Bearer Token
  - Token: {{api_key}}

---

## PART 1 — AUTH APIs

### TEST A-1: Apni Identity Verify Karo
Yeh kya karta hai: API key valid hai ya nahi, aur role/permissions kya hain

  Method:  GET
  URL:     {{base_url}}/api/v1/settings/security/api-key/verify
  Headers: Authorization: Bearer {{api_key}}

Expected Response (200 OK):
  {
    "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "role": "Admin",
    "can_load": true,
    "can_audit": true,
    "can_train": true
  }

- Agar 401 aaye: API key galat ya expired hai — Security page pe rotate karo
- Agar 403 aaye: Key hai but permissions nahi

---

### TEST A-2: Current User Info Check Karo

  Method:  GET
  URL:     {{base_url}}/api/v1/auth/me
  Headers: Authorization: Bearer {{api_key}}

---

### TEST A-3: API Key Status Check Karo

  Method:  GET
  URL:     {{base_url}}/api/v1/settings/security/api-key
  Headers: Authorization: Bearer {{api_key}}

Expected Response:
  {
    "has_key": true,
    "key_prefix": "inv_live_abc1...",
    "masked_key": "inv_live_abc1................",
    "rotated_at": "2026-09-22T17:11:00",
    "last_used_at": "2026-09-23T14:30:00",
    "can_rotate": true
  }

---

## PART 2 — INVOICE UPLOAD APIs (Inbound)

### TEST I-1: Invoice PDF Upload Karo  [MOST IMPORTANT]
Yeh kya karta hai: PDF invoice system mein daalo, AI extraction start hoti hai

  Method:   POST
  URL:      {{base_url}}/api/v1/invoices/upload
  Headers:  Authorization: Bearer {{api_key}}
  Body:     form-data
            Key: files   Type: File   Value: [apna PDF choose karo]
            Key: tags    Type: Text   Value: test,postman   (optional)

Expected Response (201 Created):
  [
    {
      "invoice_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "job_id": "job_xxxxxxxxxxxxxxxx",
      "filename": "invoice_test.pdf",
      "status": "QUEUED"
    }
  ]

IMPORTANT: invoice_id aur job_id save karo — agle tests mein kaam aayenge!

Postman tip — Tests tab mein likho:
  var resp = pm.response.json();
  pm.environment.set("invoice_id", resp[0].invoice_id);
  pm.environment.set("job_id", resp[0].job_id);

Error Cases:
  400 No files uploaded   — file attach karna bhool gaye
  402 Payment Required    — free tier limit khatam
  409 Duplicate           — yahi file pehle se upload hai

---

### TEST I-2: Processing Status Check Karo
Yeh kya karta hai: AI extraction ka status dekhna

  Method:  GET
  URL:     {{base_url}}/api/v1/invoices/status/{{job_id}}
  Headers: Authorization: Bearer {{api_key}}

Status Flow:
  QUEUED -> PROCESSING -> COMPLETED       (success)
                       -> AUDIT_REQUIRED  (AI ne issue pakda)
                       -> EXTRACT_FAILED  (AI fail ho gayi)

Expected:
  {
    "job_id": "job_xxx",
    "invoice_id": "xxx-xxx-xxx",
    "status": "COMPLETED",
    "filename": "invoice_test.pdf"
  }

---

### TEST I-3: Saari Invoices List Karo

  Method:  GET
  URL:     {{base_url}}/api/v1/invoices
  Headers: Authorization: Bearer {{api_key}}

Optional Query Params:
  ?status=COMPLETED
  ?status=AUDIT_REQUIRED
  ?vendor_name=Acme
  ?page=1&page_size=20

---

### TEST I-4: Single Invoice Detail Dekho

  Method:  GET
  URL:     {{base_url}}/api/v1/invoices/{{invoice_id}}
  Headers: Authorization: Bearer {{api_key}}

Expected Response:
  {
    "id": "xxx-xxx-xxx",
    "status": "COMPLETED",
    "vendor_name": "Acme Supplies Ltd",
    "invoice_number": "INV-001",
    "invoice_date": "2026-09-01",
    "due_date": "2026-10-01",
    "subtotal": 10000.00,
    "tax_amount": 1800.00,
    "grand_total": 11800.00,
    "currency": "INR",
    "flow_direction": "INBOUND"
  }

---

### TEST I-5: Invoice PDF Download Karo

  Method:  GET
  URL:     {{base_url}}/api/v1/invoices/{{invoice_id}}/pdf
  Headers: Authorization: Bearer {{api_key}}

Postman mein: Response -> Save Response -> Save to a file

---

### TEST I-6: Invoice Delete Karo (Admin only)

  Method:  DELETE
  URL:     {{base_url}}/api/v1/invoices/{{invoice_id}}
  Headers: Authorization: Bearer {{api_key}}

Expected Response: 204 No Content
WARNING: Permanent delete hai!

---

## PART 3 — AUDIT / REVIEW APIs (Approve, Reject, Reopen)

### TEST AU-1: Invoice Approve Karo (Mark as PAID)  [MOST IMPORTANT]
Yeh kya karta hai: Invoice ko final approve karna — PAID status
Permission: Admin ya Auditor dono kar sakte hain

  Method:   PUT
  URL:      {{base_url}}/api/v1/audit/resolve/{{invoice_id}}
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "status": "PAID",
      "corrections": {},
      "notify_emails": ["finance@yourcompany.com"]
    }

Expected Response (200 OK):
  {
    "id": "xxx-xxx-xxx",
    "status": "PAID",
    "vendor_name": "Acme Supplies Ltd",
    "grand_total": 11800.00
  }

Webhook Trigger: invoice.approved event fire hogi!
Error Cases:
  400 — Invoice already PAID/REJECTED hai
  403 — Permission nahi hai
  429 — Rate limit: 60 calls/minute exceed ho gayi

---

### TEST AU-2: Invoice Reject Karo
Permission: Admin ya Auditor dono

  Method:   PUT
  URL:      {{base_url}}/api/v1/audit/resolve/{{invoice_id}}
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "status": "REJECTED",
      "reject_reason": "Duplicate Invoice",
      "corrections": {}
    }

Webhook Trigger: invoice.rejected event fire hogi

---

### TEST AU-3: Invoice Corrections Save Karo (Without Finalizing)
Yeh kya karta hai: Fields correct karo but PAID/REJECT mat karo abhi

  Method:   PUT
  URL:      {{base_url}}/api/v1/audit/resolve/{{invoice_id}}
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "corrections": {
        "vendor_name": {"new_value": "Acme Supplies Limited"},
        "grand_total": {"new_value": 12500.00}
      }
    }

Note: status field diya hi nahi — sirf corrections save hongi

---

### TEST AU-4: Invoice Reopen Karo (PAID -> AUDIT_REQUIRED)
Yeh kya karta hai: Galti se approve ho gayi invoice wapas review mein laana
Permission: ADMIN ONLY — Auditor yeh nahi kar sakta!

  Method:   PUT
  URL:      {{base_url}}/api/v1/audit/resolve/{{invoice_id}}
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "status": "AUDIT_REQUIRED"
    }

Webhook Trigger: invoice.reopened event fire hogi
Error (Auditor se): 403 Only an Admin can reopen a resolved invoice

---

### TEST AU-5: Invoice Defer Karo (Review Later)

  Method:   PUT
  URL:      {{base_url}}/api/v1/audit/resolve/{{invoice_id}}
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "status": "REVIEW_LATER"
    }

---

### TEST AU-6: Change History Dekho (Admin Only)
Yeh kya karta hai: Invoice pe kab kya kiya gaya — audit trail

  Method:  GET
  URL:     {{base_url}}/api/v1/audit-history/{{invoice_id}}
  Headers: Authorization: Bearer {{api_key}}

Expected Response:
  {
    "entries": [
      {
        "action": "RESOLVE_INVOICE",
        "actor_name": "Admin User",
        "actor_role": "Admin",
        "status_change": {"from": "COMPLETED", "to": "PAID"},
        "created_at": "2026-09-23T14:30:00Z"
      }
    ]
  }

---

## PART 4 — WEBHOOK APIs (Most Important for Integration)

### TEST W-1: Webhook Endpoint Register Karo  [MOST IMPORTANT]
Yeh kya karta hai: Apna URL register karo jahan notifications aayengi

Pehle Webhook.site kholo aur URL copy karo: https://webhook.site/your-unique-id

  Method:   POST
  URL:      {{base_url}}/api/v1/webhooks
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "target_url": "https://webhook.site/your-unique-id-here",
      "subscribed_events": [
        "invoice.approved",
        "invoice.rejected",
        "invoice.reopened",
        "outbound_invoice.approved",
        "invoice.received"
      ],
      "is_active": true
    }

Expected Response (201 Created):
  {
    "id": "webhook-uuid-here",
    "target_url": "https://webhook.site/your-unique-id",
    "is_active": true,
    "created_at": "2026-09-23T..."
  }

Save karo — Postman Tests tab mein:
  pm.environment.set("webhook_id", pm.response.json().id);

Available Event Types:
  invoice.received          -> Naya invoice upload hone pe
  invoice.approved          -> Invoice PAID mark hone pe
  invoice.rejected          -> Invoice REJECTED hone pe
  invoice.reopened          -> PAID/REJECTED se wapas AUDIT_REQUIRED pe
  invoice.requires_action   -> AI ne kuch issue pakda
  outbound_invoice.sent     -> Outbound invoice send hone pe
  outbound_invoice.approved -> Outbound invoice mark-paid hone pe

---

### TEST W-2: Webhook Fire Karo Aur Verify Karo  [End-to-End Test]
Yeh complete flow test karta hai!

Steps:
1. Webhook.site browser tab kholo (live dekh sako)
2. Postman mein ek invoice upload karo (TEST I-1)
3. Invoice approve karo (TEST AU-1)
4. Webhook.site mein dekho — kuch seconds mein POST request aani chahiye

Webhook.site mein yeh dikhna chahiye:
  METHOD: POST

  Headers:
    X-Webhook-Signature:    sha256=abcdef1234...   (V1 - body ka HMAC)
    X-Webhook-Signature-V2: sha256=xyz789...       (V2 - timestamp+body ka HMAC)
    X-Webhook-Timestamp:    1727087400             (Unix timestamp)
    X-InvoiceEQ-Timestamp:  1727087400
    X-InvoiceEQ-Event-Id:   uuid-v4-here
    Content-Type: application/json

  Body:
    {
      "event_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "occurred_at": "2026-09-23T14:30:00.123456+00:00",
      "event": "invoice.approved",
      "data": {
        "invoice_id": "xxx-xxx-xxx",
        "vendor_name": "Acme Supplies Ltd",
        "grand_total": 11800.00,
        "currency": "INR",
        "status": "PAID"
      }
    }

Verify karo:
  [PASS/FAIL] event field mein sahi event type hai
  [PASS/FAIL] event_id UUIDv4 format mein hai
  [PASS/FAIL] occurred_at ISO timestamp hai with timezone
  [PASS/FAIL] X-Webhook-Signature header present hai
  [PASS/FAIL] X-Webhook-Signature-V2 present hai (V1 se alag!)
  [PASS/FAIL] X-Webhook-Timestamp present hai

---

### TEST W-3: Webhook Signature Verify Karo
Yeh kya karta hai: Ensure karo ki signature hamare server se aayi hai

Python verification code:
  import hmac
  import hashlib

  received_body = '{"event_id":"xxx","occurred_at":"...","event":"invoice.approved","data":{...}}'
  received_signature_v2 = "abcdef1234..."   # X-Webhook-Signature-V2 header
  received_timestamp = "1727087400"         # X-Webhook-Timestamp header
  webhook_secret = "whsec_xxxxxxxxxxxxxxxx" # Settings se mila tha

  sign_input = f"{received_timestamp}.{received_body}".encode("utf-8")
  expected = hmac.new(
      webhook_secret.encode("utf-8"), sign_input, hashlib.sha256
  ).hexdigest()

  if expected == received_signature_v2:
      print("VALID - Request genuine hai")
  else:
      print("INVALID - Request reject karo")

---

### TEST W-4: Saare Webhooks List Karo

  Method:  GET
  URL:     {{base_url}}/api/v1/webhooks
  Headers: Authorization: Bearer {{api_key}}

---

### TEST W-5: Webhook Delivery Logs Dekho
Yeh kya karta hai: Webhook deliver hua ya fail — history dekhna

  Method:  GET
  URL:     {{base_url}}/api/v1/webhooks/{{webhook_id}}/deliveries
  Headers: Authorization: Bearer {{api_key}}

Expected Response:
  [
    {
      "event_type": "invoice.approved",
      "target_url": "https://webhook.site/...",
      "http_status": 200,
      "delivered_at": "2026-09-23T14:30:05Z",
      "attempt": 1
    }
  ]

Agar delivery fail ho: System 3 attempts karta hai (1s, 2s backoff)
Log mein http_status: 0 ya 5xx dikhega

---

### TEST W-6: Webhook Update Karo

  Method:   PUT
  URL:      {{base_url}}/api/v1/webhooks/{{webhook_id}}
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "target_url": "https://webhook.site/your-unique-id",
      "subscribed_events": ["invoice.approved"],
      "is_active": false
    }

is_active: false karne pe — webhook disable ho jaata hai

---

### TEST W-7: Webhook Delete Karo

  Method:  DELETE
  URL:     {{base_url}}/api/v1/webhooks/{{webhook_id}}
  Headers: Authorization: Bearer {{api_key}}

Expected: 204 No Content

---

## PART 5 — OUTBOUND INVOICE APIs

### TEST OB-1: Outbound Invoice Upload Karo
Yeh kya karta hai: Jo invoices aap BHEJTE ho (client ko) unhe system mein daalna

  Method:   POST
  URL:      {{base_url}}/api/v1/outbound-invoices/upload
  Headers:  Authorization: Bearer {{api_key}}
  Body:     form-data
            Key: files   Type: File   Value: [outbound PDF]

---

### TEST OB-2: Outbound Invoice Confirm Send Karo

  Method:   PUT
  URL:      {{base_url}}/api/v1/outbound-invoices/{{invoice_id}}/confirm-send
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "notes": "Sent via email on 23-Sep-2026"
    }

Webhook Trigger: outbound_invoice.sent event

---

### TEST OB-3: Outbound Invoice Mark Paid Karo

  Method:   PUT
  URL:      {{base_url}}/api/v1/outbound-invoices/{{invoice_id}}/mark-paid
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "notes": "Payment received via NEFT"
    }

Webhook Trigger: outbound_invoice.approved event

---

## PART 6 — SETTINGS APIs

### TEST S-1: API Key Rotate Karo (Admin Only)
Yeh kya karta hai: Purani key invalidate karke nayi generate karna

  Method:   POST
  URL:      {{base_url}}/api/v1/settings/security/api-key/rotate
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:     {}

Expected Response:
  {
    "api_key": "inv_live_NEW_KEY_HERE_COPY_NOW",
    "key_prefix": "inv_live_abc2...",
    "rotated_at": "2026-09-23T15:00:00"
  }

WARNING: Yeh key sirf ek baar dikhti hai! Immediately copy karo.
Postman Tests tab mein:
  pm.environment.set("api_key", pm.response.json().api_key);

---

### TEST S-2: Workflow Settings Dekho

  Method:  GET
  URL:     {{base_url}}/api/v1/settings/workflow
  Headers: Authorization: Bearer {{api_key}}

---

### TEST S-3: Vendor Flow Settings Dekho

  Method:  GET
  URL:     {{base_url}}/api/v1/settings/vendor-flow
  Headers: Authorization: Bearer {{api_key}}

---

## PART 7 — ADMIN APIs (Admin Only)

### TEST AD-1: Saare Users List Karo

  Method:  GET
  URL:     {{base_url}}/api/v1/admin/users
  Headers: Authorization: Bearer {{api_key}}

Expected:
  [
    {
      "user_id": "xxx",
      "email": "user@company.com",
      "role": "Auditor",
      "can_load": false,
      "can_audit": true,
      "can_train": false
    }
  ]

---

### TEST AD-2: User Permissions Update Karo

  Method:   PUT
  URL:      {{base_url}}/api/v1/admin/users/{user_id}/permissions
  Headers:  Authorization: Bearer {{api_key}}
            Content-Type: application/json
  Body:
    {
      "can_load": true,
      "can_audit": true,
      "can_train": false
    }

---

## PART 8 — INGESTION HISTORY APIs

### TEST H-1: Ingestion History Dekho

  Method:  GET
  URL:     {{base_url}}/api/v1/ingestion-history
  Headers: Authorization: Bearer {{api_key}}

Optional: ?page=1&page_size=20

---

## PART 9 — COMPLETE END-TO-END TEST SCENARIO

Yeh complete business scenario hai — ek invoice upload se payment tak ka full flow (18 steps, ~25 minutes):

=== Phase 1: Setup (5 minutes) ===

  Step 1: Webhook.site kholo -> URL copy karo
  Step 2: Postman mein environment variables set karo (base_url, api_key)
  Step 3: TEST A-1 run karo -> 200 OK aana chahiye (key valid hai)
  Step 4: TEST W-1 run karo -> webhook register karo with webhook.site URL

=== Phase 2: Invoice Lifecycle (10 minutes) ===

  Step 5: TEST I-1 -> PDF upload karo -> invoice_id aur job_id save karo
  Step 6: TEST I-2 -> 2-3 baar run karo jab tak COMPLETED/AUDIT_REQUIRED na ho
  Step 7: TEST I-4 -> Invoice details dekho — vendor, amount, currency verify karo
  Step 8: TEST AU-3 -> Ek correction save karo (vendor name ya amount fix karo)

=== Phase 3: Webhook Verification (5 minutes) ===

  Step 9:  TEST AU-1 -> Invoice approve karo (status: PAID)
  Step 10: Webhook.site mein dekho -> invoice.approved POST aana chahiye (10 sec mein)
  Step 11: Headers verify karo:
           X-Webhook-Signature     -> present?           [PASS/FAIL]
           X-Webhook-Signature-V2  -> present, V1 se different?  [PASS/FAIL]
           X-Webhook-Timestamp     -> present?           [PASS/FAIL]
  Step 12: Body verify karo:
           event = "invoice.approved"     [PASS/FAIL]
           data.status = "PAID"           [PASS/FAIL]
           data.vendor_name = sahi name   [PASS/FAIL]
           data.grand_total = sahi amount [PASS/FAIL]

=== Phase 4: Error Scenarios (5 minutes) ===

  Step 13: TEST AU-1 dobara same invoice pe -> 400 Expected ("already PAID")
  Step 14: TEST AU-4 -> Invoice reopen karo -> AUDIT_REQUIRED
           Webhook.site mein -> "invoice.reopened" aana chahiye [PASS/FAIL]
  Step 15: TEST AU-2 -> Invoice reject karo
           Webhook.site mein -> "invoice.rejected" aana chahiye [PASS/FAIL]
  Step 16: TEST W-5 -> Delivery logs dekho -> 3 events show honge

=== Phase 5: Rate Limit Test (Optional) ===

  Step 17: Postman Collection Runner mein TEST AU-1 ko 65 iterations mein run karo
  Step 18: 61st call pe expect karo:
           HTTP Status: 429 Too Many Requests
           Body: "Rate limit exceeded: maximum 60 resolve operations per minute per tenant."

---

## COMMON ERRORS & SOLUTIONS

| Error Code | Message                | Cause                    | Solution                       |
|------------|------------------------|--------------------------|--------------------------------|
| 401        | Invalid API key        | Key galat ya expired     | Security page pe rotate karo   |
| 403        | Only Admin can...      | Role mismatch            | Admin key use karo             |
| 404        | Invoice not found      | Galat invoice_id         | List se sahi ID check karo     |
| 409        | Duplicate file         | Same PDF pehle upload    | Nayi file use karo             |
| 422        | Validation error       | Body format galat        | JSON structure check karo      |
| 429        | Rate limit exceeded    | 60+ calls/minute         | 1 minute wait karo             |
| 402        | Free tier limit        | Monthly limit khatam     | Billing check karo             |

---

## QUICK REFERENCE CARD

BASE URL : https://invoicellm.admsofttech.com
API KEY  : inv_live_xxxx... (Settings -> Security page se)

KEY ENDPOINTS:
  GET    /api/v1/settings/security/api-key/verify  -> Key identity check
  GET    /api/v1/auth/me                           -> User info
  POST   /api/v1/invoices/upload                   -> PDF upload
  GET    /api/v1/invoices                          -> All invoices list
  GET    /api/v1/invoices/{id}                     -> Single invoice
  GET    /api/v1/invoices/{id}/pdf                 -> PDF download
  DELETE /api/v1/invoices/{id}                     -> Delete invoice
  PUT    /api/v1/audit/resolve/{id}                -> Approve/Reject/Reopen
  GET    /api/v1/audit-history/{id}                -> Change history (Admin)
  GET    /api/v1/webhooks                          -> List webhooks
  POST   /api/v1/webhooks                          -> Create webhook
  PUT    /api/v1/webhooks/{id}                     -> Update webhook
  GET    /api/v1/webhooks/{id}/deliveries          -> Delivery logs
  DELETE /api/v1/webhooks/{id}                     -> Delete webhook
  POST   /api/v1/outbound-invoices/upload          -> Outbound upload
  PUT    /api/v1/outbound-invoices/{id}/mark-paid  -> Outbound mark paid
  GET    /api/v1/admin/users                       -> List users (Admin)
  PUT    /api/v1/admin/users/{id}/permissions      -> Update permissions (Admin)
  GET    /api/v1/ingestion-history                 -> Ingestion log
  POST   /api/v1/settings/security/api-key/rotate  -> Rotate API key (Admin)

WEBHOOK EVENTS:
  invoice.received          -> Naya invoice aaya
  invoice.approved          -> PAID hua
  invoice.rejected          -> REJECTED hua
  invoice.reopened          -> Wapas review mein aaya
  invoice.requires_action   -> AI ne issue pakda
  outbound_invoice.sent     -> Bheja gaya
  outbound_invoice.approved -> Payment mili

RATE LIMITS:
  Audit resolve: 60 per minute per tenant

WEBHOOK HEADERS TO VERIFY:
  X-Webhook-Signature     (V1 - body only HMAC)
  X-Webhook-Signature-V2  (V2 - timestamp+body HMAC — yeh use karo)
  X-Webhook-Timestamp     (Unix seconds)
  X-InvoiceEQ-Event-Id    (UUIDv4)

ROLES & PERMISSIONS:
  Admin   -> can_load + can_audit + can_train (sab kuch)
  Auditor -> can_audit only (approve/reject, upload nahi kar sakta)
  Trainer -> can_train only (rules update, upload/approve nahi)

---
Guide banaya gaya: live codebase analysis, master branch @ 2c343ec
Tools: Postman (free) + Webhook.site (free)
