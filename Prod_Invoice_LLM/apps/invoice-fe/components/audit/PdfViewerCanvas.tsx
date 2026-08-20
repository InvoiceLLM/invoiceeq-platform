"use client";

import { ZoomIn, ZoomOut, RotateCw, Maximize2, X, AlertTriangle } from "lucide-react";
import { useState, useCallback } from "react";
import { Document, Page, pdfjs } from "react-pdf";

// FE Gap 271: pdf.js needs a worker script. Tried the documented
// `new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url)`
// bundler-resolution pattern first -- broke `next build` in production:
// Next's Terser minification pass runs over the asset chunk webpack copies
// for that URL, and pdfjs-dist 5.x's worker (`import.meta` at module scope,
// no non-ESM build exists anymore in this version) isn't valid input to
// Terser's default parser, producing "'import.meta' cannot be used outside
// of module code." Confirmed by actually running a production build, not
// assumed.
//
// Fixed by serving it as a plain static file instead: the exact same
// `pdf.worker.min.mjs` copied verbatim into `public/`, referenced by a
// plain string path. `public/` assets are served as-is and never touched by
// webpack/Terser, so this sidesteps the problem rather than working around
// it. Still same-origin, no CDN dependency. If pdfjs-dist is ever upgraded,
// re-copy `node_modules/pdfjs-dist/build/pdf.worker.min.mjs` ->
// `public/pdf.worker.min.mjs` to match the new version.
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

interface Coordinate {
  x: number;       // percentage-based left offset (0-100)
  y: number;       // percentage-based top offset (0-100)
  width: number;   // percentage-based width (0-100)
  height: number;  // percentage-based height (0-100)
  label?: string;
}

interface PdfViewerCanvasProps {
  invoiceId: string;
  title?: string;
  status?: string;
  coordinates?: Coordinate[];
}

/**
 * FE Gap 271: this used to render the PDF in a plain `<iframe>` (the
 * browser's own native PDF viewer) and position the bounding-box overlays as
 * percentages of the *iframe's outer box*. That was the actual bug -- a
 * native viewer can add its own toolbar/padding/letterboxing that the parent
 * page can't see or measure, so "100% of the iframe" never reliably equaled
 * "100% of the PDF page's real content area", and every highlight landed
 * somewhere close to right but not exactly right.
 *
 * Fixed by rendering via pdf.js (react-pdf) onto a real `<canvas>` instead.
 * The rendered page's exact pixel dimensions come back from
 * `onRenderSuccess`, so the overlay wrapper can be sized to *exactly* the
 * real page box -- there is no plugin chrome to be uncertain about anymore.
 *
 * Deliberately unchanged: the existing zoom (CSS width%) and rotate (CSS
 * transform) mechanism on the outer wrapping div. Neither was the reported
 * bug (rotation's own layout issue was Gap 72, already fixed separately),
 * and scaling/rotating a precisely-sized inner box keeps the overlay
 * percentages correctly aligned to it either way -- no reason to also
 * migrate those to pdf.js's native `scale`/`rotate` props in the same pass.
 *
 * Also deliberately unchanged in scope: overlays are positioned against
 * page 1 only. `coordinates` has never carried a page number (checked
 * models.py -- `Invoice.coordinates` is a plain untyped JSON list), so this
 * was already implicitly page-1-only before; every page still renders
 * (multi-page invoices still scroll exactly like the old iframe did), this
 * fix doesn't newly narrow that.
 */
export default function PdfViewerCanvas({
  invoiceId,
  title,
  status,
  coordinates = [],
}: PdfViewerCanvasProps) {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [isModalOpen, setIsModalOpen] = useState(false);
  // Gap 154/155: isolated modal transform state — these are completely separate from
  // the inline viewer state so that rotating in the modal does not leak back into
  // the background viewer and vice-versa.
  const [modalZoom, setModalZoom] = useState(100);
  const [modalRotation, setModalRotation] = useState(0);

  const [numPages, setNumPages] = useState<number | null>(null);
  // FE Gap 271: page 1's real, rendered pixel size -- what the overlay
  // wrapper is sized to, so coord.x/y/width/height percentages land exactly
  // where Document Intelligence measured them against the source page.
  const [page1Size, setPage1Size] = useState<{ width: number; height: number } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const pdfUrl = `/api/invoices/${invoiceId}/pdf`;

  const statusBadge: Record<string, string> = {
    COMPLETED: "bg-emerald-500/20 text-emerald-300 border-emerald-600/50",
    AUDIT_REQUIRED: "bg-yellow-500/20 text-yellow-300 border-yellow-600/50",
    PROCESSING: "bg-blue-500/20 text-blue-300 border-blue-600/50",
    DUPLICATE: "bg-orange-500/20 text-orange-300 border-orange-600/50",
    PAID: "bg-emerald-500/20 text-emerald-300 border-emerald-600/50",
    REJECTED: "bg-red-500/20 text-red-300 border-red-600/50",
  };

  const handleZoomIn = () => setZoom((z) => Math.min(z + 15, 250));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 15, 50));
  const handleRotate = () => setRotation((r) => (r + 90) % 360);

  // Gap 154/155: isolated modal controls — only affect modalZoom / modalRotation.
  const handleModalZoomIn = () => setModalZoom((z) => Math.min(z + 15, 250));
  const handleModalZoomOut = () => setModalZoom((z) => Math.max(z - 15, 50));
  const handleModalRotate = () => setModalRotation((r) => (r + 90) % 360);

  const handleOpenModal = () => {
    // Reset modal to default view on open so it starts clean regardless of inline viewer state.
    setModalZoom(100);
    setModalRotation(0);
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    // Explicitly reset so reopening starts fresh and inline viewer is unaffected.
    setModalZoom(100);
    setModalRotation(0);
  };

  const handleDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setLoadError(null);
  }, []);

  // Typed as `{ width, height }` only, deliberately not react-pdf's full
  // PageCallback (PDFPageProxy) type -- avoids depending on that package's
  // internal type-export path, which isn't re-exported from its top-level
  // module and isn't part of its public API contract.
  const handlePage1RenderSuccess = useCallback((page: { width: number; height: number }) => {
    setPage1Size({ width: page.width, height: page.height });
  }, []);

  return (
    <div className="flex h-full min-h-[500px] xl:min-h-0 flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#222D3D] px-4 py-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
            Invoice PDF Viewer
          </p>
          {title && (
            <p className="mt-0.5 text-sm font-medium text-slate-200">{title}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <span
              className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                statusBadge[status] ?? "bg-slate-700 text-slate-300 border-slate-600"
              }`}
            >
              {status.replace("_", " ")}
            </span>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-[#222D3D] px-4 py-2 text-slate-400">
        <button
          type="button"
          onClick={handleZoomIn}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <ZoomIn size={13} /> Zoom In
        </button>
        <button
          type="button"
          onClick={handleZoomOut}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <ZoomOut size={13} /> Zoom Out
        </button>
        <button
          type="button"
          onClick={handleRotate}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <RotateCw size={13} /> Rotate
        </button>
        <span className="text-xs text-slate-500 font-mono ml-1">{zoom}%</span>
        {numPages && numPages > 1 && (
          <span className="text-xs text-slate-500 ml-2">{numPages} pages</span>
        )}

        {/* Gap 155: Fullscreen Lightbox Modal Button */}
        <button
          type="button"
          onClick={handleOpenModal}
          className="ml-auto flex items-center gap-1 rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-300 transition hover:bg-blue-500/20"
        >
          <Maximize2 size={13} /> Expand PDF
        </button>
      </div>

      {/* PDF + Overlay Container */}
      <div className="relative flex-1 overflow-auto bg-[#08101A] p-4 flex items-start justify-center">
        <div
          className="relative transition-all duration-200"
          style={{
            width: `${zoom}%`,
            minWidth: "100%",
            transform: `rotate(${rotation}deg)`,
            transformOrigin: "center top",
          }}
        >
          {loadError ? (
            <div className="flex h-[400px] w-full items-center justify-center gap-2 rounded-md border border-[#222D3D] bg-white text-sm text-rose-600">
              <AlertTriangle size={16} /> {loadError}
            </div>
          ) : (
            <Document
              file={pdfUrl}
              onLoadSuccess={handleDocumentLoadSuccess}
              onLoadError={(err) => setLoadError(err?.message || "Failed to load PDF.")}
              loading={
                <div className="flex h-[400px] w-full items-center justify-center rounded-md border border-[#222D3D] bg-white text-sm text-slate-500">
                  Loading PDF…
                </div>
              }
              className="w-full rounded-md border border-[#222D3D] bg-white shadow-xl overflow-hidden"
            >
              {Array.from({ length: numPages ?? 0 }, (_, i) => i + 1).map((pageNumber) => (
                <div key={pageNumber} className={pageNumber > 1 ? "relative border-t border-[#222D3D]" : "relative"}>
                  <Page
                    pageNumber={pageNumber}
                    width={undefined}
                    renderTextLayer={false}
                    renderAnnotationLayer={false}
                    onRenderSuccess={pageNumber === 1 ? handlePage1RenderSuccess : undefined}
                    className="w-full [&>canvas]:!w-full [&>canvas]:!h-auto"
                  />
                  {/* Bounding Box Overlays — page 1 only, see file-level comment. */}
                  {pageNumber === 1 && page1Size && (
                    <div
                      className="pointer-events-none absolute left-0 top-0"
                      style={{ width: page1Size.width, height: page1Size.height }}
                    >
                      {coordinates.map((coord, idx) => (
                        <div
                          key={idx}
                          className="absolute rounded-sm border-2 border-emerald-400 bg-emerald-400/20 shadow-[0_0_12px_rgba(16,185,129,0.5)]"
                          style={{
                            left: `${coord.x}%`,
                            top: `${coord.y}%`,
                            width: `${coord.width}%`,
                            height: `${coord.height}%`,
                          }}
                          title={coord.label}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </Document>
          )}
        </div>
      </div>

      {/* Gap 154/155: Lightbox Modal Pop-out — with isolated zoom/rotation state */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 backdrop-blur-md p-6">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{title || "Invoice PDF Preview"}</span>
              {/* Gap 154: show modal-specific zoom level, not inline viewer's */}
              <span className="text-xs font-mono text-slate-400">{modalZoom}%</span>
              {modalRotation > 0 && (
                <span className="text-xs font-mono text-slate-500">{modalRotation}°</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* Gap 154: modal zoom/rotate controls use isolated handlers */}
              <button
                type="button"
                onClick={handleModalZoomIn}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                title="Zoom In (modal)"
              >
                <ZoomIn size={16} />
              </button>
              <button
                type="button"
                onClick={handleModalZoomOut}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                title="Zoom Out (modal)"
              >
                <ZoomOut size={16} />
              </button>
              <button
                type="button"
                onClick={handleModalRotate}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                title="Rotate (modal only — does not affect background viewer)"
              >
                <RotateCw size={16} />
              </button>
              <button
                type="button"
                onClick={handleCloseModal}
                className="p-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 ml-2"
              >
                <X size={16} />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto flex items-center justify-center p-4">
            {/* Gap 154: apply transform to the wrapper div, not the page itself,
                so the full PDF (including scrollable content) scales and rotates correctly.
                FE Gap 271: same iframe -> canvas swap as the inline viewer above; this
                preview never rendered coordinate overlays before and still doesn't. */}
            <div
              style={{
                width: `${modalZoom}%`,
                minWidth: "300px",
                maxWidth: "100%",
                transform: `rotate(${modalRotation}deg)`,
                transformOrigin: "center center",
                transition: "transform 0.2s ease, width 0.2s ease",
              }}
              className="h-full overflow-auto"
            >
              {!loadError && (
                <Document
                  file={pdfUrl}
                  loading={
                    <div className="flex h-full min-h-[70vh] w-full items-center justify-center rounded-xl border border-slate-800 bg-white text-sm text-slate-500">
                      Loading PDF…
                    </div>
                  }
                  className="w-full rounded-xl border border-slate-800 bg-white shadow-2xl overflow-hidden"
                >
                  {Array.from({ length: numPages ?? 0 }, (_, i) => i + 1).map((pageNumber) => (
                    <div key={pageNumber} className={pageNumber > 1 ? "border-t border-slate-800" : undefined}>
                      <Page
                        pageNumber={pageNumber}
                        renderTextLayer={false}
                        renderAnnotationLayer={false}
                        className="w-full [&>canvas]:!w-full [&>canvas]:!h-auto"
                      />
                    </div>
                  ))}
                </Document>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
