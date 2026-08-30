# Feature 18 — Desktop App

> **STATUS: PLANNED — NOT IMPLEMENTED.**
> Created 2026-08-30 as a placeholder for later work, at the founder's request
> ("small feature we will develop it later"). No design decisions below are
> final — this captures the idea and the obvious shape, not a committed plan.
> Nothing here describes shipped behaviour. Build status lives in
> `fe_features_tracker.md` Gap 326; this doc is only real once that Gap is `[x]`.
>
> **A Tauri implementation was attempted and fully removed the same day.**
> A real scaffold (`apps/invoice-desktop`), an FE discovery banner/header
> button, and a CI build workflow were all built, then deleted after hitting
> real, compounding problems on the only available build machine: no local
> Rust/MSVC toolchain; once installed, Windows Smart App Control blocked the
> freshly-compiled binary from running at all; and the install contributed
> to the machine running completely out of disk space, which broke an
> in-progress `git checkout` mid-write. Nothing was lost in the process, but
> the branch was deleted rather than kept parked. **Current plan: a PWA** —
> a manifest + icons added to the existing `invoice-fe` app, no new sibling
> app, no compiler, no toolchain. Nothing has been built for either approach
> as of this reset; every section below describes the original,
> pre-implementation idea only.

## 1. Overview

A native-feeling desktop app so a user doesn't have to open a browser and
navigate to a URL every time. Founder's own framing: "like Claude Desktop" —
a dedicated icon in the taskbar/dock, no browser chrome (no tabs, no address
bar), opens straight to the login screen if signed out, or straight to the
dashboard if a session already exists.

## 2. What this is NOT

- Not a native rewrite. The existing `invoice-fe` Next.js app is not
  reimplemented — every screen, permission, and API call stays exactly what
  it is; this feature only changes how a user reaches it.
- Not a new product surface. There is nothing to duplicate in BE or website.

## 3. Discovery — how a user finds out this exists

Founder decisions (2026-08-30), still standing regardless of implementation
approach:
- A one-time banner on first dashboard visit after an organisation is
  created — same timing as Feature 17's workflow-wizard first-run banner,
  same "show once, tied to a real state flag" convention, not a
  `localStorage` guess.
- **Plus a persistent entry point**: a small download/install button next
  to the notification bell in the header, always reachable after the
  banner is dismissed — not one-shot-only.

## 4. Implementation approach — PWA (current plan, 2026-08-30)

A `manifest.json` + icon set added to the existing `invoice-fe` app, using
the browser's own "install this site as an app" capability (Chrome/Edge) to
produce a chromeless window and a real desktop/Start Menu icon — no new
app, no compiler, no toolchain, no local build step. `display: "standalone"`
is what actually produces the chromeless window; without it, "install" is
just a bookmark. No service worker / offline support is in scope here.

**Why not a native shell (Tauri/Electron)**: Tauri was tried and fully
removed the same day — see the status banner above. Worth reconsidering
only if a real downloadable installer with auto-update becomes a hard
requirement, or if OS integration a PWA can't reach on Windows is genuinely
needed.

## 5. Left for whoever builds this — verification tasks, not decisions

- `beforeinstallprompt` (Chrome/Edge) triggers a real install; Safari/
  Firefox don't support it the same way — the banner/button needs a
  fallback explaining the manual "Install this site" browser menu for
  those, not a silent no-op.
- Real icon assets — **no logo/favicon exists anywhere in this repo** as of
  this writing; get a real brand asset before building final icons.
- An actual install, on an actual machine: confirm a real desktop icon
  appears, the window opens chromeless, and a returning session lands on
  the dashboard without re-authenticating.

## 6. File Coordinates

### 6.1 Exists today — untouched by this feature
Every screen and API route in `apps/invoice-fe` and `apps/invoice-be`.

### 6.2 New — planned, does not exist yet
- `apps/invoice-fe/public/manifest.json` + icon set.
- `apps/invoice-fe/app/layout.tsx` — manifest `<link>` tag (modified).
- The discovery banner component (§3) and whatever state flag drives it,
  plus the persistent header download/install button beside the
  notification bell.

## 7. Verification Plan

**EMPTY AT CREATION. No work has been performed, no test has been run.**

## 8. Dependencies outside this feature

None known yet — this wraps the existing FE, so it inherits whatever state
that app is in when this actually gets picked up.
