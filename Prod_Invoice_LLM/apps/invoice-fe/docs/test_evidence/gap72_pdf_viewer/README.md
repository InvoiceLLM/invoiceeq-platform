=== Gap 72 repro evidence, real non-headless Chromium (Playwright, headless: false), 2026-08-02/03 ===
Target: http://localhost:3001/invoices/review/b67fe5ab-248f-49b0-bbf1-60cc9840e03d (invoice #FT-INBOUND-20260802, real COMPLETED invoice with a real stored PDF)

--- Finding 1: 'loads wrong/broken PDF' -- NOT reproduced, ruled out ---
GET /api/invoices/b67fe5ab-.../pdf -> 200, Content-Type: application/pdf, valid %PDF-1.3 header, 1567 bytes.
Real, non-headless Chromium renders it correctly via its native PDF plugin: screenshot 1_baseline_100pct_correct_pdf.png
shows the exact right document (Vendor: FuncTest Vendor Ltd, Invoice #FT-INBOUND-20260802, correct line item/totals),
matching the sidebar's metadata exactly. Confirms the original entry's suspicion: the prior headless-Chromium blank-iframe
finding was a test artifact (headless Chromium has no built-in PDF viewer plugin by default), not a real bug.

--- Finding 2: Zoom In / Zoom Out -- NOT broken, works correctly (contrary to the reported complaint) ---
Measured iframe wrapper width via getBoundingClientRect() before/after:
  Baseline (100%): 414.67px
  After 3x Zoom In clicks (100->130%): 539.06px  (539.06 / 414.67 = 1.30, exact match)
  After 5x Zoom Out clicks (130->80%): 331.73px  (331.73 / 414.67 = 0.80, exact match)
Screenshots 2 and 3 confirm the PDF content visibly grows/shrinks with each click, no truncation. One real UX nuance,
not a functional break: 'Zoom' resizes the CSS width of the iframe wrapper (PdfViewerCanvas.tsx line 94), which makes
Chrome's own native PDF-viewer toolbar react by revealing more of its own chrome (thumbnail rail, its own +/- zoom, page
nav) rather than the PDF content itself being zoomed via a real PDF-level zoom API -- see screenshot 2, where Chrome's
native toolbar has expanded. Cosmetically confusing (two zoom controls doing different things) but not dead.

--- Finding 3: Rotate -- CONFIRMED BROKEN, root-caused ---
A single Rotate click (0 -> 90deg) makes almost the entire PDF disappear from view with no way to scroll back to it.
Screenshot: 4_after_rotate_90deg_BROKEN.png -- only a ~50px sliver of the rotated page plus Chrome's native PDF toolbar
(shrunk to a vertical strip) remain visible; the rest of the panel is empty.

Root cause (components/audit/PdfViewerCanvas.tsx lines 91-103): 'transform: rotate(90deg)' is applied directly to the
wrapper div containing the iframe, with no compensating width/height swap or re-centering. Measured DOM geometry after
rotation confirms it:
  iframeRect: { width: 800, height: 331.73, top: 134.14, left: -264 }
  wrapperTransform: matrix(0, 1, -1, 0, 0, 0)   // = rotate(90deg), confirmed applied
The rotated box's 'left' is NEGATIVE (-264px) relative to its scroll container -- CSS transforms don't expand the
container's scrollable area in this layout (containerScrollHeight 832 == containerClientHeight 832, i.e. the container
thinks nothing overflows), so the browser never offers a scrollbar to reach the transformed-away content. The element
rotates in place around its own center without the container re-flowing to fit the new (now width<->height swapped)
bounding box. This matches the user's live report exactly: 'PDF displays only half' and 'Rotate doesn't work at all'
-- rotate doesn't no-op, it actively breaks the layout.

--- Fix implication for senior-dev (diagnosis only, not built here) ---
Either (a) swap the wrapper's width/height and re-center when rotation is 90/270 degrees, or (b) rotate a fixed-size
outer frame around the iframe rather than the iframe's own sizing wrapper, so the rotated content's bounding box stays
within the visible/scrollable container at every rotation angle.
