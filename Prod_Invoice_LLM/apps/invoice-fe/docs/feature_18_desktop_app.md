# Feature 18 — Desktop App

> **STATUS: PLANNED — NOT IMPLEMENTED.**
> Created 2026-08-30 as a placeholder for later work, at the founder's request
> ("small feature we will develop it later"). No design decisions below are
> final — this captures the idea and the obvious shape, not a committed plan.
> Nothing here describes shipped behaviour. Build status lives in
> `fe_features_tracker.md` Gap 326; this doc is only real once that Gap is `[x]`.

## 1. Overview

A native-feeling desktop app so a user doesn't have to open a browser and
navigate to a URL every time. Founder's own framing: "like Claude Desktop" —
a dedicated icon in the taskbar/dock, no browser chrome (no tabs, no address
bar), opens straight to the login screen if signed out, or straight to the
dashboard if a session already exists.

## 2. What this is NOT

- Not a native rewrite. The existing `invoice-fe` Next.js app is not
  reimplemented — it is wrapped, reusing 100% of the existing UI, auth
  (Clerk), and API calls.
- Not a new product surface. Every screen, permission, and API call already
  built (including this session's plug-and-play wizard) works identically
  inside the wrapper — there is nothing here to duplicate in BE or website.

## 3. Discovery — how a user finds out this exists

Founder decisions (2026-08-30), settled:
- A one-time banner on first dashboard visit after an organisation is
  created — same timing as Feature 17's workflow-wizard first-run banner,
  same "show once, tied to a real state flag" convention, not a
  `localStorage` guess.
- **Plus a persistent entry point**: a small download button next to the
  notification bell in the header, always reachable after the banner is
  dismissed — not one-shot-only.

## 4. Decided (2026-08-30)

- **Shell toolchain: Tauri**, not Electron. Much smaller install (a few MB
  vs. Electron's 100MB+ bundled Chromium), lighter resource use,
  purpose-built for exactly this "wrap an existing web app" pattern.
- **First platform: Windows.** macOS (and any code-signing work it needs)
  comes after Windows is working, not simultaneously.
- The shell loads the deployed `invoice-fe` origin in a native window — no
  separate hosting, no separate build of the app's own pages.
- Session persistence: confirm Clerk's session survives the same way it does
  in a browser inside the wrapper's own webview storage, so a returning user
  lands straight in the dashboard rather than re-authenticating every launch.

## 5. Left for whoever builds this — verification tasks, not decisions

- Does anything in the app assume it's running inside a normal browser tab
  specifically? The most likely trip point is any `window.open()`-based popup
  flow (Google Drive's OAuth connect, Clerk's own auth popups) — needs a real
  check against a wrapped window before assuming it "just works."
- Fixed native window sizing vs. the app's current responsive-browser-tab
  assumptions — needs a pass to confirm nothing breaks at a typical desktop
  window size outside a browser's own chrome.
- Windows code-signing setup (a trustworthy install needs it) — mechanics,
  not a decision the founder needs to make in advance.

## 6. File Coordinates

### 6.1 Exists today — untouched by this feature
Every screen and API route in `apps/invoice-fe` and `apps/invoice-be` — this
feature adds a shell around them, not new application logic.

### 6.2 New — planned, does not exist yet
- A new sibling app/package for the desktop shell (e.g. `apps/invoice-desktop`
  or similar — exact placement not decided).
- Packaging/build/CI config for the chosen shell tool.
- Auto-update + Windows code-signing pipeline.
- The discovery banner component (§3) and whatever state flag drives it,
  plus the persistent header download button beside the notification bell.

## 7. Verification Plan

**EMPTY AT CREATION. No work has been performed, no test has been run.**

## 8. Dependencies outside this feature

None known yet — this wraps the existing FE, so it inherits whatever state
that app is in when this actually gets picked up (including any in-progress
plug-and-play work).
