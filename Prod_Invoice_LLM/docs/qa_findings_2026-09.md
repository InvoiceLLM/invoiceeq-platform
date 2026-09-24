# QA findings — the 2026-09 business-scenario run

**Opened:** 2026-09-21 · **Status:** live, appended as the run continues
**Where the testing happens:** Azure dev (`rg-invoice-llm-dev`), real AI, through the public website container
**Code under test:** `master` @ `f633b25`

## What this file is, and what it is not

This is the **holding pen** between "something looked wrong during a test" and "a gap was filed, fixed and closed". Nothing here is a tracker entry yet.

The rule we are working to:

1. A test run produces an **observation**. It lands here with its evidence.
2. The observation is **verified** — read against the code, reproduced, or shown to be a bad test premise rather than a product defect.
3. Only when we decide to **fix** it does it become a numbered gap in `apps/invoice-be/docs/be_features_tracker.md` or `apps/invoice-fe/docs/fe_features_tracker.md`, in those files' own format, with the fix and its evidence.

Keeping it in two steps is deliberate. The trackers are a record of **closed work** — every entry there is `[x]`, with a fix and evidence behind it. Ten half-diagnosed observations dropped into them would destroy that meaning. So they wait here until they have earned their place.

**Gap numbers, for when these graduate:** BE is at **719**, FE is at **708**. Numbers are unique *per tracker*, never across them — always write "BE Gap N" or "FE Gap N", never a bare "Gap N".

## Status legend

| Mark | Meaning |
|---|---|
| **CONFIRMED** | Reproduced, and the cause is read in the code — ready to become a gap |
| **OPEN** | Observed and credible, but one piece of evidence is still missing |
| **NOT A DEFECT** | Looked wrong; turned out to be correct behaviour or a bad test premise |
| **ENV** | Real, but it is configuration or infrastructure, not product code |

---

## F-01 — an invoice can finish with no total, and nothing says so · CONFIRMED · BE

**What happened.** A document reached a terminal state with `grand_total` empty. No alert was raised, and the invoice was not routed to review.

**Why it matters.** `grand_total` is the number a payment decision is made on. Every other money check in the product exists to stop a *wrong* total reaching a human — but a *missing* total walks straight through, and the screen shows a finished invoice with a blank where the amount should be. Silence is the worst possible answer here: a wrong number gets argued about, a missing one gets assumed.

**Evidence — `apps/invoice-be/utils/verification_tools.py`:**

```
208:    if grand_total is None or subtotal is None:
437:    if grand_total is None or not ocr_text:
```

Both checks `return` early when the total is absent. The arithmetic verification and the source-text verification each decline to run, and neither leaves anything behind saying it declined.

**Proposed resolution.** Treat the absence as a finding in its own right: when `grand_total` is `None` after extraction, raise an alert (`grand_total_missing`) and route to `AUDIT_REQUIRED` instead of returning quietly. The two early returns stay — they are right not to do arithmetic on a `None` — but the caller needs to learn that the check never ran.

**Open question for the founder.** Should a missing total *block* completion, or alert and route to review? Every other money finding in this product alerts rather than blocks (BE Gap 535's ruling). Consistency says alert.

---

## F-02 — the resolve decision log writes no fields · CONFIRMED · BE

**What happened.** Every audit decision emits one INFO line reading exactly `Invoice resolved` and nothing else. The whole point of that line was to carry who decided what.

**Why it matters.** BE Gap 562 was closed on the promise that "the resolve rate and its actors can be read off the log stream without joining audit_logs". That promise is not kept in the deployed build. Anyone building an ops dashboard on this line gets a counter of decisions and no idea who made them.

**Evidence — the two ends do not agree.**

`apps/invoice-be/routers/audit.py:753` passes the fields **flat**:

```python
logger.info(
    "Invoice resolved",
    extra={
        "invoice_id": str(invoice.id),
        "actor_user_id": ...,
        "old_status": current_status,
        "new_status": target_status,
        ...
    },
)
```

`apps/invoice-be/utils/logging_config.py:113` only ever reads a **nested** key:

```python
if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
    log_obj.update(record.extra_fields)
```

There is no `record.extra_fields` on that record, so nothing is merged and every field is dropped. The same file at lines 167 and 181 uses the nested shape correctly — so the convention exists, and this one call site missed it.

**Live confirmation.** Log Analytics, 2026-09-21, six resolve decisions on invoice `ebf9db76`: every line is the bare string `Invoice resolved`.

**Proposed resolution.** A one-line fix at the call site — `extra={"extra_fields": {...}}` — matching the shape the formatter and the rest of the file already use. Worth a test that asserts the emitted JSON actually contains `invoice_id`, because the current code passes review by eye.

---

## F-03 — one telemetry line carries an empty tenant id · OPEN · BE

**What happened.** During the injection test (BE Gap 672, fenced document text) the telemetry line was emitted with an empty tenant id.

**Why it matters.** A security-relevant event that cannot be attributed to a tenant is close to useless in an incident.

**Still needed.** The exact emitting call site, and whether the tenant id is genuinely unavailable at that point or simply not threaded through. Re-run the injection document and capture the raw line before this is written up.

---

## F-04 — the DI-confidence rule flags COMPLEX more often than the path it replaced · OPEN · BE

**What happened.** BE Gap 682's routing sends *more* documents to COMPLEX than the behaviour it replaced, because of the Document-Intelligence confidence rule it added.

**Why it matters.** COMPLEX is the expensive path. If the rule over-fires, every tenant pays for it on documents that did not need it — and the gap was sold as better routing, not more routing.

**Still needed.** A counted before/after on the same document set. "More" is an impression until there is a number; this one is not fileable without it.

---

## F-05 — a FAILED invoice blocks its own re-upload as a duplicate · CONFIRMED · BE

**What happened.** A document failed processing. Re-uploading the same file — the obvious thing anyone would do — was refused as `DUPLICATE`.

**Why it matters.** This is a dead end with no way out from the UI. The failure was ours (a 429, an OCR timeout), the user's fix is to try again, and the product says no. The duplicate guard exists to stop paying a bill twice; a `FAILED` row is not a bill that was paid.

**Proposed resolution.** Exclude terminal-failure rows (`FAILED`, `EXTRACT_FAILED`) from the duplicate match, or offer an explicit "retry this document" action that reuses the existing row instead of creating a second one.

---

## F-06 — `.env.example` and the setup docs name Azure AI resources that do not exist · CONFIRMED · BE / docs

**What happened.** A fresh clone configured from the committed example cannot do OCR. The endpoints named are for resources that are gone, and the keys are stale.

**Why it matters.** Every upload fails at OCR, and the error does not point at configuration — so the next person loses hours on it. We lost hours on it.

**Evidence.** Every local upload failed at OCR until `AZURE_DOC_INTEL_ENDPOINT`, `AZURE_DOC_INTEL_KEY`, `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` were repointed at the live resources.

**Proposed resolution.** Correct the example to the current resource names, with placeholders for the secrets, and say in the setup doc where the real values come from. No secret belongs in the committed file.

---

## F-07 — dev hits an Azure OpenAI rate limit and the document ends FAILED · ENV

**What happened.** `gpt-5.6-luna` returned 429 on the dev deployment; the document finished `EXTRACT_FAILED`.

**Assessment.** The handling is correct — it retried, then failed honestly with a reason, which is exactly what BE Gap 683 asks for. The quota is the problem, not the code.

**Action.** Raise the dev deployment's quota, or accept that batch runs on dev will lose documents to 429 and plan the test runs around it. Not a gap.

---

## F-08 — the `"fail"` / `"audit"` filename shims are gone · NOT A DEFECT

**What happened.** The QA runner's pre-flight and its `s4-*` checks assume that uploading a file with `fail` or `audit` in its name forces that outcome.

**Assessment.** Those shims **no longer exist in the source.** Grepping `queue_worker/` and `services/` on `f633b25` finds them only inside a stale `__pycache__/handlers.cpython-314.pyc`. Separately, `services/storage.py:56` builds the blob name from the tenant and invoice ids — the uploaded filename never reaches the worker's path at all, so the shim could not have fired from the upload door even while it existed.

**Action.** The checks that depend on it are testing something that is not there. Rewrite them to force the outcome a supported way, or drop them. **Do not record them as product failures.** Worth deleting the stale `.pyc` too, so the next person grepping does not find a ghost.

---

## F-09 — the stale-tab refusal is shown far from the button that caused it · CONFIRMED · FE · low severity

**What happened.** Two tabs open on the same invoice, both showing `AUDIT_REQUIRED`. Approve in tab A. Then Reject in tab B: the button responds, nothing changes, and **no message appears on screen**. Clicked three times.

**The backend is right.** Log Analytics, invoice `ebf9db76`:

```
11:41:44  PUT /api/v1/audit/resolve/ebf9db76...  400 Bad Request
11:42:00  PUT /api/v1/audit/resolve/ebf9db76...  400 Bad Request
11:42:24  PUT /api/v1/audit/resolve/ebf9db76...  400 Bad Request
```

`routers/audit.py:625` (BE Gap 529) refuses a direct PAID → REJECTED flip with `Cannot change a PAID invoice to 'REJECTED' directly — reopen it first (Admin-only).` The status stayed PAID and tab B dispatched no webhook. **The money decision held.** That half is a pass.

**Why the silence matters anyway.** An auditor pressing a button that does nothing concludes the system is stuck, and keeps pressing. What they are never told is the one thing that would end the confusion: *somebody else already decided this*. A correct refusal that nobody can see is the worst place for a correct refusal to be.

**The message is not swallowed — it is out of view.** Re-run on 2026-09-21 with the side panel scrolled to its bottom: the banner is there, reading exactly

> ⚠ Not saved — Cannot change a PAID invoice to 'REJECTED' directly — reopen it first (Admin-only).

`app/invoices/review/[id]/page.tsx:573-576` catches the error and calls `setSaveError(correctionErrorMessage(err))`; `lib/correctionResponse.ts:66-68` passes the backend's `detail` through unchanged rather than flattening it to something generic. That chain works, and the wording it produces is good — it names the state and the way out.

**What is actually wrong, then.** The banner draws at the **bottom of the side panel**, just above the pinned corrections footer (line 968), while Approve and Reject sit in the **page header**. Press a button at the top, and the answer appears off-screen at the bottom of a different column. The tester clicked three times before finding it, and only found it when told where to look — which is the whole finding.

This is not a correctness bug and should not be filed as one. It is placement: a refusal has to appear where the eye already is. The app has a related history here (FE Gap 704, the scrollbar that was invisible at 6% contrast), so "the content was technically on the page" is a failure mode this codebase has seen before.

**Proposed resolution.** Put the failed-action feedback next to the action — a toast, or an inline message in the header action row — rather than relying on the reader finding a panel-footer banner. The existing banner can stay for correction-save errors raised *inside* that panel, where it is next to its own cause.

---

## F-10 — `invoice.reopened` cannot be subscribed to from the app · CONFIRMED · FE

**What happened.** Reopening an invoice delivered no webhook. The event is not in the subscription picker, so it could never have been ticked.

**This is not a backend bug.** `routers/webhooks.py:22-33` lists **ten** allowed event types, `invoice.reopened` among them, and `routers/audit.py:829` dispatches it on a PAID/REJECTED → AUDIT_REQUIRED transition. That is BE Gap 558, and it works. The dispatcher then drops it at `services/webhooks.py:404-405`:

```python
for sub in subscriptions:
    if event_type not in (sub.subscribed_events or []):
        continue
```

— correctly, because the subscription never listed it. The skip is silent by design, which is why nothing appeared in the logs either.

**Where it breaks.** `apps/invoice-fe/app/settings/webhooks/page.tsx:48-58` offers **nine** events. The one missing is exactly `invoice.reopened`. The help page (`app/help/content/webhooks-guide.tsx`) does not mention it either.

**Why it matters.** `invoice.reopened` is the event that tells a subscriber an earlier `invoice.approved` or `invoice.rejected` was undone. Without it, an integration that pays on approval is never told the approval was withdrawn — it holds a decision the business has already reversed. Backend work that shipped and closed is unreachable to every customer, and nothing about that is visible from either side.

**Proposed resolution.** Add the tenth entry to `ALLOWED_EVENTS` with a label and description in the style of the other nine, and list it in the webhooks help page. Worth a test that asserts the FE list and the BE `ALLOWED_EVENT_TYPES` are the same set, because this drifted once and will drift again.

---

## F-11 — a rejection can be categorised but not explained · CONFIRMED · FE

**What happened.** The Reject dialog offers a dropdown of nine fixed categories and **nothing else** — no free-text field. The nearest option to a real rejection ("this is a duplicate of the bill we already paid against PO-9921") is `Business Logic Error (Duplicate / Invalid business vendor)`.

**Evidence.** `app/invoices/review/[id]/page.tsx:1314-1331` is the whole form: one `<select>` with nine `<option>`s, then Cancel and Confirm Rejection. `rejectReason` is seeded to `"Invoice Error"` at line 306 and sent as-is at line 551. The backend takes `reject_reason` as a free string — the restriction is the app's alone.

**Why it matters.** That string is not only a metric. It travels to the webhook subscriber (BE Gap 558 puts the reason in the payload) and it is what the audit history shows a reader months later: `Reason: {entry.reject_reason}` — `components/audit/ChangeHistoryPanel.tsx:153`. A vendor asking "why was my invoice rejected?" gets answered with `Business Logic Error`, which names a category of mistake rather than the mistake. The one fact that would settle it — *which* bill it duplicates — has nowhere to live.

The dialog's own subtitle says the reason is "to help track AI performance metrics", and for that purpose a closed list is right: free text cannot be counted. So this is not a case of the dropdown being wrong. It is that one field is being asked to do two jobs — a countable category, and an explanation a human will read — and only the first is served.

**Proposed resolution.** Keep the dropdown for metrics, add an optional note beside it, and carry both: the category stays countable, the note reaches the webhook payload and the change history. Nine categories cannot be extended into an explanation; a second field costs almost nothing.

**Note for the test plan.** BS-P4-03 and the QA runner's R3 both assume a typed reason. That premise does not match the product. Rewrite them to select a category and, once the note field exists, to check the note travels — not to type free text into a dialog that has never accepted it.

---

## F-12 — a slow rule save is reported as "Not saved" after it has already saved · CONFIRMED · FE / infra · **high**

**What happened.** Correcting the vendor name on `ACM-7731` with "apply as a standing rule" ticked returned the red banner

> Not saved — the server did not accept this change. Please try again.

The server had accepted it. The write completed.

**Evidence — dev, 2026-09-21, invoice `252a48b9-a219-4a02-bd3f-d1993d3c87e9`:**

```
16:03:49  Error: socket hang up
16:03:49  Failed to proxy .../api/audit/resolve/252a48b9-...
16:03:51  Invoice resolved
16:03:51  HTTP PUT /api/v1/audit/resolve/252a48b9-...  200 OK  (32460.77ms)
```

The backend took **32.5 seconds** — and this is not a surprise to the code. `routers/audit.py:709` says so outright:

```
# Gap 546: the safety check runs OCR + an LLM extraction (24-53s measured); on a thread so the
# event loop keeps serving other requests.
```

Somebody measured this path at **24–53 seconds** and wrote the number down. `LLM_REQUEST_TIMEOUT_SECONDS=120` was set to accommodate it. The work to keep the event loop free was done. What nobody checked was whether the layer in front would still be listening — and it gives up at about 30s, inside the range that was measured. A proxy hop in front of it gave up at roughly **30 seconds**, closed the socket, and the browser was left with nothing. Two seconds later the backend committed and answered 200 into a connection nobody was holding.

**Why the message is wrong twice over.** It is wrong on the fact — the change *was* saved. And it is wrong in what it asks for: "Please try again". A retry does not repair anything here, because nothing was broken; it writes a **second** version of a rule that already exists. Anyone following the instruction on screen converts one successful save into v5, v6, v7 — and rule history, which is the Trainer's whole safety net, fills with phantom versions nobody chose to make.

This is worse than the generic-message problem in F-09. There the app failed to show a true refusal. Here it shows a **false** one, and the recovery it recommends actively causes damage.

**Root cause, in two parts.**
1. **Timeout mismatch.** The backend is configured to spend up to 120s on this call; the proxy chain (browser → website container → `ca-invoice-fe-dev` → backend) gives up near 30s. The slowest legitimate operation in the product is longer than the patience of the layer in front of it.
2. **A dropped connection is reported as a rejection.** `lib/correctionResponse.ts:70` returns "the server did not accept this change" for anything that is not an axios error carrying a `detail`. A socket that closed before the answer arrived is not a rejection — the outcome is *unknown*, and the app states it as a definite no.

**Proposed resolution.**
- Raise the proxy timeout above the backend's own ceiling for this route, so the slowest allowed save can still be heard.
- Separate "refused" from "no answer" in the error path. A dropped connection should say the result is unconfirmed and tell the reader to **check before retrying**, never "try again" as if the write certainly did not happen.
- Better still for a call this slow: acknowledge immediately and do the rule save in the background, the way webhook delivery was moved off the request thread (BE Gap 194). A 32-second synchronous request is a timeout waiting to happen at every layer.

**Note for the test plan.** `r4-nofreeze` asks whether a rule save freezes the backend. It does not — but it does outlive the proxy in front of it, which no check currently looks for. Worth adding.

---

## F-13 — a vendor-name rule still never reaches the next invoice · CONFIRMED · BE · **BE Gap 549 is not closed**

**What happened.** On `ACM-7731`, vendor name was corrected `ACME SUPPLIES LIMITED` → `Acme Supplies Ltd` with "apply as a standing rule" ticked. The rule saved. The next invoice from that vendor, `ACM-7790`, extracted with vendor **`ACME SUPPLIES LIMITED`** — the printed name. The rule did not apply.

This is `r4-vendor` in the QA runner, whose expectation reads: *"Before the fix, a rule taught this way was saved but never found."* It is still never found.

**Evidence — dev, 2026-09-21, invoice `fa68a657-44b1-4348-8bfe-fa77c65c2cf9`:**

```
16:10:27  Matched vendor template for 'ACME SUPPLIES LIMITED' (exact match, tenant: e7c46b74-...)
16:10:27  BE Gap 683: OCR pre-detected vendor 'ACME SUPPLIES LIMITED' with 1 trained constraints.
          Merged rules upfront into single extraction pass.
16:10:33  Matched vendor template for 'ACME SUPPLIES LIMITED' (exact match, tenant: e7c46b74-...)
16:10:33  Stage 2 skipped: trained vendor rules were applied upfront in single pass (BE Gap 683).
```

Rule History at the time held **two** templates for what is one vendor:

| Template row | Active version | Rules it holds |
|---|---|---|
| `ACME SUPPLIES LIMITED` | v3 | currency → GBP |
| `Acme Supplies Ltd` | v1 | vendor name → `Acme Supplies Ltd` |

The worker matched the first row by **exact match** and loaded its **1** rule — the currency one, which is why GBP came out right. The second row, holding the rule that had just been taught, was never consulted.

**Root cause — the fix only covers the case that does not occur here.** BE Gap 549 was closed on 2026-09-15 by adding "normalized vendor name matching and vendor alias resolution via `services/vendor_master.py::resolve_vendor`" to `queue_worker/handlers.py::_get_template_rules` (the same function's docstring credits BE Gap 675 for that behaviour — both entries claim it). The code is explicit about the ordering:

```python
# queue_worker/handlers.py
617    # 1. Exact match on vendor_name
618    tpl = session.exec(stmt.where(ExtractionTemplate.vendor_name == vendor_name)).first()
619    if tpl and isinstance(tpl.rules, dict):
620        logger.info("Matched vendor template for '%s' (exact match, tenant: %s)", ...)
621        return list(tpl.rules.get("constraints", []) or [])
622
623    # 2. Normalized vendor name, then confirmed vendor_master alias (BE Gap 675)
```

Step 2 is unreachable whenever step 1 hits. Here step 1 hits — a template exists under the printed name, because the earlier currency corrections created one — so normalization and alias resolution never run, and the freshly taught rule is invisible. The log line at 16:10:27 says `exact match` for precisely this reason.

**The matching itself is not the problem — it already works.** `services/vendor_master.py::normalise_vendor_name` strips legal suffixes, and both spellings collapse to the same key:

```
normalise_vendor_name('ACME SUPPLIES LIMITED')  ->  'acme supplies'
normalise_vendor_name('Acme Supplies Ltd')      ->  'acme supplies'
match: True
```

So step 2 would have found the rule. It never got the chance. **A stale template under the printed name shadows the correct one**, and the shadowing row is the one that wins purely because it is checked first.

That is what makes the bug so easy to miss: every piece of it works. The rule saves. The names normalise. The lookup matches. Only the *order* is wrong, and only when a second template happens to exist.

Note what this means about when the bug appears: a vendor-name rule works **only** for a vendor who has no other rules. Teach a vendor anything else first — a currency, a tax tolerance — and the vendor-name rule you teach afterwards silently stops working. The more a tenant uses the Trainer, the less the Trainer works. A first-time trial would look perfect; a real tenant's second month would not.

**This also narrows the fix.** Neither proposed option below needs new matching logic — the resolution already exists and is correct. What is missing is that `_get_template_rules` treats "a row keyed by this exact string" as authoritative, when the thing it is actually looking for is "the rows belonging to this vendor", and a vendor can hold more than one key.

The storage side is unchanged and still stores a vendor-name rule under the name it **produces**, not the name it **matches**. A rule whose entire job is "when you see X, write Y" is filed under Y and looked up by X. Nothing can find it except the fallback, and the fallback is skipped whenever any template already exists under X.

Worth stating plainly: this is the **exact failure the gap describes**, still reproducible on `master` @ `f633b25`, six days after it was marked closed. The fix addressed the empty-slot case and the test that covered it (`test_extraction.py`) presumably sets up no template under the misread name — which is why it passes while the product does not.

**Why it matters.** Teaching a vendor's name is the single most likely thing an auditor will teach, because a misread vendor name is the most visible extraction error. They are shown a success, a rule version is written, the rule appears in the Trainer — and every future invoice ignores it. Nothing in the product ever tells them. They will teach it again, and again.

Note also that the two rows cannot both win: the unique constraint is `(tenant_id, vendor_name, flow_direction)`, and the lookup takes one row. Correcting a vendor name **splits that vendor's rules across two templates**, and whichever one the printed name matches is the only one that applies. Rules taught before the rename keep working; rules taught after it do not.

**Proposed resolution.** Two candidates, and the choice is a design decision:
- **Look up by alias first, not as a fallback** — resolve the extracted name through `resolve_vendor` *before* the exact match, so a rename is honoured even when a stale template exists under the old name. Also merges the split, because both names resolve to one vendor.
- **Store the vendor-name rule under the matched name** (the one on the paper), since that is the key it will be looked up by, and let the rule carry the output value. This keeps one template per printed vendor and removes the split entirely.

Either way, a regression test must set up a template under the **misread** name before teaching the rule — the condition this bug needs and the current test does not create.

---

## F-14 — Admin change history never leaves the website tier · CONFIRMED · FE / infra · **high**

**What happened.** Expanding **CHANGE HISTORY (Admin)** on an invoice shows

> Could not load the change history. Please try again.

It fails for every invoice, for every Admin, every time.

**Evidence.** Three hours of dev logs contain **zero** requests to `/audit-history` — searched by substring, not token, so nothing was missed. The backend never heard of it. Neither did `ca-invoice-fe-dev`.

Both ends are healthy and deployed:
- Backend route exists — `routers/audit_history.py:24`, mounted at `main.py:189`.
- FE proxy route exists — `app/api/audit-history/[id]/route.ts`.
- Both landed in `a4f83fb` (2026-09-15), and the deployed FE image `bcd0167` (built 2026-09-21 12:20 UTC) has that commit as an ancestor.

The request dies one tier earlier. `apps/invoice-website/next.config.js:99` holds a hand-maintained allowlist of the API prefixes the public site forwards to `invoice-fe`:

```js
const feApiPrefixes = ["admin", "atlas", "audit", "auth", "autopilot", "chat", "connectors",
  "dashboard", "docs", "email", "ingestion-history", "invoices", "outbound-audit",
  "outbound-dashboard", "outbound-invoices", "settings", "support", "trainer", "webhooks"];
```

`audit-history` is not in it. Note `audit` is present, but the rewrite is `/api/${p}/:path*` — a prefix match on the path segment, so `audit` does not cover `audit-history`. With no rule, the website serves its own 404 and the call never leaves the public tier.

**This was considered and decided wrongly.** The comment immediately above the array (lines 97-98) reads:

> Still deliberately absent — "billing" (shadows invoice-website's own app/api/billing/), "documents", "config", **"audit-history" (no page served through this proxy calls them)**

A page served through this proxy does call it. `ChangeHistoryPanel` is rendered on the invoice review screen, and `invoices` is in the proxied page list. The array was re-diffed against `invoice-fe/app/api/` on 2026-09-19 — 22 folders counted — and this entry survived the review on a premise that was false.

**Why it matters.** `ca-invoice-fe-dev` is internal-only; the website is the sole public entry. So this is not "broken on one origin" — it is broken for everyone, with no route that works. And what is lost is the audit trail: who changed what, when, and from what value. That is the record you reach for exactly when something has gone wrong and someone is asking who did it.

The file's own comments describe this failure mode twice — FE Gap 469 and FE Gap 705 were both this same missing-prefix bug — and name the symptom precisely: *"the screen renders, the data never arrives, and it reads as 'the feature is broken' rather than 'the request never left this tier'."* It has now happened a third time.

**It is not the only one.** The same comment excludes `"documents"` on the same reasoning, and that is wrong too: `components/atlas/ReconPanel.tsx:74` calls `GET /documents` to build its statement-reconciliation picker, and it renders on `/work`, which **is** in the proxied page list. So the ATLAS reconciliation picker has the same defect — it will come up empty on the only origin users can reach. Found while looking for somewhere to view non-invoice documents; not separately reproduced in the browser, but the call site and the missing prefix are both in the code.

**Proposed resolution.** Add `"audit-history"` and `"documents"` to `feApiPrefixes`. Then stop relying on a hand-kept list that has silently drifted three times: the same file (line 25) already proposes a CI check diffing `invoice-fe/app/api/*` against this array, and notes it "is not done here". Three occurrences is the argument for doing it.

**Note for the test plan.** `r5-send` and `r5-paid` both verify their result by reading the change history. They will fail on this, not on anything wrong with outbound send or mark-paid. Fix this first or those results mean nothing.

---

## Passed on the way — worth recording

These were tested in the same run and held. They are here so the file reads as a record of the run, not only of its failures.

| What was tested | Result |
|---|---|
| Webhook envelope (BE Gap 555) | `event_id` UUIDv4 + `occurred_at` ISO with timezone, matching `build_delivery_body()` |
| Signature headers (BE Gap 564) | V1 and V2 both present and **different**, `X-Webhook-Timestamp` equals `occurred_at` to the second — so V2 really is signed over timestamp + body |
| One delivery per real change | Two approvals, two deliveries, each one task → one POST → 200 → deleted from the queue. No duplicates, no retries |
| Currency on the wire (BE Gap 215) | `currency` present in the payload; a figure never travels bare |
| Secret at rest (BE Gap 564) | `routers/webhooks.py` encrypts through `encrypt_token()` and refuses with 503 if encryption fails — read from code; the column itself was not read |
| Delivery off the request thread (BE Gap 194) | Dispatch ran on `ca-queue-worker-dev`, not the thread that committed the invoice |
| Stale-tab guard, backend half (BE Gap 529) | Three attempts, three 400s, status unchanged, no webhook |
| Rejection reason on the wire (BE Gap 558) | `invoice.rejected` carried `reject_reason: 'Business Logic Error'` alongside status, vendor, total and currency. The plumbing is there — F-11's note field would travel the same path, needing no new wiring |
| Reopen fires nothing when unsubscribed | 12:07:27 reopen produced no delivery, 12:08:21 rejection produced exactly one. The event filter discriminates correctly (see F-10 for why `invoice.reopened` could not be subscribed to at all) |
| Correcting figures — the whole R1 block (BE Gaps 530-535, FE 499) | **8 of 8 passed** on `INV-44821`. `$646.92` stored as `646.92` and the box read back the *stored* value; `1.250,50` refused by name; `nan` refused as "not a finite number" rather than crashing; vendor name could not be emptied, due date could; currency `USD → EUR` stuck. Five of these are the places software usually lies quietly — a bad format swallowed, a NaN crash, a required field emptied, a "saved" that saved nothing |
| A correction that breaks the arithmetic (BE Gap 535) | Grand total `700.00` raised `Subtotal (599.00) + Tax (47.92) does not match Grand Total (700.00)` — the alert prints all three figures instead of saying "mismatch", so the auditor sees where the gap is. Approval was **not** blocked, which is the founder ruling. *Minor:* the alert points at `tax_amount` when the field just edited was `grand_total`; arithmetic cannot tell which is wrong, but it reads as misdirection |
| Variable fields cannot become rules (BE Gap 542) | A `grand_total` correction with the rule box ticked applied to that invoice only, with the reason stated. `utils/rule_schema.py:108-117` also excludes invoice number, dates, PO number, subtotal, tax amount and items |
| Stale-tab refusal wording (FE) | The backend's `detail` reaches the screen intact — it names the state and the way out, not a generic "something went wrong". Only its placement is wrong (F-09) |

---

## Not yet filed, tracked elsewhere

- Day 2–4 of the automated scenario harness (`apps/invoice-be/tests/scenarios/`)
- The CI job that sets `TEST_DATABASE_URL` — closing BE Gap 685
- BE Gaps 673, 674, 684, 685, 686 — still open from `6ff79db`
- The repeat-approve check (BE Gap 554): **unreachable from the UI**, because the app hides Approve once an invoice is PAID. It belongs in the automated API suite, not in the manual runner — an API key can still make that call.
