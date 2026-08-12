# Gap 124 — inbound mail hardening (code-only items 5–7)

Checkpoint 16. DNS/SendGrid dashboard config is explicitly OUT of scope (user-owned checkpoint).

- [x] 1. `config.py` — `INBOUND_PARSE_SHARED_SECRET` (fail-closed) + `INBOUND_EMAIL_MAX_BYTES` (25 MiB)
- [x] 2. `models.py` — `DroppedInboundEmail` table
- [x] 3. Alembic migration `a2b3c4d5e6f7_add_dropped_inbound_emails.py`
      (three concurrent sessions briefly declared this same revision id, which
      is a hard alembic failure rather than a branch; the other two renumbered
      to `c9d0e1f2a3b4` / `c1d2e3f4a5b6`, so the id is now this file's alone.
      `b8c1d4e7f209` (Gap 194) chains off it — do not renumber without
      updating that file too.)
- [x] 4. `services/inbound_mail_security.py` — secret verification (3 transports,
      `hmac.compare_digest`), size helpers, drop recorder
- [x] 5. `routers/email_ingestion.py` — secret + 25 MiB cap enforced *before* the
      body is parsed (hand-rolled `request.form()`; FastAPI parses the body
      before it solves dependencies, so declared `Form(...)` params gave no
      pre-parse hook). Every drop path records a row. Also fixes attachment
      collection: `files: list[UploadFile]` only matched a part named `files`,
      but SendGrid sends `attachment1..N`.
- [x] 6. `routers/admin.py` — `GET /admin/dropped-emails`, Admin-only, tenant-scoped
      + narrow domain-match rule for unattributed rows
- [x] 7. `invoice-website` relay — forwards query string + secret headers (it
      dropped both before, so BE enforcement alone would have rejected 100% of
      real mail), 413s oversized bodies at the edge
- [x] 8. `invoice-fe` — `/api/admin/dropped-emails` proxy + Admin console panel
- [x] 9. Backend tests in `tests/test_email_ingestion.py` (12 new)
- [x] 10. `pytest` (real run) + `npx tsc --noEmit` on invoice-fe AND invoice-website
- [x] 11. Docs: `feature_14_email_ingestion.md` body + `be_features_tracker.md`
       Gap 124 (items 5–7 done, gap stays OPEN for DNS/live-verify half)

Status: complete. Gap 124 deliberately left `[ ]` open — only the code-hardening
half (items 5–7) is done; items 1–4 (GoDaddy MX, SendGrid Inbound Parse
destination, domain auth, live E2E) are external/user-owned and untouched.
