# System Journey — User & Admin Guide

Purpose: a plain-language walkthrough of what this product actually does for the people who use it day to day — no code, no file names. Written as a set of journeys through the screens, so you can sanity-check the whole picture: what is live today, and what is still on the drawing board.

*Last reconciled against the live application: 2026-09-07.*

Marking convention:
- **Today** — live, working right now.
- **Today (recently built)** — working, but shipped in the last few weeks and not yet run end-to-end on the cloud environment. Expect rough edges.
- **Planned** — designed, documented, not yet built.

---

## Part 1 — Today: receiving and paying your vendors' invoices

### The people
- **Admin** — full control: every screen, Settings, Subscriptions, and the Admin Console where users and their permissions are managed.
- **Auditor** — works the Audit Queue and the History screen, reviews and corrects flagged invoices, uses Dashboard and Chat.
- **Trainer** — teaches the system corrections on the AI Trainer screen, uses Dashboard and Chat.

Two things changed since the last edition of this guide. First, the old **Viewer** role was retired on 2026-08-28; there is no read-only role to hand out any more. Second, roles are now a starting point rather than the whole story: an Admin can grant or withhold four individual permissions per person — **Trainer**, **Auditor**, **Loader** (may upload invoices) and **Send Invoices** — so an Auditor can be allowed to upload, or a Trainer allowed to send customer invoices, without changing their role. Someone whose role could not be established (for example, an invitation that has not been completed) sees only Dashboard, Chat and Help. **Today.**

### Signing in
Everyone arrives through the public website. An Admin creates the organisation on the sign-up page (organisation name, type and country, plus their own email and password); the email is verified with a one-time code that shows a ten-minute countdown and a resend button. Sign-in is email and password, with the same one-time code as a second step if the organisation has that turned on, and every password box has a show/hide eye icon. Forgotten passwords are reset with a code sent by email. After sign-in you land on the app's Dashboard. **Today.**

### A typical Monday
Priya, an AP clerk, receives a stack of vendor invoices by email. She (or any registered AP address) can forward them straight to the shared receive mailbox — the address is shown on **Settings → Email** (on the live environment it is `invoice@receive.invoicellm.admsofttech.com`) — once an Admin has added her address to the **inbound authorized emails** list there. Emails from an address that is not on the list are dropped and recorded, not processed. **Today.**

For the ones on her desk she opens **Ingest**, drags in five files — PDFs, or a phone photo or scan (PNG, JPG, TIFF, WEBP, BMP; images are converted to PDF for her) — and watches each one move through a live status bar, usually inside a minute per invoice, since real OCR and AI extraction are running behind the scenes (**NOVA** — Smart Invoice Extraction agent). Most land as **Completed**; a couple get flagged **Needs Review**, because **SENTINEL** (Invoice Risk Detection agent) automatically caught a field that was low-confidence or a total that didn't match what's printed on the page. Duplicates are caught twice — once on the file itself, once on vendor + invoice number after reading — and marked **Duplicate** rather than counted twice. **Today** (image upload: **Today, recently built**).

She opens the **Audit Queue** and picks the first flagged invoice. The **Auditor Review Console** puts the PDF on one side, the extracted fields in the middle and a **Discrepancy Warnings** card on the right listing exactly what SENTINEL objected to; clicking a warning jumps to the field it is about. She can correct any field, dismiss a warning she has checked by hand, then finish the invoice one of four ways: **Mark Paid**, **Reject** (with a reason), or — new since the last edition — park it as **Review Later** or send it back to the vendor as **Needs Resubmission**. Both parking states stay visible in the queue and on the Dashboard filters so nothing gets lost. **Today.**

Later, her manager Raj wants a quick answer and opens **Chat**: *"What's the total from Northwind Manufacturing this month, and is anything flagged?"* — **SAGE** (Invoice Intelligence Chat agent) returns a real answer citing the specific invoices, because it already indexed everything Priya processed. Each answer arrives as one complete reply once it is ready (a progress indicator shows while it works; word-by-word streaming exists as an operator switch and is off by default). He can open the audit drawer under any answer to see how it was worked out, and give a thumbs-down that routes the answer into a short triage so the team can fix a wrong one. Chat keeps past conversations in a sidebar. **Today.**

Raj can also **attach a document to the conversation** — a purchase order or a quotation, as a PDF — and ask *"does this match what we were billed?"*. SAGE finds the invoices it relates to (by PO number first, then supplier and date; it asks him to confirm when unsure) and shows a side-by-side reconciliation table of subtotal, tax and total, marking each difference. Two attachments can each be compared to their own invoice in one go. Asking questions about the *contents* of an attached non-invoice document (rather than comparing it) is an operator switch, on in the current environment but off by default. **Today.**

At the end of the day, the **Dashboard** shows the numbers that matter: total invoiced, paid, outstanding, average processing time, a **Needs Attention** list, a **Top Vendors & Clients** tab, an **Insights** tab that raises a handful of plain-English observations (spend concentration, money at risk, audit rate, vendors with no rules yet — each can be dismissed), and a **Trainer Impact** tab counting the rules trained (company-wide and per vendor) and listing the vendors that still have none. **Today.**

### Not everything that arrives is an invoice
Vendors send credit notes, statements, delivery notes. As of September 2026 every incoming file is first classified as one of fourteen document types — Invoice, Proforma Invoice, Credit Note, Debit Note, Quotation, Purchase Order, Order Confirmation, Contract, Delivery Note, Goods Received Note, Receipt, Remittance Advice, Statement of Account, or Other. Anything that is not an invoice is read and stored, but it never enters the payables Audit Queue and never inflates the Dashboard totals; it appears as an explained row on the **History** screen with its type and the evidence for that decision, instead of silently disappearing. **Today (recently built).**

### The History screen
Uploads, forwarded emails (including the rejected ones), Autopilot pickups and non-invoice documents all land in one durable **History** log — one row per run, expandable to the files inside it, filterable by source and direction. A row can be **archived** to tidy the list; archiving hides the log line and deletes nothing. Available to anyone with the Auditor permission. **Today (recently built, 2026-09-05).**

### Letting it run itself — Autopilot
Instead of dragging files in, an Admin connects the company's **Google Drive** (under Settings → Connectors — Drive is the only connector today; the Salesforce option was removed on 2026-08-28), then on the **Ingest → Autopilot** tab points at a folder and picks a schedule: every so many minutes, or a cron-style timetable. Each sync shows up in a **sync history** table (when, what triggered it, how many files, what happened to each), kept for a configurable number of days — 90 by default — and any run can be hidden. Optional notification emails and approval links can be sent to named colleagues after each run. **Today.**

### What Trainer is for
The **AI Trainer** screen powers **EVOLVE** (Continuous Learning agent). It was redesigned on 2026-08-17 around a simple idea: a rule should always be anchored to a real document. You start by choosing a vendor and one of their real invoices (or uploading one), and the screen shows that invoice's PDF next to the warnings SENTINEL raised on it. Correcting a warning — or reporting one it missed — becomes a rule for that vendor; the screen previews what the rule would change before you commit, re-checks that vendor's existing invoices when you do, and keeps a history with rollback. A second mode, **Ask Questions**, lets you quiz the sandbox about that invoice to check what the system currently believes. A **Chat Response Style** tab on the same screen sets how Chat answers for the whole company (length, tone, standing instructions). Rules that apply to every vendor still work, but the free-text "type a rule for everyone" entry point was removed on purpose — a rule with no document behind it was the source of most bad rules. Requires the Trainer permission and a **Pro** or **Pro Combined** plan; free-tier users see an upgrade prompt instead. **Today.**

### When something goes wrong — getting help
Priya hits a wall: an invoice keeps coming back flagged and she can't work out why. She clicks **Help** in the sidebar. It opens on the **Knowledge Base Guides** — seven illustrated, step-by-step walkthroughs (Auditor, AI Trainer, Autopilot, Settings, Webhooks, and inbound and outbound email setup), with a search box at the top so she can type "vendor rule" and jump straight to the right one. **Today.**

If the guides don't answer it, she switches to the second tab, **AI Support Assistant**, and describes the problem in her own words. It answers on the spot for common issues. Be aware of what this is: a fast lookup over a curated set of known problems and their fixes, not the same AI that answers questions about your invoice data in Chat — it doesn't know anything about *your* invoices. When it can't help, it says so and offers to escalate rather than guessing. **Today.**

Escalating is one click. A ticket form opens with the problem already filled in from the conversation, she picks how urgent it is (**Low**, **Normal**, or **Urgent**, each with the response time we commit to), and submits. She gets a reference number back immediately — something like `TICK-2026-9173A5B8` — and the whole chat transcript goes to the support team along with it, so nobody asks her to explain it all over again. She can raise a ticket directly from the same screen without talking to the assistant first, if she already knows what she needs. **Today.**

The third tab, **My Tickets**, is new since the last edition: it lists every ticket she has raised with its reference, subject, urgency and current status — **Open**, **In Progress**, **Resolved** or **Closed**. It is read-only; the conversation itself still happens by email, and only the support team moves a ticket between states. **Today.**

A prospect who isn't a customer yet has their own way in: the **Contact Us** page on the public website, linked from the site header and footer. Same idea — pick a category (sales, technical, billing, partnership, general) and an urgency, write the message, get a reference number back (`INQ-2026-…` for these) and an acknowledgement email. Every one of these, from either door, lands as a ticket in one place and pages the support inbox. **Today.**

### The Admin's screens
Everything in this section is **Admin only** and **Today** unless marked otherwise.

- **Settings** is a grid of tiles. **Service Flow** holds the two switches — *Receive Invoices* (on for everyone) and *Send Invoices* (see Part 2). **Email** shows the shared receive mailbox and the two authorised-sender lists (inbound for vendor invoices, outbound for your own). **Connectors** is where Google Drive is connected and folders are mapped. **Webhooks** lets you register your own systems to be notified — signed messages for seven events: an invoice completed, flagged for audit, approved or rejected, and a customer invoice sent, approved or gone overdue; each webhook can be paused and its signing key rotated. **Security** issues and rotates the company's API key for programmatic access, issues tokens for an embeddable chat widget, and shows the role/permission matrix. **Workflows** is a short **Plug & Play** wizard: how invoices arrive (manual upload, email, Google Drive, direct API), the audit policy (**Full Automation** — the API key may approve, reject and finalise on its own — or **Strict Review** — a person finalises every invoice), where results go (email summary, Google Drive archive, webhook, or dashboard only), and where Chat is used (this app, the API, or an embeddable widget on your own website). *(Workflows and the widget: **Today (recently built)**; the public "try it with a sandbox key" path advertised on the website is behind an operator switch that is off by default — **Planned** for customers.)*
- **Subscriptions** (also in the sidebar) shows the current plan, the invoice allowance and when it refills (the Free plan is metered; Pro plans are not), and a Change Plan button that hands off to PayU. Cancelling and reactivating a plan is done here too.
- **Admin Console** (a tile on the Settings screen — it is deliberately not in the sidebar) lists the organisation's members, creates a new user directly with a name, email and password — they can sign in immediately, no confirmation step — grants or withdraws the four permissions (Trainer, Auditor, Loader, Send Invoices) per person, and removes users.

### Paying for it
Three plans on the public website's pricing page: **Free** (₹0, metered allowance), **Pro** (₹4,999/month, receiving side) and **Pro Combined** (₹8,999/month, receiving and sending). Checkout runs on PayU's hosted page; success and failure land back on the website with a plain explanation and a link into the app. A lapsed renewal locks the workspace until payment is fixed. **Today** (live-mode PayU still needs the merchant's own KYC sign-off — test mode is what has been exercised end to end).

---

## Part 2 — Today: sending invoices to your own customers

When this guide was last written, everything in this part was **Planned**. It has since been built and is in daily use: the mirror image of Part 1 — instead of *receiving* bills from your vendors, you *send* bills to your own customers and track whether they've been paid. Where something is still missing, it is marked.

### Turning it on
An Admin — and only an Admin — flips the *Send Invoices* switch on **Settings → Service Flow**. It's independent of *Receive Invoices* (on by default for every customer, so nothing changes unless you touch it). Two preconditions: the workspace must be on the **Pro Combined** plan (the switch offers an upgrade otherwise), and at least one address must be on the **outbound authorized emails** list under Settings → Email. Whatever you answered at signup only sets the starting position; Settings is the permanent control from then on. On top of the company-wide switch, each person also needs the **Send Invoices** permission from the Admin Console before the sending screens appear for them (added 2026-09-02). **Today.**

### Sending an invoice — from a PDF you already have
On **Ingest**, a **Send Invoices** tab appears next to the receiving one. You upload the invoice PDF you made in whatever tool you use today (or email it to the shared mailbox from an outbound-authorised address). The system reads it back with the same rigor as the receiving side — checking the arithmetic and that the required fields are present — and shows a "ready to send" or "needs a fix" status. **Today.**

Flagged ones open in the **Outbound Auditor Console**: PDF on one side, fields in the middle, **Discrepancy Warnings** on the right — the same layout as the vendor side. If the system keeps misreading the same thing on your own invoices (say, always mixing up which block is the customer's name), a single checkbox on that screen — *apply as a standing rule* — teaches it the fix for all future invoices of yours. There's no multi-step training sandbox for this, because there's only one format to get right — your own. From here you **Confirm Send** to mark the invoice as sent and, later, **Mark Paid**. **Today.**

### Sending an invoice — building one from a previous one
New since the last edition: from any verified, sent, paid or overdue customer invoice, the button **New invoice from this** opens the **Invoice Builder**. It pre-fills everything from the source, suggests the next invoice number and rolls the dates forward by the same payment term; you edit the customer, dates, number and line items (add or remove rows), watch the totals recalculate, **Preview** the real PDF the system will produce, then **Create**. The new invoice drops into the Send Invoices ledger and goes through exactly the same read-back check as an uploaded one — if what was rendered does not match what you typed, it is flagged rather than sent. Each customer invoice shows a "cloned from" link back to its source. **Today (recently built, 2026-09-05 — not yet exercised end-to-end on the cloud environment).**

### Tracking what's owed to you
The **Audit Queue** has a second view for customer invoices with its own tabs — all, pending, overdue and so on — so a customer invoice that has gone past its due date is one click away. **Today.**

The **Dashboard** behaves differently here: if you're using *both* receiving and sending, it splits into two halves shown side by side — what you owe on the left, what's owed to you on the right — with a **Top Customers** tab alongside **Top Vendors & Clients**. If you only use one side of the business, you never see an empty second half. **Today.**

### Asking about both sides at once
**Chat** doesn't change screens or split in two — it's the same conversation window. Ask about a customer invoice, a vendor invoice, or both at once ("how much do I owe versus how much am I owed") and it answers correctly either way. **Today.**

### What this does *not* include yet
- **No delivery to the customer.** *Confirm Send* records the invoice as sent and notifies your own staff; it does not email the customer. You still send the PDF yourself. **Planned** — no date.
- **No branding tool.** The Invoice Builder reproduces your existing layout; there is no logo upload, template designer or customer address book. Deliberately out of scope for now. **Planned**, separate project.
- **No desktop app.** The product is used in the browser. A desktop wrapper is designed but not started (an earlier native attempt was abandoned in favour of an installable web app). **Planned.**

---

## Quick reference: who can do what

Roles set the defaults; an Admin can adjust the four permissions per person in the Admin Console.

| | **Admin** | **Auditor** | **Trainer** |
|---|---|---|---|
| Dashboard, Chat, Help | Yes | Yes | Yes |
| Upload invoices (Ingest) | Yes | Only if granted **Loader** | Only if granted **Loader** |
| Audit Queue + review consoles, History | Yes | Yes | Only if granted **Auditor** |
| AI Trainer | Yes | Only if granted **Trainer** | Yes |
| Send Invoices tab, Outbound console, Invoice Builder | Yes (and workspace must have *Send Invoices* on) | Only if granted **Send Invoices** | Only if granted **Send Invoices** |
| Settings (Service Flow, Email, Connectors, Webhooks, Security, Workflows) | Yes | No | No |
| Subscriptions and plan changes | Yes | No | No |
| Admin Console (users, roles, permissions) | Yes | No | No |

A person whose role could not be established (the old "Viewer" slot, retired 2026-08-28) sees Dashboard, Chat and Help only, and can change nothing.
