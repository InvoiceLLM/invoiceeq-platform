"use client";

import React, { useState, useEffect } from "react";
import {
  FileText,
  ZoomIn,
  ZoomOut,
  RotateCw,
  Globe,
  Sparkles,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { ExtractedVariable } from "@/lib/trainer-service";

/**
 * Feature 6 Component: PdfViewerPanel (Task 6.5 — leftmost workspace panel)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This component renders the document column in the AI Trainer workspace.
 * It operates in three distinct visual modes:
 *
 *   MODE 0 — Session Loading (FE Gap 139):
 *     Shown while `isLoadingSession` is true, i.e. the page is awaiting a
 *     `startSession` round-trip (New Vendor / Global upload, Existing Vendor
 *     production-invoice load, or clearing a grounding document). Takes
 *     precedence over both modes below, so the panel never sits on the
 *     *previous* session's document with no sign that anything is happening.
 *
 *   MODE 1 — PDF Document Viewer Canvas:
 *     Shown when a real document is loaded (pdfUrl is set).
 *     Renders the actual PDF (via iframe — works for both the client-side blob
 *     URL of a freshly uploaded file and the real backend-served invoice PDF
 *     for Existing Vendor sessions).
 *       • Zoom controls toolbar (75% – 175%), with a real scrollable viewport
 *
 *   MODE 2 — Global Chat-Only Empty State:
 *     Shown when no document is loaded (Global scope, no optional PDF uploaded).
 *     A glassmorphism card with ambient glow explaining that Global rules do
 *     not need a PDF.
 *
 * Gap 111: this is now the narrow (~300px) leftmost of three panels rather
 * than a 50% half-screen column, and it no longer renders the extracted-field
 * summary — that moved to its own dedicated `ExtractedFieldsPanel` beside it.
 * Burying the fields under the document was the placement problem in Gap 78:
 * they sat below a viewport that grows with the document, so on anything but a
 * short single-page PDF they were pushed out of sight entirely. A panel that
 * renders the document and a panel that renders the values read from it are
 * two jobs, and they now scroll independently.
 *
 * Design: Deep navy glassmorphism surface, toolbar with glass pill controls,
 * ambient radial glow background on empty state.
 */

interface PdfViewerPanelProps {
  /** Display name of the active PDF file */
  fileName?: string;
  /** Blob URL or remote URL of the PDF document */
  pdfUrl?: string;
  /** Flag indicating Global scope with no seed document loaded */
  isGlobalScopeNoPdf?: boolean;
  /** Currently selected variable, named in a callout over the document */
  selectedVariable?: ExtractedVariable | null;
  scope?: "global" | "existing_vendor" | "new_vendor";
  vendorName?: string | null;
  /**
   * FE Gap 139: true while `app/trainer/page.tsx` is awaiting a session load
   * (upload, vendor selection, or clearing the grounding file). Drives MODE 0.
   */
  isLoadingSession?: boolean;
  /** Name of the file being uploaded, if the pending load is an upload. */
  loadingFileName?: string;
}

export default function PdfViewerPanel({
  fileName,
  pdfUrl,
  isGlobalScopeNoPdf = false,
  selectedVariable,
  scope = "global",
  vendorName,
  isLoadingSession = false,
  loadingFileName,
}: PdfViewerPanelProps) {
  // Zoom level for the document canvas; range 75% – 175%
  const [zoom, setZoom] = useState(100);

  const handleZoomIn = () => setZoom((z) => Math.min(z + 15, 175));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 15, 75));
  const handleResetZoom = () => setZoom(100);

  const [pdfError, setPdfError] = useState<string | null>(null);

  useEffect(() => {
    if (!pdfUrl) {
      setPdfError(null);
      return;
    }
    if (pdfUrl.startsWith("blob:")) {
      setPdfError(null);
      return;
    }

    // Gap 90: probe before rendering the iframe, so a missing production sample
    // shows a friendly card instead of the backend's raw error JSON rendered
    // verbatim in the PDF pane.
    //
    // Only a 404 is treated as "the document isn't there". Anything else is
    // treated as an inconclusive probe and the iframe is rendered anyway:
    // claiming a document is unavailable when the *probe* is what failed is a
    // worse outcome than letting the browser's own PDF viewer try. This is not
    // hypothetical -- the backend route is `@router.get` only (FastAPI's
    // APIRouter, unlike a bare Starlette Route, does not add HEAD alongside
    // GET), so this HEAD only succeeds because Next 14 auto-implements HEAD by
    // calling the exported GET, whose handler forwards a hardcoded `method:
    // "GET"` inward. Change that proxy to forward the real method and every
    // probe becomes a 405 -- under the old `!res.ok` check that would have
    // shown "Document Unavailable" on every perfectly good PDF.
    fetch(pdfUrl, { method: "HEAD" })
      .then((res) => {
        if (res.status === 404) {
          setPdfError("Production sample PDF is missing or unavailable.");
        } else if (res.status >= 500) {
          setPdfError("Failed to retrieve sample PDF.");
        } else {
          setPdfError(null);
        }
      })
      .catch(() => {
        // A genuine network failure -- the iframe would fail the same way.
        setPdfError("Failed to retrieve sample PDF.");
      });
  }, [pdfUrl]);

  // ── Estimated progress while a session loads (FE Gap 139) ──────────────
  // Same approach, and deliberately the same visual language, as QnAPanel's
  // correction progress bar: the backend's session-create call
  // (`routers/trainer.py::upload_transient_file` / `start_global_session` /
  // `start_session`) runs `_run_ocr_split` + `run_extraction_agent`
  // synchronously and reports no incremental progress, so this is a
  // client-side elapsed-time estimate, not a server-reported percentage. It
  // approaches 92% asymptotically and only reaches completion when the real
  // response lands and this whole mode unmounts, so it can never claim to be
  // finished while the user is still waiting.
  const [progressPct, setProgressPct] = useState(0);
  const ESTIMATED_DURATION_MS = 32000;
  useEffect(() => {
    if (!isLoadingSession) {
      setProgressPct(0);
      return;
    }
    const startedAt = Date.now();
    const interval = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const pct = Math.min(92, Math.round((elapsed / ESTIMATED_DURATION_MS) * 92));
      setProgressPct(pct);
    }, 300);
    return () => clearInterval(interval);
  }, [isLoadingSession]);

  // ── MODE 0: Session Loading ────────────────────────────────────────────
  // Checked before every other mode: during a load the previous session's
  // document (or empty-state card) is exactly what made this read as frozen.
  if (isLoadingSession) {
    const isUpload = Boolean(loadingFileName);
    const heading = isUpload
      ? "Processing Sample Document"
      : scope === "existing_vendor"
      ? "Loading Production Invoice"
      : "Preparing Sandbox";

    // Named stages, mapped onto the same elapsed-time estimate. The wording
    // tracks what the backend is actually doing in that window rather than a
    // generic spinner caption.
    const stages = isUpload
      ? ["Uploading document…", "Running OCR and page split…", "Extracting fields…", "Finalizing…"]
      : scope === "existing_vendor"
      ? ["Fetching production invoice…", "Running OCR and page split…", "Extracting fields…", "Finalizing…"]
      : ["Clearing grounding document…", "Restarting sandbox session…", "Preparing rules…", "Finalizing…"];

    const stageIndex =
      progressPct < 20 ? 0 : progressPct < 55 ? 1 : progressPct < 85 ? 2 : 3;

    return (
      <div
        data-testid="trainer-pdf-loading"
        className="h-full flex flex-col items-center justify-center p-4 bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl text-center backdrop-blur-md relative overflow-hidden shadow-2xl shadow-black/30"
      >
        {/* Ambient radial glow orbs — decorative only, matching MODE 2 */}
        <div className="absolute -top-28 -left-28 w-80 h-80 bg-blue-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-28 -right-28 w-80 h-80 bg-indigo-600/8 rounded-full blur-3xl pointer-events-none" />

        {/* Central spinner badge */}
        <div className="w-12 h-12 rounded-xl bg-[#111827] border border-blue-500/25 flex items-center justify-center text-blue-400 mb-4 shadow-2xl shadow-blue-500/15 shrink-0">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>

        <h3 className="text-sm font-semibold text-white mb-1 tracking-tight">{heading}</h3>
        {loadingFileName && (
          <p
            className="text-[11px] text-slate-400 max-w-full truncate mb-3"
            title={loadingFileName}
          >
            {loadingFileName}
          </p>
        )}

        {/* Staged progress — same bouncing dots + bar + percentage as QnAPanel's
            "Analyzing correction…" indicator, so both waits in this workspace
            read as the same thing happening. */}
        <div className="w-full max-w-[240px] bg-[#111827] border border-[#1E2D45] rounded-2xl px-3 py-2.5 mt-1">
          <div className="flex items-center gap-1.5">
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                style={{ animationDelay: `${delay}ms` }}
                className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
              />
            ))}
            <span className="ml-2 text-[11px] text-slate-400 truncate">
              {stages[stageIndex]}
            </span>
            <span className="ml-auto text-[10px] font-mono text-blue-400 shrink-0">
              {progressPct}%
            </span>
          </div>
          <div className="mt-2 h-1 bg-[#1E2D45] rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-300 ease-out rounded-full"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        <p className="text-[10px] text-slate-500 mt-3 leading-relaxed">
          OCR and field extraction run on the server — this can take up to a
          minute for a dense invoice.
        </p>
      </div>
    );
  }

  // ── MODE 2: Global Scope Chat-Only Empty State ──────────────────────────
  if (isGlobalScopeNoPdf || !pdfUrl) {
    const isGlobal = scope === "global";
    const isExisting = scope === "existing_vendor";

    const getTitle = () => {
      if (isGlobal) return "Global Rule Grounding Sandbox";
      if (isExisting) return "Existing Vendor Sandbox";
      return "New Vendor Sandbox";
    };

    // Gap 111: reworded for a ~300px column. The old copy said "chat directly
    // on the right" and "browse a sample invoice PDF above", which described
    // the two-panel layout this gap replaced -- chat is no longer immediately
    // to the right of this panel (the extracted fields are), so the directions
    // would have been actively wrong. It now names the control instead of its
    // position, which stays true regardless of how the panels are arranged.
    const getDescription = () => {
      if (isGlobal) {
        return (
          <>
            Tenant-wide rules need no vendor PDF. Teach or refine them in the chat
            panel, or ground this sandbox with a sample document.
          </>
        );
      }
      if (isExisting) {
        return (
          <>
            Refining rules for{" "}
            <span className="text-blue-400 font-medium">{vendorName || "the selected vendor"}</span>
            . Pick a vendor in the Ground step to load a real production invoice.
          </>
        );
      }
      return (
        <>
          Cold-starting a new vendor. Use Browse PDF in the Ground step to load a
          sample invoice and begin field extraction.
        </>
      );
    };

    return (
      <div className="h-full flex flex-col items-center justify-center p-4 bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl text-center backdrop-blur-md relative overflow-hidden shadow-2xl shadow-black/30">
        {/* Ambient radial glow orbs — decorative only */}
        <div className="absolute -top-28 -left-28 w-80 h-80 bg-blue-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-28 -right-28 w-80 h-80 bg-indigo-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-48 h-48 bg-blue-500/5 rounded-full blur-2xl pointer-events-none" />

        {/* Central Icon Badge */}
        <div className="w-12 h-12 rounded-xl bg-[#111827] border border-blue-500/25 flex items-center justify-center text-blue-400 mb-4 shadow-2xl shadow-blue-500/15 relative shrink-0">
          <Globe className="w-6 h-6" />
          {/* Floating sparkle accent */}
          <Sparkles className="w-3 h-3 text-blue-300 absolute -top-1.5 -right-1.5 animate-pulse" />
        </div>

        {/* Heading & description */}
        <h3 className="text-sm font-semibold text-white mb-2 tracking-tight">
          {getTitle()}
        </h3>
        <p className="text-[11px] text-slate-400 leading-relaxed">
          {getDescription()}
        </p>
      </div>
    );
  }

  // ── MODE 1: Interactive PDF Document Viewer Canvas ─────────────────────
  return (
    <div className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30">
      {/* ── Viewer Top Controls Toolbar ──────────────────────────────── */}
      {/* Gap 111: this panel is now ~300px wide, not half the screen. The
          toolbar therefore stacks the filename above the zoom controls rather
          than sharing one row with them -- at 300px a single row put the
          filename down to a couple of characters before the ellipsis. */}
      <div className="px-3 py-2 bg-[#0B1120]/90 border-b border-[#1E2D45] flex flex-col gap-2 text-xs text-slate-300 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-3.5 h-3.5 text-blue-400 shrink-0" />
          <span className="font-medium text-white truncate" title={fileName}>
            {fileName}
          </span>
        </div>

        <div className="flex items-center justify-between gap-2">
          {/* Zoom pill */}
          <div className="flex items-center gap-0.5 bg-[#111827]/80 p-0.5 rounded-xl border border-[#1E2D45]">
            <button
              onClick={handleZoomOut}
              title="Zoom Out"
              aria-label="Zoom out"
              className="p-1 hover:bg-[#1E293B] rounded-lg text-slate-400 hover:text-white transition-colors"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <span className="px-1.5 text-[11px] font-mono text-slate-300 min-w-[38px] text-center select-none">
              {zoom}%
            </span>
            <button
              onClick={handleZoomIn}
              title="Zoom In"
              aria-label="Zoom in"
              className="p-1 hover:bg-[#1E293B] rounded-lg text-slate-400 hover:text-white transition-colors"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleResetZoom}
              title="Reset Zoom"
              aria-label="Reset zoom"
              className="p-1 hover:bg-[#1E293B] rounded-lg text-slate-400 hover:text-white transition-colors border-l border-[#1E2D45] ml-0.5 pl-1.5"
            >
              <RotateCw className="w-3.5 h-3.5" />
            </button>
          </div>

          <span className="px-2 py-0.5 rounded-lg bg-[#111827] text-[10px] text-slate-400 border border-[#1E2D45] font-mono shrink-0">
            Page 1 / 1
          </span>
        </div>
      </div>

      {/* ── PDF Viewport — the actual uploaded/loaded document ─────────── */}
      {/*
        Gap 78 + Gap 111.2 — how the document is actually sized, and why this
        is not a CSS transform any more.

        It used to be `transform: scale(zoom/100)` on the frame, inside a
        parent with `overflow-hidden`. Two things were wrong with that:

          1. A transform does not change the element's layout box, so scaling
             up produced no scrollbars anywhere -- the enlarged document was
             simply clipped by the `overflow-hidden` parent, with no way to
             reach the part that had been pushed out of view. Zooming in past
             ~115% therefore *lost* content instead of magnifying it, which is
             the "uploaded PDF doesn't display well" of Gap 78.
          2. Scaling an <iframe> scales its rendered output, so text got
             blurrier the further in you zoomed, rather than sharper.

        Sizing the frame in percent instead fixes both: the box genuinely grows,
        so the `overflow-auto` viewport below produces real scrollbars and every
        part of the page stays reachable, and the browser's own PDF renderer
        re-lays out at the new size so zooming in actually resolves more detail.

        `overflow-auto` here is also Gap 111.2's cap: this element is the only
        scroll container for the document. The panel itself is `h-full` inside
        the workspace's `min-h-0` row, so a long or multi-page PDF scrolls
        *within* this box and can never push the panels beside it out of view,
        which is what it used to do.
      */}
      <div className="flex-1 min-h-0 bg-[#050810] p-2 overflow-hidden">
        <div className="h-full w-full overflow-auto bg-[#0B1120] border border-[#1E2D45] rounded-2xl relative">
          {pdfError ? (
            <div className="flex flex-col items-center justify-center h-full p-4 text-center">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 border border-red-500/25 flex items-center justify-center text-red-400 mb-3">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <h4 className="text-xs font-semibold text-white mb-1">Document Unavailable</h4>
              <p className="text-[11px] text-slate-400">{pdfError}</p>
            </div>
          ) : (
            <div
              style={{ width: `${zoom}%`, height: `${zoom}%` }}
              className="transition-[width,height] duration-150"
            >
              <iframe
                src={pdfUrl}
                title={fileName || "Sample invoice PDF"}
                className="w-full h-full border-none"
              />
            </div>
          )}

          {/* Selected-variable callout — real bounding-box coordinates aren't
              plumbed into the trainer session yet, so this names the field
              rather than drawing a box over an unknown location on the page.
              `sticky` rather than `absolute`: an absolutely-positioned child of
              a scroll container scrolls away with the content, so at any zoom
              above 100% the callout would slide off the top of its own panel. */}
          {selectedVariable && (
            <div className="sticky bottom-2 left-2 mr-2 z-10 w-fit max-w-[calc(100%-1rem)] bg-blue-500 text-white text-[10px] px-2.5 py-1 rounded-md font-mono font-semibold shadow-lg pointer-events-none truncate">
              {selectedVariable.label}: {selectedVariable.value}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
