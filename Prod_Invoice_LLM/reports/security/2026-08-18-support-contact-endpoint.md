# Security Review: `POST /api/v1/support/contact` (unauthenticated support-contact endpoint)

**Branch reviewed:** `feature/contact-us-and-support-tickets` @ `fc48ef0` (unmerged, worktree `contact-us-verify`)
**Scope:** Auth/rate-limiting, injection, tenant isolation, secrets handling — for the new public contact-form endpoint and its handler chain (`routers/support.py`, `agents/support_agent.py`, `services/support_email.py`). Read-only assessment; nothing modified or executed.
**Note on sequencing:** this repo's normal priority order is coding → functional testing → dev/prod env split → load test → security test. This review is a user-approved scoped exception for this one endpoint ahead of that order, prompted by a merge-readiness review flagging it — not a general security pass.

## Findings

### 1. No rate limiting anywhere in the request path — CONFIRMED
Repo-wide grep for `slowapi|limiter|throttl|rate.?limit|captcha` in `invoice-be` returns nothing outside an unrelated queue-worker fair-share throttle. `main.py:33-39` mounts only `CORSMiddleware`. `routers/support.py:218-221`'s `submit_contact_inquiry` depends on `get_db_session` alone — no limiter dependency. Both sides of the stack claim otherwise: `docs/feature_19_support_tickets_and_notifications.md:62` says "Public rate-limited endpoint," and the website proxy at `apps/invoice-website/app/api/contact/route.ts:20-22` says "Rate-limiting / abuse prevention is handled entirely by the backend." Neither implements it.

### 2. Open email relay with unescaped attacker-controlled HTML — CONFIRMED, highest severity
`services/support_email.py:282-287` sends the receipt email to `ticket.user_email`, which is just the request body's `email` field — fully attacker-controlled destination. `_receipt_html` (line 183) interpolates `ticket.user_name` (= request body's `name`) directly into the HTML template with no escaping.

**Failure scenario:** POST to `/api/v1/support/contact` with
```json
{"name": "</p><a href=\"https://evil.tld\">Your Invoice AI password expired - reset now</a><p>", "email": "victim@target.com", "message": "x"}
```
SendGrid delivers attacker-authored phishing HTML to any address the attacker names, `From: invoices@invoiceeq.app` — SPF/DKIM-passing on the platform's own authenticated sending domain. The only length constraint is the `VARCHAR(255)` column (`models.py:639`), not a validator, and 255 chars is ample for an anchor tag. Blast radius: sender-reputation damage and potential SendGrid account suspension, which would also take down real invoice delivery (shared `services/outbound_email.py`).

### 3. HTML injection into the internal staff alert — CONFIRMED
Unescaped f-string interpolation in the staff-alert template: `support_email.py:140` (subject), `:145` (description, up to 5000 chars), `:126` (user_name), `:96` (company_name), `:129` (user_email, inside an `href`). The transcript-rendering loop at `:82` *does* HTML-escape (`&lt;`/`&gt;`) — so escaping was understood elsewhere in the same file and simply not applied to the public-form fields. Combined with `reply_to=ticket.user_email` (`:265`), the internal alert delivered to `Application@infinevocloud.com` both renders attacker HTML and has its reply-to pointed at the attacker.

### 4. Ticket-number namespace exhaustion → contact-form DoS — CONFIRMED
`_generate_ticket_number` (`support.py:46-54`) produces `INQ-{year}-{randint(1000,9999)}` — 9,000 possible values per year. `_unique_ticket_number` (`:57-64`) retries 10x then raises `RuntimeError`, uncaught by the handler, surfacing as a 500. With no rate limiting (finding 1), roughly 9,000 unauthenticated POSTs — minutes of traffic — saturate the space; after that, every legitimate inquiry fails, and authenticated `TICK`-prefixed tickets share the same 9,000-value random space under a different prefix, so they degrade too. The docstring's "<0.01% collision odds" claim holds only at low volume.

### 5. Sync handler + two sequential blocking SendGrid calls → threadpool exhaustion — PLAUSIBLE
`submit_contact_inquiry` is declared `def`, not `async def`, so each call holds an AnyIO worker thread (default pool size 40) across two sequential blocking `httpx` calls with 30s timeouts each (`outbound_email.py:86-87`). ~40 concurrent submissions against a slow/unresponsive SendGrid would starve the thread pool shared by every other synchronous endpoint in the app. Code path confirmed; actual impact threshold not load-tested.

### 6. Tenant isolation on the contact path — checked, no issue found
`tenant_id` is nullable on `SupportTicket` (`models.py:636`) and correctly left `None` for anonymous contact submissions — no sentinel value used. `GET /support/tickets` (`support.py:338-343`) filters on `context.tenant_id`, and `TenantContext.tenant_id` is a non-Optional `UUID` (`dependencies.py:20`); even the `ALLOW_MOCK_AUTH` dev path sets it to an all-zeros UUID (`dependencies.py:44`), never `None`. The degenerate case of an `IS NULL` tenant filter leaking every anonymous submitter's PII is therefore unreachable today. Recommend a defensive `.where(SupportTicket.tenant_id.is_not(None))` on that query to make the safety explicit rather than emergent from an unrelated non-Optional type.

### 7. SendGrid API key handling — checked, no issue found
`config.py:151` defaults to `""` and reads from env; `infra/modules/compute/invoice-be.bicep:161` wires it as a Key Vault `secretRef` (`05-secrets.bicep:231`); used only as a Bearer header value. Not hardcoded, not logged.

### 8. Network exposure context — lowers but does not remove severity
`invoice-be` has `ingress.external: false` (`invoice-be.bicep:109`), so the endpoint is not directly internet-reachable. However the public Next.js proxy at `/api/contact` forwards to it with no auth and no throttling, so findings 1–5 are fully exploitable one hop away via the public website. Also note: the proxy does not forward the original client IP, so any future IP-based limiter added on the backend side would see all website traffic as a single source and throttle every user together — a fix belongs at the proxy layer, or the proxy needs to forward the real client IP.

## Minor / out of scope
- `name` and `company` fields have no length validator (`support.py:81, 85-91`); only `message` is capped. Over-255-char input hits a Postgres `StringDataRightTruncation` error, surfaced as an uncaught 500 instead of a 422.
- `POST /support/chat` is authenticated, and `evaluate_support_query` (`agents/support_agent.py:193+`) is deterministic keyword/regex matching over a static knowledge base — no LLM call, no prompt-injection surface.
- `GET /support/tickets/{ticket_id}` is documented in `feature_19_support_tickets_and_notifications.md:66` but not implemented — spec drift, not a security issue.

## Recommendation
Findings 1–4 should be treated as merge blockers for this branch, not follow-up items: rate-limit/CAPTCHA the endpoint (and forward real client IP through the website proxy so limiting is meaningful), HTML-escape all user-supplied fields in both email templates, and bound the ticket-number generation failure mode (larger keyspace and/or a proper 503 instead of an uncaught 500). Finding 5 (sync handler) is a lower-urgency hardening item.
