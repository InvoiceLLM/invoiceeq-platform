from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    CHROMA_HOST: str
    CHROMA_PORT: int
    # ChromaDB's Container App ingress is HTTPS-only when reached over its
    # external hostname (needed since its internal-only ingress rejected the
    # client's plain-HTTP calls outright) -- local/dev Chroma over docker-compose
    # has no TLS, so this defaults off and is only set true for that deployment.
    CHROMA_USE_SSL: bool = False
    CLERK_SECRET_KEY: str
    TOKEN_ENCRYPTION_KEY: str
    CLERK_JWT_ISSUER: str = ""
    CLERK_JWKS_URL: str = ""
    # Gap 4: gates the mock/test tenant fallback in dependencies.py.
    # Defaults False so an unconfigured or production deployment enforces real
    # Clerk auth. Set true ONLY for local dev and the test suite -- when true, a
    # request with no Authorization header resolves to a mock Admin context on
    # the all-zero tenant, which is a full auth bypass.
    ALLOW_MOCK_AUTH: bool = False
    # Gap 280: gates the Redis-backed async chat queue in routers/chat.py.
    # Defaults False so POST /message keeps its long-standing synchronous
    # behaviour for every tenant until this is verified live -- as merged,
    # the branch made async the unconditional default with the old behaviour
    # reachable only via an undiscoverable ?sync=true escape hatch, which is
    # a real production-behaviour change to chat with no rollout gate.
    #
    # Gap 365: "once it has real live evidence" was the whole problem -- a gate
    # with no stated bar is a gate nobody can ever satisfy, so the flag sat False
    # over a fully built queue/worker/SSE path. These are the five criteria.
    # ALL FIVE must pass, on ONE run against real Postgres and a real Redis
    # (hard rule 2 -- a SQLite/fakeredis run is not evidence), and passing them
    # flips this in DEV only. Production stays False until a 24h dev soak ends
    # with every `chat_inflight:{tenant}` counter back at zero.
    #   1. LIVE PROGRESS. An SSE transcript from one real turn on
    #      GET /chat/jobs/{id}/stream shows >= 6 DISTINCT `step` values, and a
    #      turn whose SQL needed repair shows each attempt separately. Before
    #      Gap 365 the worker published exactly 2 hardcoded steps.
    #   2. CONCURRENCY CEILING. The 4th simultaneous job for one tenant is
    #      rejected with HTTP 429 + Retry-After while the 3 in flight all
    #      complete. (Enforcement is Gap 364/Track A's
    #      `services/chat_queue.py::enqueue_chat_job` -- cite that run, do not
    #      re-derive it here.)
    #   3. FOLLOW-UP CORRECTNESS UNDER LOAD. A narrowing follow-up sent while
    #      earlier turns are in flight still routes to SQL -- i.e. Gap 237's
    #      deterministic override still sees the previous turn's `generated_sql`.
    #      This is what Gap 365's per-session Redis lock
    #      (`queue_worker/handlers.py::chat_session_lock`) exists to guarantee.
    #   4. NO SLOT LEAK ON FAILURE. A job that FAILS releases its slot:
    #      `chat_inflight:{tenant}` returns to 0 after `fail_job`, not just
    #      after `complete_job`.
    #   5. REDIS-DOWN FALLBACK. With Redis unreachable,
    #      POST /chat/sessions/{id}/message still answers via the synchronous
    #      path and returns no 5xx.
    # Founder decision, 2026-09-04 (Gap 451): BOTH paths stay, and the queue is
    # the one that is on. The synchronous path is kept deliberately -- it is the
    # Redis-down fallback named in criterion 5 above, and deleting it would make
    # an unreachable Redis a 5xx instead of a slower answer.
    #
    # Why the queue is now the default rather than the exception: it is the only
    # path with a progress channel, and Feature 26 Phase 3.3 puts attachment
    # extraction on it (Gap 452) so an upload can report reading -> extracting ->
    # matching instead of holding one HTTP request open for 25-50 seconds. It is
    # also the only path that enforces Gap 364's per-tenant concurrency ceiling.
    ENABLE_ASYNC_CHAT_QUEUE: bool = True

    # Feature 6.1 item A3: stream the four *phrasing* calls of a chat turn --
    # the SQL summary, the RAG answer and both Feature 26 narrations -- as
    # `streaming` progress events carrying the partial text, so the browser
    # renders the answer as it is written instead of after it is finished.
    #
    # Only those four. SQL generation is structured output (a schema, not prose)
    # and every figure a summary can state was computed by
    # `_computed_figures_block_for()` / `_full_record_block_for()` before the
    # call began (hard rule 3), so streaming changes WHEN text arrives, never
    # what it says.
    #
    # OFF by default and inert when off: every site falls back to `.invoke()`.
    # It is also inert on the synchronous HTTP path, which has no progress
    # consumer to stream to -- only the async queue path (`ENABLE_ASYNC_CHAT_QUEUE`)
    # has an SSE channel. Measured value is bounded: about 2s of *perceived*
    # latency on a 27.8s median turn, which is why it is last in Block A.
    ENABLE_CHAT_STREAMING: bool = False
    # Feature 27 (`docs/feature_27_generic_extraction.md`): make document type an
    # explicit, deterministic decision made *before* extraction, and make the
    # schema, the prompt and the verification rubric a function of it. Off, the
    # pipeline is what it is today -- implicitly an invoice pipeline, which grades
    # a delivery challan against a money rubric it was never going to satisfy and
    # returns a perfectly correct document looking broken (E3: flag OFF is
    # byte-identical to today, with E9's fail-loud as the one stated exception).
    #
    # THIS IS A SOFTWARE-LEVEL SWITCH, NOT A PER-TENANT ONE. Founder decision,
    # recorded as E2 in that document: one global env-driven boolean, resolved
    # once through `get_settings()`, identical for every tenant in the deployment.
    # There is deliberately no `Tenant` column, no rules-table row, no workflow
    # config entry and no header override, and one must not be added -- the
    # extraction graph carries `tenant_id` for telemetry only and never reads
    # per-tenant configuration, so a per-tenant flag would have to be resolved at
    # all eight `run_extraction_agent()` call sites, and mixed-mode data (two
    # tenants' rows extracted under different schemas and verified under
    # different rubrics, with nothing on the row saying which) is worse than
    # either mode. If a per-tenant rollout is ever wanted the shape is a separate
    # deployment, which `infra/params.*.json` already supports.
    #
    # What it costs when on: one extra classification step per document. The
    # deterministic title-band pass (`services/document_type_classifier.py`)
    # costs nothing and is the common case; only an ambiguous or untitled
    # document pays for one extra structured-output call
    # (`extraction.classify_doc_type`). Non-invoice documents then leave the
    # `invoice` table entirely (E10) for `documents` + a `docs_{tenant_id}`
    # Chroma collection, which is why this is not a free flip.
    #
    # What flips it -- all required, and none of it is cleared yet:
    #   1. T-OFF-1: a fixture through the pipeline with the flag OFF produces an
    #      extracted dict equal, field for field, to the recorded pre-change
    #      golden. Equality, not "the tests still pass".
    #   2. T-R-6: the ON-case mirror -- an INVOICE-family fixture with the flag ON
    #      equals that same golden. This is the one that proves turning it on does
    #      not silently drop `compliance_metadata`, `tax_ids`, `round_off` or
    #      per-line `hsn_sac_code` while still returning a plausible-looking
    #      `vendor_name` and `grand_total`.
    #   3. §7 task F's real fixtures exist, and the classifier's `0.6` confidence
    #      threshold has been calibrated against their measured distribution --
    #      that number is a placeholder chosen before any real document existed
    #      (N2), not a validated one.
    #   4. T-E10-1/2/3 against real Postgres (hard rule 2): a `DELIVERY_NOTE`
    #      leaves zero `invoice` rows, `/dashboard/insights` is byte-identical
    #      before and after ingesting one, and a re-upload is not billed twice.
    # Rollout gate on top of the build gate: G11 (FE) and G14 (`GET /documents`)
    # must both exist before this is turned on anywhere a user can see, because
    # E10 deletes the placeholder `invoice` row and without them a classified
    # delivery note is invisible to whoever uploaded it.
    #
    # Default False for the same fail-closed reason as every other flag in this
    # file: a deployment that has not thought about this must get today's
    # behaviour.
    #
    # ── REMOVAL CRITERION (Feature 27 task R12) ───────────────────────────────
    # The condition under which this flag is DELETED rather than merely flipped
    # on. It is written down because the alternative is what actually happens to
    # feature flags: they are flipped, they work, and the flag-OFF branch lives
    # forever as a second code path nobody exercises and nobody dares remove.
    #
    # Remove when all of:
    #   (a) R4's and R11's Postgres runs are recorded (hard rule 2 -- a recorded
    #       run, not a passing test on SQLite);
    #   (b) R5's rollout gate is closed: the FE surface exists and a classified
    #       non-invoice is visible to whoever uploaded it;
    #   (c) one dev soak of >= 7 days with ZERO `doc_type_reason == "llm_error"`
    #       and ZERO misrouted `documents` rows;
    #   (d) T-R-3's equality still holds on the THEN-CURRENT invoice suite --
    #       re-run at removal time, not cited from this run, because the point of
    #       that test is that the invoice path did not move and the invoice path
    #       keeps moving.
    #
    # At that point the flag-OFF graph is DELETED, not kept. A branch retained
    # "just in case" after the criterion is met is a branch that will be wrong
    # the first time anyone edits the other one.
    #
    # Build-gate item 3 above is now SATISFIED, recorded here because it names a
    # number that has since changed: the threshold was recalibrated 0.6 -> 0.75
    # on 2026-09-03 (task R11) against six measured LLM-path confidences
    # (0.90/0.92/0.93/0.95/0.95/0.95 -- nothing observed between 0.60 and 0.90).
    # See `services/document_type_classifier.py::DOC_TYPE_CONFIDENCE_THRESHOLD`
    # for the basis and `tests/fixtures/doc_types/MANIFEST.md` for both numbers.
    #
    # ── DEFAULT FLIPPED False -> True, 2026-09-05 (Gap 461) ───────────────────
    # Founder decision: the flag is already ON in Azure and "should be always
    # on", so the fail-closed default above had stopped protecting anything and
    # started doing harm -- a fresh checkout, a new environment, and CI each ran
    # a DIFFERENT pipeline from the one actually serving users, which is the
    # condition under which a bug reaches production having passed every local
    # test. The default now matches the deployment.
    #
    # What this does NOT do: it does not satisfy the build/rollout gates above,
    # and it does not delete the flag-OFF branch (that is still task R12's
    # removal criterion, unmet -- (c)'s 7-day soak has not been run). The gates
    # are recorded as met in practice rather than on paper: the rollout gate's
    # two halves both exist (`GET /documents` = G14, and the FE surface at
    # `app/documents/page.tsx` = R5(c), commit 510c444), and `test_documents_
    # table.py` / `test_document_type_classifier.py` / `test_document_delete.py`
    # ran 243 passed against real Postgres on 2026-09-05.
    #
    # KNOWN CONSEQUENCE, accepted knowingly: the 27 flag-OFF parity tests in
    # `tests/test_generic_extraction.py` read this setting at import time
    # instead of forcing it, so they now fail on EVERY machine rather than only
    # on ones with `ENABLE_GENERIC_EXTRACTION=true` in `.env`. That is a defect
    # in those tests, not in this feature -- see Gap 461 in the tracker.
    #
    # ═══ ALWAYS TRUE. NEVER SET THIS TO FALSE. ═══════════════════════════════
    # Founder ruling, 2026-09-05: "the flag is always on". Not a default to be
    # overridden per environment -- on everywhere, permanently. Do not set it
    # False in `.env`, in `infra/params.*.json`, in a test, or "temporarily" to
    # debug something. There is no supported configuration of this product in
    # which it is False, and the OFF branch below it is unexercised dead code.
    # Deleting the flag and that branch outright was started as Gap 468 and
    # deliberately reverted by the founder -- the setting stays, pinned True.
    ENABLE_GENERIC_EXTRACTION: bool = True
    # Gap 117: which deployment this process is. Read only by ops scripts that
    # must never touch production data (scripts/grant_test_plan.py), never by
    # request-handling code -- nothing about the product's behaviour should
    # branch on it. Defaults to "production" deliberately, the same fail-closed
    # choice as ALLOW_MOCK_AUTH above: an environment that forgot to declare
    # itself is treated as the one where a destructive script must refuse to
    # run, so the unsafe state is the one you have to opt into explicitly.
    ENVIRONMENT: str = "production"
    DEFAULT_FREE_INVOICES_LIMIT: int = 50
    # Gap 118: how often DEFAULT_FREE_INVOICES_LIMIT refills. The free tier was
    # always described as a monthly allowance but was implemented as a
    # decrement-only lifetime counter, so a free tenant was permanently capped
    # at 50 invoices ever. Deliberately its own knob rather than reusing
    # BILLING_CYCLE_DAYS: that value is "how much time one PayU payment buys",
    # and if a future annual plan pushed it to 365 the free tier would silently
    # become 50 invoices per *year*. Same default (30) today, different meaning.
    FREE_QUOTA_CYCLE_DAYS: int = 30

    # --- Feature 25 (Gap 340): sandbox `inv_test_` keys ---------------------
    #
    # A sandbox key is issued to an ANONYMOUS website visitor with no login, and
    # resolves to a fresh real Tenant row. Every value below is a containment
    # knob, so each has a deliberately conservative default rather than an
    # "unlimited" one -- the whole surface is unauthenticated.
    #
    # Master switch. Default False: a deployment that has not thought about the
    # abuse surface must not be handing out credentials to strangers. Same
    # fail-closed reasoning as ALLOW_MOCK_AUTH above.
    SANDBOX_KEYS_ENABLED: bool = False
    # How long a sandbox key lives. Expiry is enforced live in
    # dependencies.resolve_api_key_context() (the key stops verifying) AND swept
    # by scripts/sweep_sandbox_tenants.py, which deletes the tenant outright --
    # a flag nobody reads is not a TTL.
    SANDBOX_KEY_TTL_HOURS: int = 72
    # Hard ceiling on UNCLAIMED sandbox tenants platform-wide. Issuance past this
    # fails closed with a "temporarily unavailable" 503 rather than creating
    # tenant rows without bound. Counted under an advisory lock at issuance time.
    SANDBOX_MAX_UNCLAIMED_TENANTS: int = 500
    # Per-IP sliding window for issuance, enforced through the SAME limiter the
    # public contact form uses (routers/support.py::_ContactRateLimiter) -- it
    # already solves the which-IP-header-do-we-trust problem for this platform.
    SANDBOX_ISSUE_RATE_LIMIT: int = 3
    SANDBOX_ISSUE_RATE_WINDOW_SECONDS: int = 3600
    # Gap 340 requirement 7: services/billing_quota.py's free-tier charge covers
    # INGESTION only, so without this a sandbox key is an unmetered path to real
    # Azure OpenAI spend. A plain bounded counter on the sandbox row, not a
    # second quota system.
    SANDBOX_CHAT_MESSAGE_LIMIT: int = 25
    # How many invoices a sandbox workspace may ingest. Kept separate from
    # DEFAULT_FREE_INVOICES_LIMIT so tightening the sandbox does not tighten the
    # free tier a paying-adjacent customer is on.
    SANDBOX_INVOICE_LIMIT: int = 5

    # --- Feature 26 Part 2 (E-7): chat attachment retention -----------------
    #
    # How long a document a user attached to a chat turn is kept before the
    # sweeper (`scripts/sweep_chat_attachments.py`, task H8) deletes the row, its
    # blob and its chunks from `chat_docs_{tenant_id}`. Written onto every new
    # row as `ChatAttachment.expires_at = created_at + this`, so the expiry of a
    # row is fixed at upload time and does not silently move when this value is
    # changed -- an already-uploaded document keeps the lifetime the user was
    # given, and re-tuning the knob only affects what is attached after it.
    #
    # Deliberately its OWN knob rather than reusing SANDBOX_KEY_TTL_HOURS or
    # FREE_QUOTA_CYCLE_DAYS. Those two answer different questions ("how long does
    # an anonymous credential live", "how often does the free allowance refill"),
    # and an attachment is the first thing in this system with a genuine finite
    # lifetime for a third reason again: it is a transient artifact of one
    # conversation that carries a vector footprint in a second Chroma collection,
    # which nothing else in the product ever removes (invoice chunks deliberately
    # have no TTL -- `delete_invoice_chunks()` is unwired from soft-delete so a
    # restored invoice keeps its chunks). Sharing a knob would mean tightening
    # one of those unrelated policies silently re-times this one.
    #
    # 30 days, matching E-7's stated default. The value is not fail-closed the
    # way the flags above are -- a shorter value deletes a user's attachment out
    # from under a conversation they are still having, so the conservative
    # direction here is longer, not shorter.
    CHAT_ATTACHMENT_TTL_DAYS: int = 30
    # Feature 26 Part 2 (`docs/feature_26_chat_attached_documents.md`, E-1/E-3):
    # let an attached document be asked open-ended questions about its own
    # CONTENT -- "what are the payment terms?", "who signed it?" -- instead of
    # only "does this agree with our invoices?".
    #
    # FILED RETROACTIVELY (BE Gap 382 — this comment read "Gap 380" until BE
    # Gap 384's close-out pass; 380 is FE Gap 380, Feature 26 task H11, which is
    # unrelated FE work. Always write the "BE"/"FE" prefix on a 378-385 number).
    # Task H5 shipped the whole intent-split /
    # clarifying-turn / content-branch mechanism with no gate at all, which is
    # why this docstring reads like a correction rather than a design note: the
    # founder's original brief for this feature asked for exactly this flag and
    # it was dropped somewhere between the brief and the spec. Every other
    # ENABLE_* in this file defaults False and gates its own code path; this one
    # did not exist, so H5's new logic was live in every deployment the moment
    # it merged.
    #
    # WHAT OFF MEANS, EXACTLY -- and this is the whole point of the flag:
    # `_run_attached_document_turn()` does not call
    # `_classify_attachment_intent()` at all. Not "classifies and then ignores
    # the result", not "the content branch happens never to trigger" -- the
    # classifier is never invoked, the clarifying turn is unreachable, and
    # `_run_attachment_content_branch()` has no caller. Every attachment turn
    # goes straight to Part 1's confirmation gate and comparison path, which is
    # byte-identical to the pre-H5 behaviour shipped under Gap 366. Same
    # guarantee shape as Feature 27's E3, and asserted the same way: a named
    # test (`test_chat_doc_content_branch.py`'s flag-OFF parity block), not
    # "the tests still pass".
    #
    # What it costs when on: one vector search plus one narration call per
    # content-branch turn, against `chat_docs_{tenant_id}` -- i.e. an embedding
    # call and an Azure OpenAI call on turns that previously made neither
    # (the confirmation turn composes its prose in Python). It also puts
    # retrieved document text in front of the model, which is a second
    # untrusted channel: mitigated by `_wrap_retrieved_document_text()` + its
    # guard instruction (B6), and structurally bounded by the content branch
    # computing no figures at all, but a mitigation is not a control.
    #
    # What flips it -- none of it cleared yet:
    #   1. The FE surface exists and is shipped. H10/H11/H12 render the
    #      clarifying turn's two choice buttons and the `evidence[]` block; with
    #      the flag on and those absent, a clarifying turn is a question the
    #      user has no way to answer.
    #   2. A real-document pass over the intent split's keyword lists. The two
    #      alternations in `agents/query_agent.py` are hand-written English and
    #      have never been measured against real user phrasing; a comparison
    #      question misread as content is a financial question answered from
    #      narration instead of `Decimal`.
    #   3. V-25's live-model injection probe (functional-tester's), i.e. a real
    #      hostile PDF through the real model, not the committed unit test that
    #      only proves the markers are in the prompt.
    #   4. Feature 27's `ENABLE_GENERIC_EXTRACTION` is on, per the founder's
    #      original brief -- E-1's family-bias table keys on `doc_type`, and
    #      with that flag off every attachment is PO/QUOTATION/OTHER, so the
    #      DELIVERY_NOTE/GRN/CONTRACT rows the content branch exists for are
    #      unreachable. This is a rollout ordering, not an import-time
    #      dependency: nothing here reads that flag, deliberately, because two
    #      flags reading each other is how a deployment ends up in a state
    #      neither was tested in.
    #
    # Default False for the same fail-closed reason as every other flag here: a
    # deployment that has not thought about this must get today's behaviour --
    # which for this feature means Part 1's, the one with the deterministic
    # `Decimal` comparison and the explicit confirmation gate.
    #
    # ── REMOVAL CRITERION (Feature 26 amendment B11, task R13) ────────────────
    # The condition under which this flag is DELETED rather than flipped, copied
    # verbatim in substance from B11 so the two cannot drift:
    #
    #   Removed when all of: (a) H16 has landed and the answer contract is
    #   verified reaching the browser against real Postgres (V-27); (b) V-25's
    #   live injection probe is recorded with the structural control holding;
    #   (c) the intent split's keyword lists have been measured against a real
    #   transcript sample -- at least 50 real attachment turns -- with the
    #   misroute rate RECORDED, not estimated; (d) the FE surface has been driven
    #   end to end by a person, once, and a screenshot filed; (e) one dev soak of
    #   >= 7 days with zero turns landing on
    #   `stop_reason="attachment_no_indexed_text"` for a document that did index.
    #
    # At that point the flag-off path is deleted and Part 1's comparison branch
    # becomes the `comparison` arm of the intent split rather than a separate
    # reachable path -- which is the real prize here. Two reachable paths through
    # one feature is the state B11 exists to make temporary.
    #
    # What this flag gates, restated because it is narrower than the name
    # suggests: Part 2's intent split and content branch, and nothing else.
    # `attachment_id` presence remains the ROUTING switch and is not a flag
    # (B11 item 1), and this must never grow into a gate on attachments as such.
    ENABLE_GENERIC_DOC_CHAT: bool = False

    AZURE_STORAGE_CONNECTION_STRING: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    # Where oauth_callback() redirects the browser back to after a connector
    # OAuth flow completes -- Google hits this backend directly
    # (see GOOGLE_REDIRECT_URI), so the backend itself must send the user
    # back into the app rather than leaving them on a bare JSON response.
    # This one targets an *invoice-fe* route (/settings/connectors), so in
    # local dev it is FE's own dev server (:3001 if FE is run directly, :3000
    # only if the website's Multi-Zone proxy is fronting it). Deliberately
    # kept distinct from PUBLIC_APP_URL below -- see that comment.
    FRONTEND_URL: str = "http://localhost:3000"
    # Where routers/billing.py sends a user returning from PayU
    # (/billing/success, /billing/failed). Those two routes live in
    # *invoice-website*, not invoice-fe, because post-Multi-Zone-proxy
    # (website_features_tracker.md Gap 12) invoice-fe's ingress is
    # external: false and a browser coming back from a third party
    # physically cannot reach an invoice-fe URL -- invoice-website is the
    # only public origin. Split out from FRONTEND_URL rather than reusing
    # it so the connectors redirect (an invoice-fe route) and the billing
    # redirect (an invoice-website route) can differ in local dev, where
    # there is no proxy collapsing them onto one origin. In Azure both
    # values point at invoice-website's public FQDN.
    PUBLIC_APP_URL: str = "http://localhost:3000"
    MOCK_EMBEDDINGS: bool = False
    # Gap 12: directory watcher only accepts paths under this base dir (path-traversal
    # guard against arbitrary server filesystem reads). Empty = feature disabled.
    WATCHER_ALLOWED_BASE_DIR: str = ""


    # --- ADD THESE THREE LINES ---
    LLM_PROVIDER: str = "azure"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # Gap 288-series follow-up (2026-08-23): was "llama3:8b" -- the original
    # Llama 3, released before Ollama/LangChain tool-calling support existed.
    # `.with_structured_output()` needs Llama 3.1+ to be reliable. Using
    # llama3.2:latest specifically because it's already pulled on this
    # machine (`ollama list`) -- no new multi-GB download needed, and 3.2 is
    # a later generation than 3.1 with the same tool-calling support carried
    # forward.
    OLLAMA_MODEL: str = "llama3.2:latest"

    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    # Gap 465 (2026-09-05): GA data-plane version. Was `2024-02-15-preview`, a
    # preview from before structured outputs existed; `2024-10-21` is GA and was
    # verified live against the gpt-5-mini deployment with a strict json_schema
    # response_format on 2026-09-05. This is the ONE place the version lives in
    # code; infra threads the same value through `azureOpenAiApiVersion`.
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    # Feature 6.1 item A2: the deployment used for the *non-reasoning* half of a
    # chat turn -- routing, summarising rows already computed, answering from
    # retrieved text, and narrating a diff table deterministic code built. None of
    # those reasons about anything, so paying a reasoning model's thinking tokens
    # for them buys nothing and costs seconds: measured 2026-09-03, classify 3.1s
    # and summary 3.6s of a 27.8s median turn.
    #
    # EMPTY BY DEFAULT, deliberately -- empty means `_fast_llm()` returns exactly
    # what `get_llm()` returns, so an unset environment behaves bit-identically to
    # before this existed. Set it to `gpt-4o` to turn A2 on.
    #
    # What must stay on the reasoning deployment: SQL generation. It is the one
    # call in the turn that genuinely reasons -- schema, joins, the repair loop --
    # and item A1 tunes its `reasoning_effort` separately. Never point this at the
    # generation path.
    #
    # Safe because no figure is at stake: `_computed_figures_block_for()` and
    # `_full_record_block_for()` compute every number before the model sees it,
    # and Feature 26's narration rule forbids stating a figure absent from the
    # diff table. The model phrases; it does not decide (hard rule 3).
    AZURE_OPENAI_FAST_DEPLOYMENT_NAME: str = ""

    # Feature 6.1 item A1: the reasoning budget for SQL GENERATION only.
    #
    # Generation is the one call in a chat turn that genuinely reasons -- schema,
    # joins, the three-attempt repair loop -- so unlike A2 it stays on the
    # reasoning deployment. What it does not need is the *default* budget:
    # measured 2026-09-03, generation was 15.6s of a 27.8s median turn and emitted
    # 1,688 output tokens, most of them thinking rather than SQL.
    #
    # Valid values are whatever the deployment accepts ("low" / "medium" /
    # "high"). EMPTY MEANS UNSET -- the parameter is not sent at all and the
    # deployment's own default applies, which is exactly today's behaviour.
    #
    # The risk this carries, stated rather than discovered later: a cheaper
    # reasoning budget still returns *a* query. It does not fail loudly; it fails
    # by generating subtly worse SQL. The golden set is the only control, which is
    # why this ships empty and is turned on against a measured before/after.
    AZURE_OPENAI_SQL_REASONING_EFFORT: str = ""

    # Feature 6.1 item A1, second half: an upper bound on generation output.
    # 0 means unset -- no cap is sent, which is today's behaviour. A cap bounds
    # the tail case where the model reasons at length and the turn stalls; it
    # cannot make a correct query incorrect, only truncate an overlong one, and a
    # truncated query fails loudly in `execute_generated_sql` rather than quietly.
    AZURE_OPENAI_SQL_MAX_COMPLETION_TOKENS: int = 0

    # Azure uses the *deployment* name, not the model name. Default matches the
    # one deployment every environment runs on (was `gpt-4o-mini`, a retired
    # model no environment has had since Jul 2026 -- Gap 465).
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-5-mini"
    # Gap 465: deployment for LLM-as-judge (agent eval, production quality
    # judge). Empty = same as AZURE_OPENAI_DEPLOYMENT_NAME. Exists so a candidate
    # swap of the primary can be graded by a model that did not change.
    AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME: str = ""
    # Gap 465: the two non-OpenAI model choices, previously hardcoded at their
    # single call sites (`queue_worker/handlers.py::_run_ocr` and
    # `chroma_client.py::get_embedding_model`). Changing EMBEDDING_MODEL_NAME
    # invalidates every Chroma collection -- re-embed with
    # `scripts/reembed_chroma_collections.py`; the Redis query cache key carries
    # the model name so it does not need flushing.
    DOC_INTEL_MODEL_ID: str = "prebuilt-invoice"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    AZURE_DOC_INTEL_ENDPOINT: str = ""
    AZURE_DOC_INTEL_KEY: str = ""
    # Optional additional Doc Intelligence resources for horizontal scale-out
    # (Gap 41/42, Jul 2026) - each S0 resource has its own independent rate
    # limit (no shared regional quota pool like Azure OpenAI has), so
    # round-robining across several is the effective scaling lever.
    # Two ways to configure (utils/doc_intel_client.py merges both):
    # (1) comma-separated AZURE_DOC_INTEL_ENDPOINTS/KEYS - convenient for
    #     local .env; (2) numbered AZURE_DOC_INTEL_ENDPOINT_2/_KEY_2,
    #     _3/_3, ... - required in Container Apps, since each Key Vault
    #     secret maps to its own env var (can't join multiple secretRefs
    #     into one comma-separated value declaratively in bicep).
    AZURE_DOC_INTEL_ENDPOINTS: str = ""
    AZURE_DOC_INTEL_KEYS: str = ""
    AZURE_DOC_INTEL_ENDPOINT_2: str = ""
    AZURE_DOC_INTEL_KEY_2: str = ""
    AZURE_DOC_INTEL_ENDPOINT_3: str = ""
    AZURE_DOC_INTEL_KEY_3: str = ""

    # OAuth Credentials
    # Salesforce (SALESFORCE_CLIENT_ID/SECRET/REDIRECT_URI) removed 2026-08-28,
    # Gap 334. The corresponding infra wiring (Key Vault secret, Container App
    # env vars, params files) is deliberately left in place -- separately
    # scoped, and an unused env var is harmless where a deleted Key Vault
    # secret is not trivially reversible.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    # Feature 11: PayU Billing
    PAYU_MERCHANT_KEY: str = ""
    PAYU_MERCHANT_SALT: str = ""
    PAYU_MODE: str = "test"  # "test" or "live"
    # The public origin PayU POSTs surl/furl back to. Despite the name this
    # is NOT invoice-be's own origin: invoice-be's ingress is internal-only
    # (external: false), so PayU -- an external third party -- can never
    # reach it directly. It is invoice-website's public origin, which now
    # carries a verbatim pass-through at the *same* path shape the backend
    # serves (app/api/v1/billing/payu/{success,failure}/route.ts), so the
    # surl/furl strings built below need no special-casing. Mirrors the
    # existing OAuth callback proxy pattern (routers/connectors.py's
    # oauth_callback() / apps/invoice-fe's /api/connectors/callback/[provider]).
    # Default is invoice-website's local dev port (3000), not invoice-be's
    # (8000), so local dev exercises the same pass-through path as Azure.
    BACKEND_PUBLIC_URL: str = "http://localhost:3000"
    # Gap 71: billing lapse enforcement. PayU's classic API has no recurring
    # object, so a paid cycle is tracked by us as a date (Tenant.paid_through)
    # and lapse is inferred from it rather than received as a webhook.
    # BILLING_CYCLE_DAYS is how far a verified payment pushes that date
    # forward; 30 rather than a real calendar month because the prices in
    # routers/billing.py::PLAN_AMOUNTS are flat monthly figures with no
    # proration, so a fixed period is both simpler and never shorter than
    # what was paid for. BILLING_GRACE_PERIOD_DAYS is how long past that date
    # a tenant keeps access before being demoted to 'unpaid' -- deliberately
    # non-zero so a payment that lands a few hours late (or a sweep that runs
    # late) doesn't lock out a paying customer.
    BILLING_CYCLE_DAYS: int = 30
    BILLING_GRACE_PERIOD_DAYS: int = 3
    # FE Gap 81: stuck-invoice reconciliation. An invoice still in a
    # non-terminal status this long after its last enqueue is treated as
    # stalled and re-enqueued. 15 minutes is comfortably above a normal
    # end-to-end run (OCR + up to two LLM extraction passes, observed ~20-60s)
    # including the retry loops in extraction_agent/_run_ocr, so a merely slow
    # invoice is never re-queued underneath a worker that is still working on
    # it. After MAX_REPROCESS_ATTEMPTS re-queues it is marked FAILED instead,
    # so a file the worker genuinely cannot process can't loop forever.
    INVOICE_STUCK_AFTER_MINUTES: int = 15
    INVOICE_MAX_REPROCESS_ATTEMPTS: int = 2
    # Feature 14: one platform-wide mailbox (not per-tenant).
    # Tenant + direction are resolved from the sender's registered set.
    EMAIL_APP_DOMAIN: str = "invoiceeq.app"
    EMAIL_APP_ADDRESS: str = "invoices@invoiceeq.app"
    # Gap 125: SendGrid Mail Send. Works with Single Sender Verification for
    # tests (no GoDaddy domain auth required); domain auth improves deliverability.
    SENDGRID_API_KEY: str = ""
    SENDGRID_SENDING_DOMAIN: str = ""
    # Outbound sender address & display name. SENDGRID_FROM_EMAIL takes priority
    # over EMAIL_APP_ADDRESS in outbound_email.py::from_address() so the
    # inbound mailbox (AI receive) and outbound sender (customer notifications)
    # are cleanly separated. Injected from bicep params sendgridFromEmail /
    # sendgridFromName -- must be declared here or Pydantic extra='ignore'
    # silently drops the Container App env vars.
    SENDGRID_FROM_EMAIL: str = ""
    SENDGRID_FROM_NAME: str = "InvoiceLLM"
    # Gap 124 item 5: the shared secret POST /email/mailintegration requires.
    # The name matches the container env var already wired in
    # infra/modules/compute/invoice-be.bicep, which maps it to the Key Vault
    # secret SENDGRID-INBOUND-SECRET -- that secret was provisioned but nothing
    # in the application ever read it, so the webhook was open to anyone who
    # could reach the website relay.
    #
    # SendGrid Inbound Parse lets you configure a Destination URL and nothing
    # else -- no signing key, no signature header -- so the only place the
    # secret can travel is the URL itself. Accepted, in order: an
    # `X-Inbound-Secret` header, a `key`/`secret` query parameter, or the
    # password half of HTTP Basic credentials embedded in the URL. See
    # services/inbound_mail_security.py::presented_inbound_secret.
    #
    # Fail-closed, deliberately, the same choice as ALLOW_MOCK_AUTH above: an
    # empty value does NOT mean "enforcement off", it means every inbound mail
    # POST is rejected, because an empty shared secret cannot authenticate
    # anything. A deployment that has not seeded the Key Vault secret yet is
    # exactly the deployment that must not accept unauthenticated mail. The
    # rejection is recorded (reason `secret_unconfigured`) and visible in the
    # Admin console, so the misconfiguration surfaces instead of silently
    # eating mail.
    INBOUND_PARSE_SHARED_SECRET: str = ""
    # Gap 124 item 7: hard ceiling on a single inbound mail POST, attachments
    # included. 25 MiB matches SendGrid's own documented Inbound Parse limit --
    # anything larger than this was never going to be a legitimate parse POST.
    INBOUND_EMAIL_MAX_BYTES: int = 26_214_400

    # Feature 19 / Feature Website 5: Support Ticket & Inquiry Engine
    # Destination inbox for all support alert emails (contact form submissions,
    # chatbot escalations, and direct app tickets). Defaults to the platform's
    # primary support address; override via env var in Key Vault for alternate
    # environments. NEVER set to empty — that would silently swallow every ticket.
    SUPPORT_NOTIFY_EMAIL: str = "sbanerji@admsofttech.com"

    # Gap 249: the Front Door profile's `frontDoorId` GUID, used only to decide
    # whether the `X-Azure-ClientIP` header on an inbound request can be
    # trusted for rate-limiting (see routers/support.py::_get_client_ip).
    #
    # Empty by default, and empty is the correct value today: Front Door is
    # gated on `customDomainName` in infra/08-apps.bicep, that param is unset,
    # and nothing has been deployed -- so no request currently arrives with a
    # genuine X-Azure-* header. Leaving this empty means those headers are
    # ignored outright, which is the safe state: if we trusted X-Azure-ClientIP
    # unconditionally, any caller could forge it and reset their own limit
    # window, which is the exact bypass this setting exists to prevent.
    #
    # Set it (to the real profile GUID, not a placeholder) only in the same
    # change that actually puts Front Door in front of this app. An inbound
    # X-Azure-FDID is only honoured when it matches this value exactly.
    FRONT_DOOR_ID: str = ""

    # Feature 23 / Gap 304 half (2): score every real production chat turn with
    # the same reference-free judge the golden bank uses
    # (`services/online_quality_judge.py`), writing an `agent_eval_run` row
    # tagged `run_source=production`.
    #
    # This is an on/off switch, not a sampling control -- when it is on, every
    # turn is judged. Default False for the same fail-closed reason as the two
    # flags above, plus one this file has not had before: turning it on adds
    # **two billable LLM calls to every chat turn** (the combined soft judge and
    # the persona judge). That is a real per-tenant cost change, so it is opted
    # into per environment rather than arriving switched on with a merge.
    #
    # Off is inert by construction: the judge is submitted, not called, and the
    # submit helper checks this flag before it hands anything to a thread, so
    # with the flag off nothing extra runs on the turn at all.
    ENABLE_PRODUCTION_QUALITY_JUDGE: bool = False

    # Feature 20 Area 1 (`services/azure_cost.py`): what resource group's real
    # Azure spend to read from the Cost Management API, and how to authenticate.
    #
    # Both of the first two must be set for any cost call to happen at all --
    # `cost_scope()` raises rather than guessing, because a wrong scope returns a
    # perfectly valid-looking response for somebody else's spend. The live dev
    # values are subscription `2ae37d8b-...` / `rg-invoice-llm-dev`; they are not
    # defaulted here because this file is shared with local and prod processes.
    AZURE_SUBSCRIPTION_ID: str = ""
    AZURE_COST_RESOURCE_GROUP: str = ""
    # Empty means "the live budget name", `budget-invoicellm-dev` -- see
    # `services/azure_cost.py::resolve_budget_name()` for why that is hardcoded
    # as the default rather than derived from a naming prefix.
    AZURE_COST_BUDGET_NAME: str = ""
    # An explicitly supplied ARM bearer token. For one-off local checks and for
    # the test suite; never set on a container.
    AZURE_COST_ACCESS_TOKEN: str = ""
    # Allow falling back to `az account get-access-token` when no managed
    # identity is present. Default False, same fail-closed reasoning as
    # ALLOW_MOCK_AUTH: a deployment that lost its managed identity should raise
    # a clear auth error, not silently run as whoever last ran `az login`.
    AZURE_COST_CLI_FALLBACK: bool = False

    # Feature 23 benchmark artifacts (`services/benchmark_artifacts.py`). Where
    # the two tracks' full raw JSON output is kept, so a workbook panel's
    # `extraction_benchmark_run` / `agent_eval_summary` event can be followed
    # back to the per-case (Track 1) / per-turn (Track 2) detail behind it.
    #
    # A separate container from `invoices`, not a prefix inside it: that one
    # holds tenant PDFs, is the target of `delete_pdf_from_storage()`, and would
    # end up under whatever retention/lifecycle policy tenant data eventually
    # gets. Benchmark output is neither tenant data nor subject to that.
    BENCHMARK_ARTIFACT_CONTAINER: str = "benchmark-artifacts"
    # Only consulted when AZURE_STORAGE_CONNECTION_STRING is unset/placeholder --
    # the managed-identity path, which needs the account name because there is no
    # connection string to read it out of. `id-invoicellm-dev` already holds
    # `Storage Blob Data Contributor` on `stinvoicellmdev2` (verified live
    # 2026-08-24), so that path needs no new role assignment.
    AZURE_STORAGE_ACCOUNT: str = ""
    # Off switch for the upload half of the mirror. The telemetry event is still
    # emitted -- it carries no `artifact_blob` and the workbook panel simply has
    # no link to follow. For a local run that should not touch Azure at all.
    BENCHMARK_ARTIFACT_UPLOAD: bool = True

    # Feature 24 (Ops Digest Agent) declared seven OPS_DIGEST_* settings here.
    # The feature was superseded as over-scoped and deleted 2026-08-25 (Gap 311);
    # `extra="ignore"` below means a stale OPS_DIGEST_* line left in someone's
    # local `.env` is silently dropped rather than raising at startup.

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

# Gap 359: ALLOW_MOCK_AUTH is a full authentication bypass (Gap 4's docstring
# above). It defaults False and is confirmed off in every real deployment
# today, but nothing previously stopped a future deployment from setting it
# true by accident -- there was no startup check tying it to a non-production
# environment, only the default itself. This mirrors NON_PRODUCTION_ENVIRONMENTS
# in scripts/grant_test_plan.py (same set, same fail-closed reasoning) rather
# than importing it from there -- that module is a standalone ops script, not
# meant to be imported into the running app.
NON_PRODUCTION_ENVIRONMENTS = {"dev", "development", "local", "test", "testing", "qa", "staging"}


def _enforce_mock_auth_not_in_production(s: Settings) -> None:
    """Raises if `s` describes a full auth bypass outside a non-production
    environment. A plain function, not an inline `if`, so a test can call it
    directly against a constructed `Settings` without reloading this module."""
    if s.ALLOW_MOCK_AUTH and s.ENVIRONMENT not in NON_PRODUCTION_ENVIRONMENTS:
        raise RuntimeError(
            "ALLOW_MOCK_AUTH=true is a full authentication bypass and is refused "
            "outside a recognized non-production ENVIRONMENT "
            f"({', '.join(sorted(NON_PRODUCTION_ENVIRONMENTS))}); "
            f"got ENVIRONMENT={s.ENVIRONMENT!r}. Set ALLOW_MOCK_AUTH=false, "
            "or set ENVIRONMENT to a recognized non-production value."
        )


# Runs at import time, not inside main.py's lifespan hook, so a misconfigured
# process fails before it ever binds a port rather than merely failing its
# readiness probe -- the strongest fail-closed point available.
_enforce_mock_auth_not_in_production(settings)