# Gap 83 repro — Outbound Audit screen redundant internal tab row

Real, non-headless Chromium (Playwright `headless:false`), real local stack,
2026-08-03.

## Suspected causes ruled out
The Audit Queue **list** page (`app/invoices/page.tsx`, `/invoices`) does
render two visually-similar pill-button rows when both Receive/Send are
enabled — the top-level Receiving/Sending direction toggle, and (inside
whichever table card is showing) that table's own All/Pending/Paid/
Rejected-or-Overdue status-tab row. Checked both Receiving and Sending tabs
live (screenshots 3–4): each renders its toggle+status-tabs exactly once,
no duplication, and the pattern is symmetric between inbound and outbound
(`RecentInvoicesTable.tsx` and `OutboundInvoicesTable.tsx` both have their
own internal `STATUS_TABS` row). This category of "two stacked tab-like
rows" is real but by design and not a bug, and not unique to outbound — so
it doesn't explain a report specifically calling out the *outbound* screen.

## Real root cause found: same class of bug as Gap 71, unfixed on the outbound counterpart
`app/invoices/outbound-review/[id]/page.tsx` (the **individual outbound
invoice's** audit console, reached by opening an outbound invoice from the
Sending tab) still imports and wraps itself in `<Shell>` in all three return
paths (loading state line 164, error state line 174, main render line 188) —
exactly the double-Shell bug Gap 71 fixed on 2026-07-29, but only on the
*inbound* counterpart (`app/invoices/review/[id]/page.tsx`, confirmed via
grep to have zero `Shell` references today). The outbound file was never
touched by that fix.

Live confirmation, opening a real `NEEDS_REVIEW` outbound invoice
(`78d112ca-bfa4-4dff-8fc4-be3ed2299129`) at `/invoices/outbound-review/78d112ca-...`:
- `"Tenant Isolation ID"` footer (rendered once per `Shell`/`Sidebar`) count: **2**
- Header search box count: **2**
- `"Dashboard"` nav link count: **2**

Screenshot 1 (still in the loading-spinner state) and screenshot 2 (fully
loaded) both show a full second copy of the entire app chrome — logo,
search bar, help icon, sidebar nav, Tenant Isolation ID footer — nested
inside the outer Shell's content area, pushing the actual "Outbound Auditor
Console" content off to the right and forcing a horizontal scrollbar
(visible at the bottom of screenshot 2).

## Why this reads as "a redundant internal tab row"
The duplicated Sidebar's vertical nav-item list (Dashboard/Ingest/Audit
Queue/AI Trainer/Chat/Settings/Help) sitting inside the page's own content
area, next to a second header search bar, is a plausible thing to describe
loosely as "a redundant internal tab row" without inspecting the DOM closely
— it's an unmistakable duplicate-navigation artifact, just not literally a
row of tabs.

## Fix implication for senior-dev (diagnosis only, not built here)
Apply the exact same fix Gap 71 used: remove all three `<Shell>` wrapper
usages (and the now-unused `Shell` import) from
`app/invoices/outbound-review/[id]/page.tsx` — the page is already inside
the shell from `app/layout.tsx`, same as the inbound review page.
