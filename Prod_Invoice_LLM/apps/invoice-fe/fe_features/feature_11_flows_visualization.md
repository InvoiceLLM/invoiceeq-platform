# Feature 11: System Flow Visualization

Found already built and undocumented in the codebase (`app/flows/page.tsx`) — not created this session, no feature spec or tracker entry existed for it before now. This file backfills that gap so it's tracked like everything else, per the established convention.

**Important distinction:** this is a standalone, self-contained animated diagram — a teaching/demo tool, not a functional screen. It makes zero backend calls; every "live agent log" line is hardcoded simulated text (accurate to the real architecture — real function names, real Gap numbers — but not fetched from anywhere). It is **not** part of Vendor Flow's actual implementation, even though two of its four tabs visualize Vendor Flow's *design*.

### Theme & Styling Specifications
* Self-contained inline styles (not Tailwind), dark canvas gradient background, animated SVG node/edge diagram with per-flow accent colors (`#3B82F6` inbound, `#F59E0B` outbound/vendor, `#8B5CF6` chat).
* `isNew` nodes (Vendor Flow / Feature 6.1 additions) get an amber "NEW" badge — the page already self-discloses which nodes are spec-only vs. live, which is the right call and should be preserved in any future edit.

### File Coordinates
* Page: [apps/invoice-fe/app/flows/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/flows/page.tsx) — single monolithic client component, no proxy routes, no backend dependency.

### Functionality
Four `FlowDef` constants (`INBOUND`, `OUTBOUND`, `CHAT`, `VENDOR_CHAT`), each a fixed list of nodes/edges/activity-log lines:
- **INBOUND** — the real, live extraction pipeline (upload → blob → OCR → classify → extract → verify → dedup → RAG index → COMPLETED/AUDIT_REQUIRED), annotated with real Gap numbers (15, 41, 42, 9, 55, 26/27).
- **OUTBOUND** — Vendor Flow's outbound pipeline exactly as designed in `feature_2.1_vendor_flow_ingestion.md`/`feature_7.1_vendor_flow_auditor.md` (parallel schema, imported OCR/verification, standing-rule mechanism, `NEEDS_REVIEW`). All nodes marked `isNew: true` — correctly reflects that none of this is built yet.
- **CHAT** — the real, live query agent (cache → history → rule injection → classify → SQL self-heal → synthesis), annotated with real Gap numbers (23, 48/52, 11, 20, 32, 34, 45).
- **VENDOR_CHAT** — Feature 6.1's direction-aware Chat design (dual-direction rule injection, `flow_direction` schema awareness, combined/net SQL). Marked `isNew: true` — correctly reflects spec-only status.

`FlowCanvas` renders the SVG node/edge graph with animated "packet" dots traveling along edges during playback. `AgentPanel` shows a per-node simulated terminal log, typed out line-by-line. Playback controls (play/pause/reset/speed) drive a `setTimeout`-chained sequence per flow.

### Explicitly out of scope / risk to flag
- Because two tabs visualize unbuilt Vendor Flow design as a polished, confident animation, there's a real risk of this page being mistaken for "it's built" by someone skimming quickly. The `isNew`/"NEW" badges and "spec only" text already mitigate this — any future edit to this page must preserve that distinction, not soften it.
- No live data anywhere on this page — if it's ever repurposed as an actual operational monitoring view, that would be a different feature entirely (and would want a very different implementation, reusing Gap 2/57's real log-line SSE events instead of hardcoded activity arrays).

### Tasks
- [x] **Task 11.1:** Backfill this doc + tracker entry for the already-existing, undocumented page. *(This entry.)*
- [ ] **Task 11.2 (optional, not scoped):** decide whether this page should be nav-linked anywhere (currently reachable only by direct URL, no `Sidebar.tsx` entry) — flagged here, not decided.

### Verification Plan
* **Manual Verification:** confirmed the page renders and both existing tabs (Inbound, Chat) accurately describe real, shipped code paths; confirmed both Vendor Flow tabs (Outbound, Direction-Aware Chat) are clearly marked as design-only via the `isNew` badge and tab description text, matching the actual implementation status (zero Vendor Flow code exists yet).
