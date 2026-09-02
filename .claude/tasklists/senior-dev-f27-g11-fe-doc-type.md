# senior-dev — Feature 27 G11 (FE): doc_type surfaces in invoice-fe

Scope: the FE half of Feature 27 (`feature_27_generic_extraction.md` §4 FE row, task G11).
Founder-approved implementation. Backend G9 (`Invoice.doc_type` persistence) has NOT landed,
so everything here must degrade to today's exact rendering when `doc_type` is absent.

Explicitly out of scope: a documents-list page (E10/G14 backend endpoint does not exist).

- [x] 1. Read CONVENTIONS + feature_27 §4/§10 + check in-flight tasklists for overlap
      — no file overlap: the other live F27 tasklists (G1–G5) are all backend.
- [x] 2. Audit real FE state — **`types/invoice.ts` does not exist**; `types/` holds only
      `chat.ts`. Real shapes: `StatusItem` (exported from `StatusTable.tsx`) and
      `InvoiceDetail` (review page). §4's coordinate is stale.
- [x] 3. Feature-flag exposure mechanism — **none exists.** No `/config` or `/features`
      router in `main.py`; every `ENABLE_*` is server-side only; FE sees only build-time
      `NEXT_PUBLIC_*`. DropZone widening is therefore blocked, not skipped.
- [x] 4. `StatusTable.tsx` — `docType?: string | null` on `StatusItem`, threaded from
      `data.doc_type` / `payload.doc_type`, merged not overwritten; `getDocTypeBadge()`
      slate pill in the File cell. No new column (FE Gap 113 item 6).
- [x] 5. Auditor console (`app/invoices/review/[id]/page.tsx`) — `doc_type` +
      `doc_type_evidence` rows in the existing metadata panel, independently conditional.
- [x] 6. `DropZone.tsx` — accept list stays `.pdf`; both guards refactored onto one
      `ACCEPTED_EXTENSIONS` constant so they cannot drift apart later. Blocker documented.
- [x] 7. `e2e/feature27-doc-type.spec.ts` — 6 tests, house pattern (stubbed `/api/**`).
      Found and handled a real hydration race: `setInputFiles` before React binds
      `onChange` is silently dropped.
- [x] 8. `npx tsc --noEmit` exit 0; spec 6/6 passing. 4 failures in
      `audit-review-console.spec.ts` / `gaps-282-284-286.spec.ts` proven **pre-existing**
      by stashing the three source changes and re-running at HEAD (identical 4 failed /
      11 passed).
- [x] 9. Docs — `feature_27_generic_extraction.md` G11 set to `[~]` with a build note;
      `feature_3_ingestion.md` additive FE section.
- [x] 10. Tracker — **FE Gap 378** filed. Collision-checked twice: 376 was taken mid-task
      by Feature 26 H10 (FE tracker) and 377 by Feature 27 G5 (BE build note, ahead of the
      BE tracker), both by concurrently-running agents.

Final status: **complete for the two pieces that were buildable; G11 left `[~]`.** The
DropZone accept-list widening and the documents-list surface are both blocked on backend
that does not exist (flag exposure mechanism; `GET /documents`/G14). Nothing committed.
