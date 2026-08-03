# Gap 96 repro — Settings → Connectors "Configure" button

Real, non-headless Chromium (Playwright `headless:false`), real local stack
(Postgres + BE + FE + real Google OAuth client ID), 2026-08-03.

## The tracker's stated diagnosis is confirmed wrong
`app/settings/page.tsx` (lines 68-73) renders a real Next.js
`<Link href="/settings/connectors">Configure</Link>` for the Connectors
section — not a dead/unwired handler. Live-clicked it from `/settings`
(screenshot 1): it's a real anchor, `Configure links count: 2` (one for
Connectors, one for Email Ingestion & Delivery, both real links per the
page's source), and it navigates correctly to `/settings/connectors`
(screenshot 2).

## The Connect/OAuth flow itself also works correctly
Clicked "Connect Account" on the Google Drive card:
- `GET /api/connectors/auth-url/google_drive` → 200, returns a real
  `https://accounts.google.com/o/oauth2/v2/auth?client_id=...` URL (a real,
  non-placeholder Google OAuth client ID is configured on this stack).
- A real popup opens and lands on Google's actual sign-in page.
- The `Connect Account` button correctly becomes `disabled` while the popup
  is open, and correctly re-enables ~500ms-1s after the popup is closed
  (tested by force-closing the popup mid-flow to simulate cancel) — the
  `popup.closed` polling in `handleConnect` works despite a benign
  `Cross-Origin-Opener-Policy policy would block the window.closed call`
  console warning coming from Google's own COOP header (harmless in this
  test; did not actually block the poll).

Could not complete a full real sign-in (blocked on the same Cloudflare
Turnstile human-click-through noted elsewhere for Clerk —
`website_features_tracker.md` Gap 9 — Google's own sign-in also expects a
live human), so the actual token-issuance leg of the OAuth flow is
unverified end-to-end. Everything short of that leg works.

## Real, distinct defect found in the same live flow: broken-connection errors are silently swallowed as "empty folder"
To test the post-connection UI (folder browse), inserted one `active`
`tenantconnection` row directly into Postgres for tenant
`00000000-0000-0000-0000-000000000000` / `google_drive`, with a
validly-Fernet-encrypted but fake access token (via the backend's own
`utils.encryption.encrypt_token`, matching the real column format) — a
legitimate black-box fault-injection test, same style as Gap 84's
deliberately-corrupted PDF. **Row deleted after the test; no lasting change
to tenant state.**

With the card now showing "Active" (screenshot 3), clicked the folder-browse
chevron (`aria-label="Browse Inbound Folder"`) to open `FolderTreeExplorer`.
Because the fake token is naturally rejected by Google, the real backend
call correctly fails and returns a clean `502 Bad Gateway` with detail
`"Could not list files from google_drive."` (see `be_502_log_excerpt.txt`,
and `routers/connectors.py::list_connector_files` lines 322-327 — this is
the backend working as designed).

**The FE discards this entirely.** `components/connectors/FolderTreeExplorer.tsx`'s
`fetchFiles()` (lines 54-69):
```
try {
  const res = await fetch(`/api/connectors/files/${provider}?direction=${direction}${query}`);
  if (!res.ok) throw new Error("Failed to load files");
  const data = await res.json();
  setFiles(data.files || []);
} catch (err) {
  console.error("Connector file listing failed", err);
} finally {
  setIsLoading(false);
}
```
The `catch` block only logs to the browser console — no error state is ever
set, so `files` stays `[]` (its initial value) and the component falls
through to its normal empty-directory rendering: **"This directory is
empty."** (screenshot 4), identical to what a genuinely empty real Google
Drive folder would show. A user with an expired/revoked/invalid connector
token gets zero indication anything is wrong — the whole Connectors feature
silently looks broken/unresponsive rather than surfacing "your connection
needs to be reconnected." This is a plausible real explanation for a user
loosely describing the Connectors area as "does nothing."

Logged separately as **Gap 100** (see `fe_features_tracker.md`) since it's a
distinct, newly-found defect from what Gap 96 originally described, not a
rewrite of Gap 96 itself.

## Conclusion
Gap 96 as originally written (dead "Configure" handler) does not reproduce
— recommend closing/rewriting per the task's own instruction. The
Connectors flow's real live defect is the swallowed-502 issue now tracked
as Gap 100.
