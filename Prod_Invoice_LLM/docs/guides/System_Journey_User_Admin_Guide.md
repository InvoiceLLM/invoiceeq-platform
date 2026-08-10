# System Journey — User & Admin Guide

Purpose: a plain-language walkthrough of what this product actually does for the people who use it day to day — no code, no file names. Written as a set of journeys through the screens, so you can sanity-check the whole picture (what's live today, and what Service Flow will add) before any of it is built.

Marking convention:
- **Today** — live, working right now.
- **Planned** — designed, documented, not yet built.

---

## Part 1 — Today: receiving and paying your vendors' invoices

### The people
- **Admin** — full control, including the one Settings screen that will exist once Service Flow ships.
- **Auditor** — reviews and fixes flagged invoices, teaches the system corrections.
- **Viewer** — read-only access to Dashboard and Chat.

### A typical Monday
Priya, an AP clerk, receives a stack of vendor invoices by email. She (or a registered AP address) can also forward PDFs to the shared app mailbox `invoices@invoiceeq.app` after an Admin adds her address to the **inbound** authorized set under **Settings → Email**. She opens **Ingestion**, drags in five PDFs, and watches each one move through a live status bar — *Extracting text → Reading fields → Done* — usually inside a minute per invoice, since real OCR and AI extraction are running behind the scenes (**NOVA** — Smart Invoice Extraction agent), not a canned demo. Most land as **Completed**; a couple get flagged **Needs Review**, because **SENTINEL** (Invoice Risk Detection agent) automatically caught a field that was low-confidence or a total that didn't match what's printed on the page.

She opens the **Auditor** screen for the first flagged invoice. The PDF sits on one side, the extracted fields on the other — she can see exactly where the AI read the tax amount from, click any field to correct it, and save. If she happens to fix the same kind of mistake three times for the same vendor, the system quietly notices and offers: *"Want to save this as a rule?"* — one click sends her straight into the **Trainer** screen with that correction pre-filled, so the AI stops making the same mistake on that vendor's future invoices.

Later, her manager Raj wants a quick answer and opens **Chat**: *"What's the total from Northwind Manufacturing this month, and is anything flagged?"* — **SAGE** (Invoice Intelligence Chat agent) returns a real answer in seconds, citing the specific invoice, because it already indexed everything Priya processed.

At the end of the day, the **Dashboard** shows the numbers that matter: total invoiced, what's been paid, what's outstanding, which vendors cost the most, and — as of a recent fix — a genuinely real average processing time (previously this number was a rough estimate; it now reflects actual measured time).

### What Trainer is for
The **Trainer** screen powers **EVOLVE** (Continuous Learning agent): three modes — one set of rules that apply to every vendor (**Global**), rules specific to a vendor you already have invoices from (**Existing Vendor**, seeded from their real data), and rules for a brand-new vendor you're about to start working with (**New Vendor**, blank slate). Corrections made in Auditor can feed straight into this screen; commits here immediately re-check any of that vendor's existing invoices against the new rule.

---

## Part 2 — Planned: sending invoices to your own customers

Everything below is designed but not yet built. It adds the mirror image of Part 1: instead of *receiving* bills from your vendors, you *send* bills to your own customers and track whether they've been paid.

### Turning it on
An Admin — and only an Admin — flips a switch on the new **Settings** screen: *Send Invoices*. It's independent of the existing *Receive Invoices* switch (on by default for every current customer, so nothing changes unless you touch it). Whatever you answered at signup only sets the starting position; Settings is the permanent control from then on.

### Sending an invoice
There's no "create an invoice" button — building a proper invoice designer would mean adding logo uploads, layout templates, and a branding settings screen, which is a bigger, separate project on its own (parked for later). Instead: you upload the invoice PDF you already made in whatever tool you use today. The system reads it back — same rigor as the receiving side, checking the math and the required fields are all there — and shows you a "ready to send" or "needs a fix" status before you confirm.

If the system keeps misreading the same thing on your own invoices (say, always mixing up which block is the customer's name), you can teach it a standing fix directly from that review screen with one checkbox — *"always apply this from now on."* Unlike the vendor side, there's no multi-step training sandbox for this, because there's only one format to get right — your own.

### Tracking what's owed to you
The **Auditor** screen gains a second tab for these sent invoices — instead of extraction problems, it flags things like a missing field before send, or a customer invoice that's now overdue.

The **Dashboard** behaves differently here than the tabs above: if you're using *both* receiving and sending, the Dashboard splits into two halves shown side by side — what you owe on the left, what's owed to you on the right — so you can see the whole picture at a glance without clicking between views. If you only use one side of the business, you'll never see an empty second half; the Dashboard just shows the one you actually use, exactly as it does today.

### Asking about both sides at once
**Chat** doesn't change screens or split in two — it's the same conversation window, now just smarter. Ask about a customer invoice, a vendor invoice, or both at once ("how much do I owe versus how much am I owed") and it answers correctly either way.

### What this does *not* include
- **No invoice creation/branding tool** — upload-only for now; a proper builder (logo, templates) is a separate future project.
- **No customer-facing delivery yet** — Confirm Send does not email the customer (Gap 125). Staff can email the tenant’s own PDFs to `invoices@invoiceeq.app` for outbound audit if their address is on the **outbound** authorized set (Settings → Email).
- **No pricing decided yet** — whether this comes free, requires the paid tier, or costs extra is an open question, deliberately not settled yet.

---

## Quick reference: who can do what

| Role | Receive (today) | Send (planned) | Settings |
|---|---|---|---|
| **Admin** | Full access | Full access | Can toggle both switches |
| **Auditor** | Review & correct | Review & correct | Can see, cannot change |
| **Viewer** | Dashboard & Chat only | Dashboard & Chat only | Can see, cannot change |
