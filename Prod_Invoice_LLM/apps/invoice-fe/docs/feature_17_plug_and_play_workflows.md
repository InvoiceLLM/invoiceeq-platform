# Feature 17: Plug & Play Workflows — Setup Wizard, Role Vocabulary & Widget Tokens

**STATUS: BUILT (FE Gap 324 + FE Gap 323 + the widget half of FE Gap 325),
2026-08-30.** Gaps 323/324 were typecheck-clean *and* verified by a real
click-through against a live local stack. FE Gap 325's widget half is
typecheck-clean and its backend contract was verified live against real FastAPI +
real Postgres, but **its in-browser click-through was not achieved and is not
claimed** — see Verification Plan §7 for the exact failure and what that leaves
unproven. Nothing in this feature has been run against a deployed environment.

**Update 2026-08-30 (functional-tester final gate) — the "No committed automated test" caveat from section 7 is now closed for the wizard half.** `e2e/workflow-wizard.spec.ts` (9 tests) is committed and passing, and the full existing FE Playwright suite was re-run in isolation and root-caused via `git stash` -- 80/89 passed, the 9 failures confirmed pre-existing/unrelated to this feature. The widget half's click-through (section 7's other open item) remains unattempted by this pass -- unchanged. See Verification Plan section 8 for commands and detail.

This is the front-end half of a cross-app feature. The backend half is
**BE Feature 25** ([../../invoice-be/docs/feature_25_plug_and_play_workflows.md](../../invoice-be/docs/feature_25_plug_and_play_workflows.md)),
and as of 2026-08-30 **every backend gap in it is built** — 335 (dual-credential
auth + two-tier API-key scope), 336 (`TenantWorkflowConfig` +
`GET`/`PUT /api/v1/settings/workflow`), 337 (role vocabulary), 338 (Drive
write-back), 339 (email summary), 340 (sandbox keys), 341 (widget token) and 342
(provisioning completion). The paragraph this replaced said 338/339/340/341 were
unbuilt; that was true when Gaps 323/324 shipped earlier the same day and stopped
being true within hours, which is itself the reason this document re-states
backend status with a date rather than as a standing fact.

**The sandbox-key half of FE Gap 325 is deliberately not built here.** A sandbox
`inv_test_` key (BE Gap 340) is issued to an *anonymous website visitor with no
login*; a signed-in Settings screen is structurally the wrong surface for it. It
belongs to `invoice-website`'s own flow and is tracked there.

---

## Ground truth at build time

Verified against the real code on 2026-08-30, before writing any of this feature's
code. Recorded because several of these are the kind of fact that goes stale, and
two of them contradicted the brief this work started from.

* **The website Multi-Zone proxy already whitelists `settings`.**
  `apps/invoice-website/next.config.js:56`'s `feApiPrefixes` array contains
  `"settings"`, and line 15's `fePages` contains `"settings"` too, so both
  `/api/settings/workflow` and the `/settings/workflows` page rewrite to the FE
  zone with no website change. The website's own `app/api/` has `auth`, `billing`,
  `contact` and `v1` only — no `settings` folder — so there is no shadowing route
  of the kind that forced the explicit `/api/billing/usage` rewrites at lines
  68–69. **Checked, not assumed**: this exact class of omission caused three real
  404s already (FE Gap 321, Website Gap 187, Website Gap 130). No file under
  `apps/invoice-website` was modified by this feature.

* **`GET /settings/workflow` is Admin-only, unlike `GET /settings/vendor-flow`.**
  `routers/settings.py::_require_admin_for_workflow()` gates *both* verbs on
  `context.role != "Admin"` → 403. A non-Admin therefore cannot even read the
  config, which is what forces the first-run banner (below) to be Admin-gated
  client-side before it fetches anything — otherwise every non-Admin session would
  fire a guaranteed 403 on every page load.

* **The response carries a sixth field the brief did not mention: `api_key_scope`.**
  `WorkflowConfig` is `input_channels`, `audit_policy`, `output_destinations`,
  `chat_access`, `completed_at` **and `api_key_scope`** — the enforcement primitive
  the policy maps onto, surfaced read-only. The wizard displays it on the review
  step so an Admin can see the actual consequence of the policy choice rather than
  inferring it from marketing wording.

* **`audit_policy` is derived from `Tenant.api_key_scope` on read, not read back
  from the config row** (`_workflow_response()`). Consequence for the FE: after a
  save, the value the server returns is authoritative and can legitimately differ
  from what was sent if the column was changed underneath. The page therefore
  re-seeds its whole form state from the PUT response instead of keeping local
  state as the truth.

* **The API value really is `full_automation`, not `full_auto_pilot`.**
  `AUDIT_POLICY_FULL_AUTOMATION = "full_automation"` /
  `AUDIT_POLICY_STRICT_REVIEW = "strict_review"`. The founder's spoken name "Full
  Auto-Pilot" is deliberately **not** the wire value — Feature 13 already ships a
  "Tenant Autopilot" that means scheduled Google Drive sync and is configured from
  the same Settings area. The naming collision is flagged and unresolved in BE
  Feature 25; this UI uses "Full Automation" in copy to match the value it sends,
  and does not invent a third name.

* **`chat_access: "widget"` is accepted by the API** (`WORKFLOW_CHAT_ACCESS =
  ("dashboard", "api", "widget")`) even though the widget token is BE Gap 341 and
  unbuilt — BE Feature 25 records that as a deliberate asymmetry against the
  rejected destinations. So the widget option is *storable* but does nothing. That
  is a worse trap than a 422, not a better one, and drives the FE treatment below.

* **`RoleMapper` (BE `models.py:850–888`)**: `NO_ROLE = "Restricted"`,
  `USER_FACING_ROLES = ("Admin", "Auditor", "Trainer")`, and
  `ROLE_PERMISSION_DEFAULTS` is Admin `(train, audit, load)` = all true, Trainer =
  `(True, False, False)`, Auditor = `(False, True, False)`, `NO_ROLE` = all false.
  The FE's Security page role matrix disagreed with **three** of those rows, not
  just the retired one — see Gap 324 below.

* **`app/settings/page.tsx`'s `INTEGRATIONS` array had 6 entries**, not the 5–6 the
  brief hedged on: Connectors, Email Setup, Admin Console (`adminOnly`),
  Subscriptions, Webhooks, Security. Workflows is added as a 7th, `adminOnly`.

### Added for FE Gap 325 (widget tokens), verified 2026-08-30 before writing its code

Two of these contradicted the shape the work was scoped from, and both changed
what got built.

* **There is no endpoint that updates a widget token.** `routers/settings.py`
  exposes exactly `GET` / `POST` / `DELETE` on
  `/security/widget-tokens[/{id}]` — no `PATCH`, no `PUT`. `allowed_origins` is
  written once by `services/widget_tokens.py::issue_widget_token()` and never
  edited afterwards. So "set **or update** the allowed origin domain" is only
  half-satisfiable: the field is offered at issue time, and changing it means
  issuing a new token and revoking the old one. The UI says exactly that rather
  than rendering an edit control with nothing to call.

* **There is no embeddable JavaScript bundle, anywhere.** `routers/widget.py`
  serves one route, `POST /api/v1/widget/chat/message`, returning JSON. There is
  no `<script>` to paste, no rendered chat bubble, no static mount — confirmed by
  a repo-wide grep for `widget.js` / `widget-loader` / `embed.js` / `StaticFiles`
  across both apps, which returns **nothing**. BE Feature 25's own Gap 341
  section says the same in its "Not done, and not claimed" list. The embed panel
  is therefore a real HTTP call the tenant wires into their own UI, and the copy
  says so in those words instead of implying a drop-in widget.

* **A tenant may hold several widget tokens** (`MAX_TOKENS_PER_TENANT = 10`, a
  409 past that), because `WidgetToken` is its own table rather than a third
  credential in `Tenant.api_key_*`. That is why this renders as a list with
  per-row revoke, not as the single rotate-in-place control the API key uses.

* **All three verbs are Admin-only, the `GET` included** — same shape as the
  workflow endpoint, and for the same stated reason: `allowed_origins` is
  security configuration. So the component checks the role before fetching.

* **`WidgetTokenSummary` carries no field that could hold the token.** `id`,
  `label`, `token_prefix`, `masked_token`, `allowed_origins`, `created_at`,
  `last_used_at`. Only `WidgetTokenCreateResponse` adds `widget_token`.

* **Origin pinning's limits are a hard constraint on the copy, not a style
  preference.** `services/widget_tokens.py`'s module docstring states that
  `curl -H 'Origin: https://acme.com'` is the entire bypass and that nothing "in
  this module, its callers, or the product documentation may describe it as a
  guarantee". BE Gap 341 additionally ships
  `test_origin_pinning_is_bypassable_outside_a_browser`, which *passes by
  demonstrating the bypass*. The UI wording below is written to that constraint.

* **An empty `allowed_origins` disables the check rather than denying
  everything** (`origin_is_allowed()` returns True on an empty list), so the
  UI must not present the field as required — a token with no origins is
  usable, by design.

---

## File Coordinates (as built)

### New

* `app/settings/workflows/page.tsx` → `WorkflowSettingsPage` (default export), with
  `STEPS`, `INPUT_CHANNELS`, `AUDIT_POLICIES`, `OUTPUT_DESTINATIONS`,
  `CHAT_ACCESS_OPTIONS` option tables, the `WorkflowConfig` /
  `WorkflowConfigDraft` interfaces, `errorMessage()`, `OptionCard`, `StepDots`.
* `app/api/settings/workflow/route.ts` → `GET`, `PUT` (both `proxyJson`),
  `export const dynamic = "force-dynamic"`.
* `components/settings/WorkflowSetupBanner.tsx` → `WorkflowSetupBanner` (default
  export) — the first-run trigger.

### New — FE Gap 325 (widget tokens)

* `components/settings/WidgetTokenSection.tsx` → `WidgetTokenSection` (default
  export, props `{ isAdmin, authLoading? }`), with the `WidgetTokenSummary` /
  `WidgetTokenCreateResponse` interfaces and the module-local `errorMessage()`,
  `formatTimestamp()`, `parseOrigins()`, `embedSnippet()` helpers.
* `app/api/settings/security/widget-tokens/route.ts` → `GET`, `POST` (both
  `proxyJson`), `export const dynamic = "force-dynamic"`.
* `app/api/settings/security/widget-tokens/[tokenId]/route.ts` → `DELETE`
  (`proxyJson`), `RouteParams`, `force-dynamic`.

### Modified — FE Gap 325

* `app/settings/security/page.tsx` → imports and renders `<WidgetTokenSection>`
  between the API-key card and the Tenant Isolation card. Nothing else on that
  page changed.
* `app/settings/workflows/page.tsx` → `CHAT_ACCESS_OPTIONS`'s `widget` entry
  loses `unavailable` and gains `configuredAt`; new `WIDGET_TOKENS_URL`,
  `widgetTokenCount` state and `loadWidgetTokenCount()`; the step-4 advisory
  block; a widget branch in `QuickStartSnippets`; and three stale-copy
  corrections (the module docstring's item 3, step 3's "Two of these", step 4's
  "or eventually from a widget").

### Modified

* `app/settings/page.tsx` → the `INTEGRATIONS` array gains the `workflows` entry
  (`adminOnly: true`); the `IntegrationTile` doc comment's role vocabulary.
* `components/layout/Shell.tsx` → renders `<WorkflowSetupBanner />` between
  `<Header />` and `<main>`.
* `app/settings/security/page.tsx` → `roleMatrix` rebuilt from the backend's real
  `ROLE_PERMISSION_DEFAULTS`; the Active Role tile's display fallback.
* `app/help/content/settings-guide.tsx` → the three-role list in section 1.
* `app/admin/page.tsx` → one historical comment's role vocabulary.
* `e2e/rbac-sidebar.spec.ts` → 7 identity stubs, 1 describe-block title, and a
  new block comment explaining why the literal moved.

### Deliberately NOT touched

* Anything under `apps/invoice-be` or `apps/invoice-website` — separately owned.
* `lib/backendProxy.ts:83-84`'s comment, and `app/admin/page.tsx`'s /
  `fe_features_tracker.md`'s historical narrative about the Clerk-template bug that
  produced `role="Viewer"` rows in Postgres. Those describe what really happened at
  the time; rewriting them would make an incident record wrong. Only *live
  vocabulary* moved, not history.
* `docs/test_coverage_map.md`, its `test_evidence/`, and
  `tests/manual/test_settings_service_flow.md` (whose Test 7 still says to
  hard-code the role to `"Viewer"`) — functional-tester-owned, following the
  precedent FE Gap 322 set for exactly these paths. Flagged, not edited. Note the
  mock bearer token `test_viewer` that doc also names is still valid: BE Gap 337
  deliberately kept that token spelling and added `test_restricted` alongside it.
* ~~Sandbox / widget credential UI — that is FE Gap 325, explicitly next, and depends
  on BE Gaps 340/341 which do not exist.~~ **Superseded 2026-08-30**: BE Gaps
  340/341 both landed, and the **widget** half of FE Gap 325 is built (above).
  The **sandbox** half remains deliberately unbuilt in this app — see the header:
  it is an anonymous-visitor credential and belongs to `invoice-website`.

---

## Functionality

### FE Gap 324 — the role vocabulary

BE Gap 337 retired "Viewer" as an assignable role. The three user-facing roles are
**Admin, Auditor, Trainer**; `RoleMapper.NO_ROLE` (spelled `"Restricted"`) is the
internal zero-permission fallback and is deliberately excluded from
`USER_FACING_ROLES` so it can never appear in a picker.

**The Security page's role matrix was wrong in three ways, not one.** It listed
Admin / Auditor / **Loader** / **Viewer**, and gave Auditor `train: true`. Against
the backend's real `ROLE_PERMISSION_DEFAULTS`: "Loader" is not a role at all (it is
the *permission* `can_load`, grantable per user from the Admin Console), Auditor has
`can_train=False`, and Trainer — a real role since before this feature — was missing
entirely. The table is now the three real roles with the real defaults:

| Role | Ingest (`can_load`) | Audit (`can_audit`) | Trainer (`can_train`) | Settings |
|---|---|---|---|---|
| Admin | ✓ | ✓ | ✓ | ✓ |
| Auditor | — | ✓ | — | — |
| Trainer | — | — | ✓ | — |

A footnote under the table records the thing the table itself cannot show: these are
role *defaults*, and an Admin can grant `can_load`/`can_audit`/`can_train`
individually from the Admin Console, so a specific user's effective permissions can
exceed their role's row.

**The display fallback reads "Unassigned", not "Restricted".** `useAuth()` returns
`role: ""` while identity is loading or when the lookup failed, and the backend can
now genuinely return the literal `"Restricted"` for an unmapped IDP role string, an
org-mismatch clamp, or a first-login clamp. Rendering `"Restricted"` verbatim in the
"Active Role" tile would read as a punishment to a user whose only problem is that
nobody has assigned them a role yet. Both cases therefore render **"Unassigned"** —
a neutral, accurate description of the same state — and the tile carries a one-line
explanation that no role is assigned yet and an Admin can assign one. The mapping is
a named constant (`UNASSIGNED_ROLE_LABEL`) with the reasoning in a comment, so the
next person to see "Restricted" in an API response can find why it is not shown.

`loading` from `useAuth()` is checked **separately** from `!role`, and that
distinction was added because a live run caught the tile telling an *Admin* they
had no role assigned for as long as `/auth/me` took to answer. While identity is
in flight the tile renders a neutral placeholder and no explanatory line; only a
resolved-and-empty or resolved-and-`"Restricted"` role produces "Unassigned". The
original `{role || "Viewer"}` had the same flaw and said something worse.

**Help copy** (`app/help/content/settings-guide.tsx`) named Admin / Auditor /
Viewer. It now names Admin / Auditor / **Trainer**, describes Trainer's actual
capability (authoring extraction rules in the AI Trainer, with no audit or approval
rights), and adds an explicit line that Dashboard, Chat and Help are available to
every member including one with no role assigned yet — mirroring the same correction
BE Gap 337 made to the live support chatbot's knowledge base, so the two customer-
facing surfaces cannot disagree.

**The e2e stubs** in `e2e/rbac-sidebar.spec.ts` used `role: "Viewer"` in 7 places to
mean "an identity with no permissions". The literal is now `"Restricted"`, which is
what the backend actually returns for that state — the point of the change is that
the stub keeps describing reality. Two describe-block titles that called this "the
design's Viewer" were reworded. **The stubs' behaviour is unchanged**: `useAuth()`
reads the three permission booleans straight off `/auth/me` and never derives them
from the role string, so these specs never depended on the literal's value. That is
also why this edit is safe without a Playwright run — but see the Verification Plan
for what that does and does not license.

### FE Gap 323 — the Setup Wizard

**Four steps, the founder's own definition.** Each is a card of large clickable
options; multi-select steps are checkboxes semantically (`role="checkbox"`),
single-select are radios (`role="radio"` in a `role="radiogroup"`).

1. **Input channels** — Email / Google Drive / Direct API / Manual upload.
   Multi-select. All four are live: email is Feature 14, Drive is Feature 13's sync,
   manual is the upload UI, and API became real when BE Gap 335 landed. Each option
   names where it is configured (e.g. Drive → Settings → Connectors) so the wizard
   is a map of the product, not a dead-end form.

2. **Audit policy** — single-select, two options, and the copy makes the *actual*
   consequence unambiguous rather than restating the label:
   * **Full Automation** (`full_automation`) — "your API key can approve, reject,
     verify, confirm-send and mark-paid on its own, with no human step." A caution
     line states plainly that this widens what a leaked key can do.
   * **Strict Review** (`strict_review`) — "the key stays read- and upload-only. A
     human finalises every invoice in this app, no matter how it arrived."
   The step also shows the resulting `api_key_scope` (`actions` / `readonly`)
   inline, because that is the column the auth layer actually enforces, and a
   sentence naming the Feature 13 "Autopilot" collision explicitly: this setting has
   nothing to do with scheduled Drive sync.

3. **Output destinations** — Email summary / Google Drive archive / Webhook /
   Dashboard only. Multi-select. **Email summary and Drive archive are disabled**
   with a "Not available yet" pill naming the gap that will build each (BE Gap 339 /
   BE Gap 338). They cannot be selected, so a user cannot lose a selection on save.
   The two available options carry the same "where this is configured" pointer as
   step 1 (webhook → Settings → Webhooks).
   * The disabled treatment is **belt and braces, not a replacement for handling the
     422**: `handleSave()` still surfaces the backend's own `detail` string verbatim
     in the error banner, and — critically — **does not clear the user's selections**
     on a failed save. If the two ever diverge (a newer backend, a stale bundle,
     someone driving the API by hand), the user sees the real reason and still has
     their draft. The backend message already names the destination, the gap, and
     what *is* available, which is why it is shown rather than replaced with a
     generic string.

4. **Chat access** — Our dashboard / API / Embeddable widget. Single-select.
   Dashboard needs no backend; API works via BE Gap 335. **The widget is disabled**
   with the same "Not available yet" pill (BE Gap 341). This is a deliberate
   divergence from what the API permits: `chat_access: "widget"` is *accepted and
   stored* by the backend and has no runtime effect whatsoever. Letting a user pick
   it would produce a green "Saved" toast for a feature that does not exist, with no
   422 to correct the impression — strictly worse than the destinations case, where
   the backend at least refuses. Disabling it is the only honest option available to
   the FE, and the option row says why rather than being silently greyed out.

**Save & Activate** clears any previous success state (found live: a failed second
save otherwise left "Workflow activated" sitting above the failure message, claiming
both at once), then issues one `PUT /api/settings/workflow` with all four fields,
then re-seeds every piece of form state from the response body — including
`audit_policy` and `api_key_scope`, which the server derives rather than echoes. On
success the page switches to a summary/confirmation state showing what is now in
force plus an "Edit workflow" affordance; the wizard is re-editable at any time from
Settings → Workflows.

**Review step.** Before the save there is a fifth screen (a review, not a
question — hence "4 steps" is still accurate and the step indicator shows 4) listing
every choice, the resulting `api_key_scope`, and the fact that unavailable options
were not included. Step navigation is Back/Next with a `role="tablist"` step
indicator whose tabs are clickable, matching `app/settings/security/page.tsx`'s
existing tab pattern; no step blocks progress, because every field is optional on
the backend and an empty list is a legitimate answer.

**Loading and permission states.** The page renders the shared
`usePageHeader({ title, subtitle, backHref: "/settings" })` header in every state,
including the loading and Access-Restricted early returns — the same ordering
`app/settings/webhooks/page.tsx` uses, so the shared header still names the screen
when the body is a gate. Non-Admins get the same Access Restricted panel the other
Admin-gated settings screens use, because `GET /settings/workflow` would 403 anyway.

**First-run trigger.** `components/settings/WorkflowSetupBanner.tsx`, mounted in
`Shell.tsx` between the header and the page body:

* Renders **only** when `useAuth()` has finished loading and `role === "Admin"` — a
  non-Admin cannot read the endpoint (403), so firing the fetch for them would be a
  guaranteed error on every page load.
* Fetches `/api/settings/workflow` once per tab (module-level cache + shared
  in-flight promise, the same shape `hooks/useAuth.ts` uses) and renders only if the
  response is OK **and** `completed_at === null`. Any failure — network, 403, 402,
  a non-JSON body — renders nothing. It fails closed to silence: an ops problem must
  not turn into a banner on every screen.
* Hides itself on `/settings/workflows` (you are already there) and is dismissible
  for the session via `sessionStorage`, so it prompts rather than nags. Completing
  the wizard sets `completed_at` server-side, so it never returns.

**Why a banner and not a forced redirect — a deliberate deviation, recorded.** The
brief called for a "first-login trigger". A redirect out of whatever route the user
landed on would fight deep links, is hostile to an Admin who signed in to do
something else, and — concretely — would make the outcome of several existing
Playwright specs depend on whether a backend happened to be running and what that
tenant's `completed_at` held. The banner is the same trigger without those
properties: it appears for exactly the population the wizard is for, on first login,
until the wizard is completed. If the founder wants a hard redirect, that is a
one-line change in this component and should be a deliberate decision, not a side
effect of this build.

**Proxy route.** `app/api/settings/workflow/route.ts` is `proxyJson(request,
"/settings/workflow")` for both verbs plus `export const dynamic = "force-dynamic"`,
matching `app/api/settings/service-flow/route.ts` exactly. `proxyJson` forwards the
status code and body untouched, which is what makes the backend's 422 `detail`
string reach the UI at all — no error-shape translation happens anywhere in the
path. The page uses bare `fetch("/api/settings/workflow")`, not `lib/apiClient.ts`,
matching every other settings screen.

### FE Gap 325 (widget half) — the chat widget token UI

**Where it lives, and why it is its own card.** Settings → Security, directly
under the API key. Both are programmatic credentials, but a widget token is a
*different credential in a different table at a different trust level*: published
in a customer's page source, chat-only, carrying no role and no permission
booleans (BE Gap 341's `WidgetContext` has four fields and none of them is a
permission). Rendering it as another row of the API-key panel would imply the two
are variants of one thing. It is a separate `<section>` with its own heading.

**A list, not a rotate-in-place control.** `Tenant.api_key_*` is one key per
tenant, so the API-key card rotates. `WidgetToken` is its own table with up to
`MAX_TOKENS_PER_TENANT = 10` rows, because a tenant may embed on several sites
and revoking the marketing site's token must not break the docs site's. So this
renders every live token with its own per-row revoke.

**What the copy says about what this credential can reach — including the part
that is still sensitive.** Two paragraphs, always visible:

1. It reaches **one endpoint** and nothing else; it cannot upload, read, approve,
   export or change anything, and it is not an API key.
2. It is *designed* to be published, so treat it as public — **and anyone who
   reads it can ask the assistant questions whose answers come from this
   workspace's real invoice data.**

The second half of point 2 is the honest part that "it's weaker than an API key"
elides. `POST /widget/chat/message` runs `routers/chat.py::run_sync_chat_turn()`
— the *same* turn the dashboard runs, against the tenant's own invoices. "Weaker
than an API key" is true and is not the same as "harmless", and a tenant deciding
where to paste this needs the second sentence, not just the first.

**Generate.** A form with a label and an optional domains field, posting to the
real endpoint. On 201 the raw token is shown **once**, in an emerald panel
matching the API-key reveal's exact treatment, with a copy button, a dismiss
button, and the literal warning that it cannot be retrieved again — literal
because the backend stores a PBKDF2 digest and genuinely cannot re-issue it. A
second issue clears any previously revealed token first: two raw values on screen
at once, only one of them new, is how the wrong one gets pasted into a live site.
A failed create **keeps the form contents** — the Admin's typed domains must
survive a rejected request, the same rule the wizard's save follows.

**The origin field, and copy written to a hard constraint.**
`services/widget_tokens.py` forbids describing origin pinning as a guarantee
anywhere, including to a customer. The field's help text therefore says, in this
order: it is *one defensive layer, not a lock*; browsers set `Origin` and page
scripts cannot change it, so it **does** stop a copied token being reused from a
different website; it stops **nothing** outside a browser, because anything that
can send an HTTP request can set that header by hand; and leaving it empty means
the check is not applied at all. Nothing in the UI says "locked to your domain".

No client-side origin validation is performed. `normalize_origin()` on the
backend is the definition of a usable origin, and re-implementing that rule in
TypeScript would give two answers to one question — the client's being the wrong
one the first time the backend's changed. The 422 is surfaced verbatim instead;
it already names the exact required form.

**Updating the domains is honestly impossible, and the UI says so.** There is no
`PATCH`. Rather than render an edit control with nothing to call, the form and
the row both state that domains are fixed at issue time and that changing them
means issuing a new token and revoking the old one. This is a real limitation of
the backend surfaced as copy, not a UI shortcut.

**Revoke is two-step.** The backend stamps `revoked_at` and checks it on every
resolve, so there is no grace period and no undo. The confirm panel names the
token, states that any site using it stops working **on its very next request**,
and that it cannot be restored.

**Embed instructions — the honest answer, not the expected one.** There is no
embeddable JavaScript bundle: `routers/widget.py` serves one JSON route and
nothing static (grep-verified, and BE Gap 341 says the same). So the panel — only
rendered once a token exists — leads with *"There is no drop-in script or
ready-made chat bubble to paste yet"* and then gives a real, copyable `fetch`
against `POST /api/v1/widget/chat/message`, including the `session_id` echo-back
comment that makes a follow-up message keep its context. It targets the backend
host directly rather than this app's `/api/...` proxy, because a widget runs on
the tenant's own domain and those proxy routes authenticate with *this* app's
Clerk session cookie; BE Gap 341's `WidgetCORSMiddleware` is what makes the
cross-origin call work.

**Admin gating, with "loading" kept distinct from "not an Admin".** All three
endpoints are Admin-only including the `GET`, so the component skips the fetch
entirely for a non-Admin rather than firing a guaranteed 403 on every page load.
It takes `authLoading` as an explicit prop: this is the exact failure FE Gap 324
fixed one card down on the same page, where `role === ""` during `/auth/me` made
an Admin briefly look like a non-Admin. Telling someone "only Administrators can
manage these" for the duration of a network round trip is wrong, so the two
states render differently.

**The wizard's step 4 is now enabled, with a live advisory.** The `widget` option
loses its "Not available yet" pill and gains a `configuredAt` pointer to Settings
→ Security, matching what `email`/`api` already do. It is enabled
**unconditionally rather than gated on a token existing**: `chat_access` is a
stated preference that promises no delivery — the distinction BE Gap 336 recorded
against the rejected output destinations — and the wizard is precisely where a
tenant discovers they need a token. Blocking it would force an Admin to leave,
issue a credential for a feature they have not chosen yet, and come back.

Instead the step fetches the token list and, when the tenant has **zero** tokens
and has selected `widget`, shows an amber note saying nothing will work on their
site until they issue one, that the answer still saves fine, and where to go.
`widgetTokenCount` is `null` when unknown and the note renders only on a real
`0`: a failed fetch must not tell an Admin they have no token. The fetch fails
silently and never blocks the wizard's own loading state.

`QuickStartSnippets` gains a matching widget `curl`, and its footer now names
both placeholders and states plainly that they are two different credentials —
the widget token is chat-only and meant to be published, the API key is not.

**Three stale-copy corrections in the same file**, recorded rather than done
silently: the module docstring's item 3 and step 3's *"Two of these are still
being built"* both still described `email_summary` as unbuilt (BE Gap 339 made it
selectable earlier the same day, leaving only `drive_archive`), and step 4's
subtitle said chat would work from a widget *"eventually"*. All three are the
same "not available yet" mechanism this gap is changing one step along, and a
count the user can see is wrong reads as carelessness about the rest of the claim.

**Sandbox keys are deliberately absent.** No `inv_test_` UI was built anywhere in
`invoice-fe`. That credential belongs to an anonymous visitor with no login, and
a signed-in Settings screen is the wrong surface for it.

---

## Tasks

- [x] **Task 17.1 (FE Gap 324): role vocabulary.** Security page role matrix rebuilt
      from the backend's real `ROLE_PERMISSION_DEFAULTS` (dropped the retired Viewer
      row *and* the non-existent "Loader" row, corrected Auditor, added the missing
      Trainer); Active Role tile falls back to "Unassigned" for both `""` and the
      backend's `"Restricted"`; help-centre role list corrected to
      Admin/Auditor/Trainer; 7 e2e identity stubs and 1 describe title moved to
      `"Restricted"`; 2 code comments de-Viewered. Historical incident records and
      functional-tester-owned test docs deliberately left alone.
- [x] **Task 17.2 (FE Gap 323): the Setup Wizard.** `app/settings/workflows/page.tsx`
      (4 steps + review + saved state), `app/api/settings/workflow/route.ts`
      (GET/PUT via `proxyJson`), the `Workflows` tile added to `settings/page.tsx`'s
      `INTEGRATIONS` array as an `adminOnly` entry, and
      `components/settings/WorkflowSetupBanner.tsx` mounted in `Shell.tsx` as the
      first-run trigger. Unbuilt options (email summary, Drive archive, widget)
      disabled with a gap-naming "Not available yet" pill; the backend's 422 `detail`
      surfaced verbatim without discarding the user's draft.
- [x] **Task 17.3 (FE Gap 325, widget half): the chat widget token UI.**
      `components/settings/WidgetTokenSection.tsx` rendered in Settings → Security
      (list / generate with shown-once reveal / issue-time origin field /
      two-step revoke / honest embed instructions), plus the two proxy routes
      `app/api/settings/security/widget-tokens/route.ts` (GET, POST) and
      `.../[tokenId]/route.ts` (DELETE). The wizard's `widget` chat-access option
      is enabled with a `configuredAt` pointer and a live "no token issued yet"
      advisory. Verified by a 30-check browser click-through against a real local
      stack.
- [ ] **Task 17.4 (FE Gap 325, sandbox half): sandbox `inv_test_` key UI.**
      **Not in this app, by design** — an anonymous-visitor credential does not
      belong on a signed-in Settings screen. Owned by `invoice-website`; left
      unchecked here so the split is visible rather than looking forgotten.

---

## Dependencies outside this feature

* **BE Feature 25** owns the endpoint, the policy vocabulary, and the role model.
  Every string this UI sends (`full_automation`, `strict_review`, the four input
  channels, the two available destinations, the three chat-access values) is defined
  in `routers/settings.py`, not here. If those constants change, this page breaks
  loudly (422 with a message naming the allowed set), not silently.
* **Feature 10 — Settings** owns `app/settings/page.tsx` and the tile grid this adds
  a row to; the `IntegrationTile` shape is unchanged.
* **Feature 1.1 — Granular RBAC** owns the role model Gap 324 realigns to. No
  permission logic changed on the FE — only the words shown for it.
* **Feature 13 — Tenant Autopilot** — naming collision only, called out in the
  wizard copy so a user configuring both does not conflate them.

---

## Verification Plan

Filled in after the runs below actually happened.

### 1. Typecheck — clean

```
npx tsc --noEmit
-> exit code 0, no output
```

Run from `apps/invoice-fe` after the full pass, covering both gaps.

### 2. Website Multi-Zone proxy — verified by reading the real config, no change needed

`apps/invoice-website/next.config.js:56` `feApiPrefixes` already contains
`"settings"`, and `:15` `fePages` already contains `"settings"`. The website's own
`app/api/` directory holds `auth`, `billing`, `contact`, `v1` — no `settings` entry,
so nothing shadows the rewrite the way `/api/billing` did. Both
`/api/settings/workflow` and `/settings/workflows` therefore reach the FE zone
already. No file under `apps/invoice-website` was touched.

### 3. HTTP calls against the real endpoint — real FastAPI, real local Postgres

Local backend started for this (`uvicorn main:app`, `ALLOW_MOCK_AUTH=true`,
`DATABASE_URL=postgresql://.../invoice_db` on port 5433 — real Postgres, not
SQLite). Called directly, with `Bearer test_admin`:

```
GET  /api/v1/settings/workflow            -> 200
  {"input_channels":[],"audit_policy":"strict_review","output_destinations":[],
   "chat_access":"dashboard","completed_at":null,"api_key_scope":"readonly"}

PUT  (the exact body the page sends)      -> 200
  {"input_channels":["email","api"],"audit_policy":"full_automation",
   "output_destinations":["webhook","dashboard_only"],"chat_access":"api",
   "completed_at":"2026-08-30T05:39:40.226121","api_key_scope":"actions"}

PUT  output_destinations=["email_summary","webhook"]  -> 422
  {"detail":"These output destinations are not available yet and were not saved:
    email_summary — BE Gap 339 (emailed run summary). Available now: webhook,
    dashboard_only."}

PUT  output_destinations=["drive_archive"]            -> 422  (names BE Gap 338)
GET  as Bearer test_restricted                        -> 403
  {"detail":"Only Admin users can view or modify workflow settings."}
GET  after the rejected PUTs -> unchanged from the last successful save
```

So: the six-field response shape the TS interface declares is the real one; the
write-through to `api_key_scope` really happens (`full_automation` → `actions`);
a rejected PUT really leaves state untouched; and the GET really is Admin-gated,
which is what the banner's client-side role check exists for.

### 4. The same calls through the new FE proxy route — real Next dev server

`next dev` with `BACKEND_API_URL=http://127.0.0.1:8000`, hitting
`/api/settings/workflow` (not the backend directly):

```
GET  /api/settings/workflow  -> 200 application/json  (same body as above)
PUT  valid                   -> 200 application/json
PUT  ["email_summary","drive_archive","webhook"]
                             -> 422 application/json
   detail: "...drive_archive — BE Gap 338 ...; email_summary — BE Gap 339 ...
            Available now: webhook, dashboard_only."
```

The 422 arrives with `content-type: application/json` and a `detail` string,
which is exactly the contract `errorMessage()` requires to show it verbatim
rather than falling back to a generic message. `proxyJson` passes status and body
through untouched, confirmed observationally rather than assumed.

### 5. Live click-through in a real browser (headless Chromium, real stack)

Real dev server → real proxy route → real FastAPI → real Postgres. No stubbed
responses anywhere. Sequence and result:

1. `/dashboard` with `completed_at` null → **first-run banner rendered**
   ("Finish setting up your workspace…"), sitting under the shared header
   without disturbing the page canvas.
2. "Set up workflow" → navigated to `/settings/workflows`; the banner correctly
   renders nothing on the wizard route itself.
3. Step 1 multi-select: `aria-checked` = `email=true, drive=false, api=true,
   manual=true` after three clicks.
4. Step 2: selecting Full Automation rendered "Resulting API key scope: actions".
5. Step 3: `email_summary` and `drive_archive` both `aria-disabled="true"`, and
   **still `aria-checked="false"` after a forced click** — they genuinely cannot
   be selected, not merely styled as if.
6. Step 4: `widget` likewise `aria-disabled="true"` and unselectable under a
   forced click.
7. Review → **Save & Activate → 200**, "Workflow activated … Your API key scope
   is now `actions`".
8. **The 422, with a real backend rejection**: the PUT body was rewritten in
   flight to include `email_summary` (the disabled control means the UI cannot
   produce that body itself). Nothing about the *response* was faked — the real
   backend answered 422 and the UI rendered its message verbatim:
   *"These output destinations are not available yet and were not saved:
   email_summary — BE Gap 339 (emailed run summary). Available now: webhook,
   dashboard_only."* plus "Nothing was saved and your answers above are
   unchanged". The review panel still listed all four answers afterwards — the
   draft survived the rejection, as designed.
9. Back on `/dashboard` after completion → banner count 0.

**One real bug was found by this run and fixed.** On the first pass, the failed
save at step 8 left the green "Workflow activated" banner from step 7 sitting
directly above the red failure message — the screen claimed both at once.
`handleSave()` now clears `justSaved` before issuing the request; re-run
confirmed the success banner is gone while the error is shown. This is exactly
the class of thing a typecheck cannot catch, and is why the click-through was
worth doing.

**The Gap 324 surfaces were rendered in the same run.** `/settings/security`
showed the role matrix as exactly `Admin (ingest/audit/trainer/settings)`,
`Auditor (audit only)`, `Trainer (trainer only)` — read out of the live DOM,
matching `ROLE_PERMISSION_DEFAULTS` row for row. The Active Role tile showed
**"Admin"** for an Admin identity and **"Unassigned"** plus the explanatory line
for an identity where `/auth/me` genuinely returned `role="Restricted"` (a
`Bearer test_restricted` header, forwarded by `backendProxy` and resolved by the
real backend — not a stub). `/settings/workflows` as that same non-Admin
identity rendered the Access Restricted panel rather than the wizard.

**A second real bug was found there and fixed.** The first pass showed
**"Unassigned" for the Admin too**: while `/auth/me` is in flight `useAuth()`
returns `role: ""`, so the tile told an Admin they had no role assigned for as
long as identity took to load. "Still loading" and "genuinely has no role" are
different answers and were sharing a label. The tile now checks `loading`
separately and renders a neutral placeholder while identity resolves; re-run
confirmed "Admin". The original `{role || "Viewer"}` had the same flaw — it just
said something worse while loading.

**Local database state was restored afterwards.** The probe tenant
(`00000000-…`) was reset to its observed pre-test state: `tenant_workflow_configs`
row deleted, `tenant.api_key_scope` back to `readonly` (verified by query, not
assumed). Both dev servers were stopped.

### 6. FE Gap 325 — typecheck, production build, live HTTP, and a real click-through

**Typecheck.** `npx tsc --noEmit` → exit 0, no output.

**Production build.** `npx next build` → exit 0, `✓ Compiled successfully`, and
its route table lists both new handlers, which is what proves they are
structurally valid route files and not just type-clean source:

```
├ ƒ /api/settings/security/widget-tokens
├ ƒ /api/settings/security/widget-tokens/[tokenId]
```

**Live HTTP against the real endpoints** (real FastAPI, real local Postgres on
5433 — not SQLite; `ALLOW_MOCK_AUTH=true`), through the **new FE proxy routes**
rather than against the backend directly:

```
GET    /api/settings/security/widget-tokens   (Bearer test_admin)      -> 200 []
POST   .../widget-tokens                                               -> 201
   {"id":"c0bd1079-…","label":"Marketing site",
    "token_prefix":"inv_widget_1pqcZx","masked_token":"inv_widget_1pqcZx...",
    "allowed_origins":["https://acme.com","https://docs.acme.com"],
    "widget_token":"inv_widget_1pqcZxfIteoClAG36qliShMs0RHBmVnQZ9KZZRuVkkE"}
GET    .../widget-tokens  -> 200, row present, `widget_token` ABSENT
       (grep for the raw value in the list response: 0 matches)
DELETE .../widget-tokens/{id}                                          -> 204, 0 bytes
GET    .../widget-tokens                                               -> 200 []
POST   .../widget-tokens  allowed_origins:["not a url at all"]         -> 422
   detail: "'not a url at all' is not a usable website origin. Use the form
            https://example.com (scheme and host, no path)."
GET    .../widget-tokens  (Bearer test_restricted)                     -> 403
   detail: "Only Admin users can manage chat widget tokens."
```

Three things this pins down beyond "the call works": the **204 passes through the
proxy as 0 bytes** rather than 500ing (the FE Gap 177 null-body path is exercised,
which matters because the backend has already committed the revoke by then); the
**origin was normalised** `https://Acme.com/chat` → `https://acme.com`, so the
decision not to validate client-side is observably correct; and the raw token is
genuinely absent from the list response.

**Origin pinning and revocation are live, checked at the widget route itself:**

```
POST /api/v1/widget/chat/message  X-API-Key: <token>  Origin: https://evil.example
  -> 403 "This chat widget token is not registered for this website…"
POST (same, after DELETE)         Origin: https://acme.com
  -> 401 "Missing or invalid chat widget token…"
```

So the layer the UI describes actually exists, and revocation really does take
effect on the very next request — which is exactly what the confirm-step copy
promises.

**Real browser click-through — 30 checks, all passed.** Headless Chromium against
the real stack (real Next server → real proxy routes → real FastAPI → real
Postgres), no stubbed responses, identity supplied as `Bearer test_admin`
forwarded by `backendProxy`:

1. Section renders; empty state reads "No widget token issued yet — generate one
   to embed chat on your own site."; the embed panel is **absent** while no token
   exists; the capability copy names the one-endpoint limit, the "treat it as
   public" warning **and** the "answers come from real invoice data" warning.
2. The origins field's copy contains "one defensive layer, not a lock", "stops
   nothing outside a browser", and "cannot be edited afterwards" — i.e. the three
   claims `services/widget_tokens.py` requires and forbids overstating.
3. Generate → reveal panel shows a 54-character `inv_widget_…` value with the
   shown-once warning.
4. The list row shows a **masked** token and does **not** contain the raw value;
   `https://Acme.com/chat` is displayed normalised as `https://acme.com`.
5. Embed snippet targets the real `/api/v1/widget/chat/message` with `X-API-Key`,
   and its panel says "no drop-in script".
6. **Shown-once holds across a reload**: after `page.reload()` the raw token is
   nowhere in the DOM (`page.content()` searched for the literal), the reveal
   panel is gone, and the token row is still listed — i.e. the credential still
   exists, it just cannot be seen again.
7. Wizard step 4: the widget option is `aria-disabled="false"`, has no "Not
   available yet" pill, links to Settings → Security, and is **genuinely
   selectable** (`aria-checked` flips to `true`). No "missing token" hint while a
   token exists.
8. Revoke → the confirm step states both "stops working on its very next request"
   and "cannot be restored"; confirming removes the row and restores the empty
   state.
9. Back in the wizard with zero tokens, selecting widget now shows the advisory
   hint, including "This answer still saves fine" — advisory, not a block.

**Local database state was restored afterwards.** The two `widget_tokens` rows the
run created were deleted and the table re-queried to `0`; `tenant_workflow_configs`
was confirmed still `0` rows and every `tenant.api_key_scope` still `readonly`
(verified by query, not assumed), since the click-through never pressed Save &
Activate. Both servers were stopped.

**One diagnosis I got wrong, recorded because it cost real time.** I spent a long
stretch concluding the Next dev server was broken, because every route under
`app/api/**` returned 404 to `curl` — including a 5-line stock probe route and
routes that shipped and worked in a previous session. The dev server was fine.
`middleware.ts` calls `auth().protect()` on every non-public route, and Clerk
answers an unauthenticated **API** request with a 404 rather than a redirect. My
requests simply had no Clerk session. The fix was the escape hatch already in that
file — `DISABLE_CLERK_AUTH=true` — which is how previous sessions ran this stack
and which I should have read first. Recorded so the next person who sees a blanket
404 on `/api/**` from a terminal checks the middleware before deleting `.next`.

### 7. What is still NOT verified, and is not claimed

* **No deployed-environment run.** All of the above is local: local Postgres,
  local uvicorn, `next dev`. Nothing has been exercised against the Azure dev
  stack, and BE Feature 25's own outstanding item — `alembic upgrade head` on the
  Azure dev database, three revisions behind — still applies. Until that runs,
  this page will 500 against the deployed backend, because the table it reads
  does not exist there yet.
* **No test through the website's Multi-Zone proxy.** The whitelist was verified
  by reading the config; no request was actually made through
  `invoice-website` → `invoice-fe` → backend.
* **Mock auth, not Clerk.** The click-through ran with `ALLOW_MOCK_AUTH=true` and
  `DISABLE_CLERK_AUTH=true`, so both identities came from the mock path rather
  than a real Clerk session. The role values themselves were real (resolved by the
  backend's `RoleMapper`), and both the Admin and non-Admin renders were observed,
  but no Clerk-issued JWT was involved at any point.
* **No committed automated test.** The click-through was a throwaway script, not
  a spec added to `e2e/`. The evidence above is a run record, not a regression
  guard — a functional-tester pass that lands a real spec is the follow-up.
* **`e2e/rbac-sidebar.spec.ts` was edited and not executed.** Its stub literals
  changed; its assertions are driven by the three permission booleans rather than
  the role string, which is why the edit is low-risk. That is an argument, not a
  test result.

Additionally, for FE Gap 325 specifically:

* **No real widget chat turn was ever completed.** The two widget-route calls made
  were the 403 (unregistered origin) and the 401 (revoked token), both of which are
  answered by `get_widget_context()` *before* the handler body runs. No message
  reached `run_sync_chat_turn()`, so the agent, the quality judge and the turn
  telemetry were not exercised through this door.
* **No cross-origin browser request was made.** `WidgetCORSMiddleware` is what makes
  the embed snippet work from a customer's domain, and it was never exercised from a
  real second origin — the snippet's correctness rests on reading BE Gap 341's
  middleware, not on having run it. This is the single largest untested claim the
  new UI makes.
* **The 409 token cap was not exercised.** Reaching it needs 10 tokens; the copy
  path for it is the same `errorMessage()` the 422 went through, which was.
* **No committed automated test.** The 30-check click-through was a throwaway
  script in a scratch directory, not a spec added to `e2e/`. It is a run record,
  not a regression guard — a functional-tester pass that lands a real spec is the
  follow-up.
* **Deployed environment: still nothing.** The migration backlog noted above now
  includes `WidgetToken`'s table, so this section will error against the Azure dev
  backend until `alembic upgrade head` runs there.
* **Sandbox `inv_test_` UI does not exist in this app** and is not claimed to —
  see Task 17.4.

### 8. functional-tester pass, 2026-08-30 -- committed Playwright coverage added, full suite re-run

Additive (CONVENTIONS.md hard rule 4) -- nothing above this section was edited.
This closes the "No committed automated test" caveat section 7 recorded for both
FE Gap 323 and FE Gap 325.

**New spec:** `e2e/workflow-wizard.spec.ts`, 9 tests, stubbing every `/api/**`
call (same convention as `e2e/rbac-sidebar.spec.ts` / `e2e/gaps-282-284-286.spec.ts`
-- no live backend needed). Covers: a non-Admin gets Access Restricted with zero
calls to the workflow endpoint; step 1's multi-select (`role=checkbox`) toggles
independently; step 2's single-select (`role=radio`) and the live
"Resulting API key scope" text; step 3 confirmed against the *current* source
(not assumed from this doc) -- `drive_archive` is the only remaining disabled
option and a forced click cannot select it, `email_summary` is live and
multi-selects with `webhook`; step 4 confirmed the `widget` chat-access option is
live with no "Not available yet" pill, and the zero-token advisory banner
(`widget-token-missing-hint`) renders only when the widget-token list is
genuinely empty, not on a fetch failure; the Review step's tablist and summary;
Save & Activate PUTs the exact draft body, shows the success banner, and renders
the Quick Start panel (all three snippets) for an `api`/`full_automation` answer;
a 422 shows the backend's `detail` verbatim and leaves the draft selections
intact.

```
npx playwright test e2e/workflow-wizard.spec.ts
-> 9 passed
```

**Full existing suite re-run, isolated (`--workers=1`, alone -- see the note
below on why isolation mattered):**

```
npx playwright test --workers=1
-> 89 total, 80 passed, 9 failed
```

The 9 failures are in `audit-review-console.spec.ts` (x2),
`chat-async-queue.spec.ts` (x2), `gaps-282-284-286.spec.ts` (x2),
`group-a-layout-overflow.spec.ts` (x1) and `inbound-mark-paid.spec.ts` (x2) --
**none of them touch any file this feature modified.** Root-caused via
`git stash` on this app's whole uncommitted feature diff (verified clean before,
restored byte-for-byte after): re-running the same 5 spec files (34 tests) against
clean HEAD produced the **identical 25 passed / 9 failed**, same test names, same
failure modes. Pre-existing and unrelated, not a regression from this feature.
`e2e/workflow-wizard.spec.ts` (9/9) and `e2e/rbac-sidebar.spec.ts` (all passing,
including the 7 stubs FE Gap 324 moved to `"Restricted"`) both passed clean
inside the same full run.

**A machine-resource note, recorded because it produced two throwaway corrupted
runs before this one:** this dev machine has 8GB RAM. Running this suite
concurrently with another app's Playwright suite in a second shell exhausted it
(measured: 257MB free of 8GB, 35 orphaned `chrome.exe` + 13 orphaned `node.exe`
processes left over from two crashed passes) and produced spurious extra
failures (`help-support.spec.ts` x3, `audit-review-console.spec.ts`'s "visible
inline correction" block x5) that do **not** reproduce once the machine is
healthy and only one Playwright pass runs at a time -- confirmed by this
section's clean isolated re-run, where all of those pass. The 9 real failures
listed above are the same 9 that reproduce with the machine healthy, run alone,
run stashed, and run un-stashed -- four independent confirmations.
