"use client";

import React, { useState, useEffect } from "react";
import {
  FileText,
  ZoomIn,
  ZoomOut,
  RotateCw,
  Globe,
  Sparkles,
  Layers,
  ShieldCheck,
  Maximize2,
  AlertTriangle,
} from "lucide-react";
import { ExtractedVariable } from "@/lib/trainer-service";

/**
 * Feature 6 Component: PdfViewerPanel (Task 6.5 - Left panel)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This component renders the left 50% split-panel column in the AI Trainer workspace.
 * It operates in two distinct visual modes:
 *
 *   MODE 1 — PDF Document Viewer Canvas:
 *     Shown when a real document is loaded (pdfUrl is set).
 *     Renders the actual PDF (via iframe — works for both the client-side blob
 *     URL of a freshly uploaded file and the real backend-served invoice PDF
 *     for Existing Vendor sessions), plus a live summary strip built from the
 *     session's real extracted field values (not sample/placeholder data).
 *       • Zoom controls toolbar (75% – 175%)
 *
 *   MODE 2 — Global Chat-Only Empty State:
 *     Shown when no document is loaded (Global scope, no optional PDF uploaded).
 *     A visually rich glassmorphism card with ambient glow explaining
 *     that Global rules do not need a PDF. Includes two info feature cards.
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
  /** Currently selected variable for bounding box highlighting */
  selectedVariable?: ExtractedVariable | null;
  /** Callback fired when user selects a variable in the viewer */
  onSelectVariable?: (variable: ExtractedVariable) => void;
  /** Real extracted scalar fields for this session — drives the live summary strip. */
  variables?: ExtractedVariable[];
  scope?: "global" | "existing_vendor" | "new_vendor";
  vendorName?: string | null;
}

export default function PdfViewerPanel({
  fileName,
  pdfUrl,
  isGlobalScopeNoPdf = false,
  selectedVariable,
  variables = [],
  scope = "global",
  vendorName,
}: PdfViewerPanelProps) {
  const getVar = (key: string) => variables.find((v) => v.key === key)?.value;
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

  // ── MODE 2: Global Scope Chat-Only Empty State ──────────────────────────
  if (isGlobalScopeNoPdf || !pdfUrl) {
    const isGlobal = scope === "global";
    const isExisting = scope === "existing_vendor";

    const getTitle = () => {
      if (isGlobal) return "Global Rule Grounding Sandbox";
      if (isExisting) return "Existing Vendor Sandbox";
      return "New Vendor Sandbox";
    };

    const getDescription = () => {
      if (isGlobal) {
        return (
          <>
            Tenant-wide rules apply globally. No specific vendor PDF is required — chat directly on the right to teach or refine global constraints, or upload a sample PDF for visual grounding.
          </>
        );
      }
      if (isExisting) {
        return (
          <>
            Refining rules for vendor: <span className="text-blue-400 font-medium">{vendorName || "Selected Vendor"}</span>. Select a vendor above to load active rules, or upload a PDF to ground the sandbox.
          </>
        );
      }
      return (
        <>
          Teaching rules for a new vendor. Drag and drop or browse a sample invoice PDF above to initialize OCR field extraction and start training.
        </>
      );
    };

    return (
      <div className="h-full flex flex-col items-center justify-center p-6 bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl text-center backdrop-blur-md relative overflow-hidden shadow-2xl shadow-black/30">
        {/* Ambient radial glow orbs — decorative only */}
        <div className="absolute -top-28 -left-28 w-80 h-80 bg-blue-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-28 -right-28 w-80 h-80 bg-indigo-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-48 h-48 bg-blue-500/5 rounded-full blur-2xl pointer-events-none" />

        {/* Central Icon Badge */}
        <div className="w-16 h-16 rounded-xl bg-[#111827] border border-blue-500/25 flex items-center justify-center text-blue-400 mb-5 shadow-2xl shadow-blue-500/15 relative">
          <Globe className="w-7 h-7" />
          {/* Floating sparkle accent */}
          <Sparkles className="w-3.5 h-3.5 text-blue-300 absolute -top-1.5 -right-1.5 animate-pulse" />
        </div>

        {/* Heading & description */}
        <h3 className="text-base font-semibold text-white mb-2 tracking-tight">
          {getTitle()}
        </h3>
        <p className="text-xs text-slate-400 max-w-sm mb-6 leading-relaxed">
          {getDescription()}
        </p>

        {/* Step-by-Step Progress Indicator */}
        <div className="w-full max-w-sm bg-[#0D131F]/90 border border-[#1E2D45] rounded-xl p-4">
          <p className="text-[9px] uppercase font-bold text-slate-500 tracking-wider mb-3 text-center">
            How to teach the sandbox
          </p>
          <div className="flex items-center justify-between text-left text-xs gap-2">
            <div className="flex-1 flex flex-col items-center text-center">
              <span className="w-5.5 h-5.5 w-6 h-6 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-400 font-semibold flex items-center justify-center mb-1 text-[10px]">
                1
              </span>
              <span className="font-semibold text-slate-300 text-[10px]">Set Scope</span>
              <span className="text-[9px] text-slate-500">Global vs Vendor</span>
            </div>
            
            <div className="h-0.5 w-4 bg-[#1E2D45] shrink-0 self-center -mt-4" />

            <div className="flex-1 flex flex-col items-center text-center">
              <span className="w-5.5 h-5.5 w-6 h-6 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-semibold flex items-center justify-center mb-1 text-[10px]">
                2
              </span>
              <span className="font-semibold text-slate-300 text-[10px]">Load PDF</span>
              <span className="text-[9px] text-slate-500">Optional grounding</span>
            </div>

            <div className="h-0.5 w-4 bg-[#1E2D45] shrink-0 self-center -mt-4" />

            <div className="flex-1 flex flex-col items-center text-center">
              <span className="w-5.5 h-5.5 w-6 h-6 rounded-full bg-violet-500/10 border border-violet-500/30 text-violet-400 font-semibold flex items-center justify-center mb-1 text-[10px]">
                3
              </span>
              <span className="font-semibold text-slate-300 text-[10px]">Teach AI</span>
              <span className="text-[9px] text-slate-500">Chat corrections</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── MODE 1: Interactive PDF Document Viewer Canvas ─────────────────────
  return (
    <div className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30">
      {/* ── Viewer Top Controls Toolbar ──────────────────────────────── */}
      <div className="h-12 px-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between gap-3 text-xs text-slate-300 shrink-0">
        {/* File name + page indicator */}
        <div className="flex items-center gap-2.5 min-w-0">
          <FileText className="w-4 h-4 text-blue-400 shrink-0" />
          <span className="font-medium text-white truncate max-w-[180px]">{fileName}</span>
          <span className="px-2 py-0.5 rounded-lg bg-[#111827] text-[10px] text-slate-400 border border-[#1E2D45] font-mono">
            Page 1 / 1
          </span>
        </div>

        {/* Right: Zoom controls + expand icon */}
        <div className="flex items-center gap-2">
          {/* Zoom pill */}
          <div className="flex items-center gap-0.5 bg-[#111827]/80 p-0.5 rounded-xl border border-[#1E2D45]">
            <button
              onClick={handleZoomOut}
              title="Zoom Out"
              className="p-1.5 hover:bg-[#1E293B] rounded-lg text-slate-400 hover:text-white transition-colors"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <span className="px-2.5 text-[11px] font-mono text-slate-300 min-w-[44px] text-center select-none">
              {zoom}%
            </span>
            <button
              onClick={handleZoomIn}
              title="Zoom In"
              className="p-1.5 hover:bg-[#1E293B] rounded-lg text-slate-400 hover:text-white transition-colors"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleResetZoom}
              title="Reset Zoom"
              className="p-1.5 hover:bg-[#1E293B] rounded-lg text-slate-400 hover:text-white transition-colors border-l border-[#1E2D45] ml-0.5 pl-1.5"
            >
              <RotateCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Expand icon (decorative for now, future full-screen) */}
          <button
            title="Expand"
            className="p-1.5 rounded-xl border border-[#1E2D45] bg-[#111827]/80 text-slate-400 hover:text-white hover:bg-[#1E293B] transition-colors"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── PDF Viewport — the actual uploaded/loaded document ─────────── */}
      <div className="flex-1 min-h-0 bg-[#050810] p-3 flex flex-col gap-3">
        <div
          style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
          className="transition-transform duration-150 flex-1 min-h-0 bg-[#0B1120] border border-[#1E2D45] rounded-2xl overflow-hidden relative"
        >
          {pdfError ? (
            <div className="flex flex-col items-center justify-center h-full p-6 text-center bg-[#0B1120] rounded-2xl relative">
              <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/25 flex items-center justify-center text-red-400 mb-4">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <h4 className="text-sm font-semibold text-white mb-1">Document Unavailable</h4>
              <p className="text-xs text-slate-400 max-w-xs">{pdfError}</p>
            </div>
          ) : (
            <iframe src={pdfUrl} title={fileName || "Sample invoice PDF"} className="w-full h-full border-none" />
          )}

          {/* Selected-variable callout — real bounding-box coordinates aren't
              plumbed into the trainer session yet, so this names the field
              rather than drawing a box over an unknown location on the page. */}
          {selectedVariable && (
            <div className="absolute top-3 left-3 bg-blue-500 text-white text-[10px] px-2.5 py-1 rounded-md font-mono font-semibold shadow-lg pointer-events-none">
              Selected: {selectedVariable.label} = {selectedVariable.value}
            </div>
          )}
        </div>

        {/* ── Live Extracted Summary — real session data, not a mock ──── */}
        <div className="shrink-0 bg-[#0B1120] border border-[#1E2D45] rounded-2xl p-4 text-xs">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[9px] text-slate-500 uppercase tracking-wider font-semibold">
              Extracted Summary (live)
            </span>
            <span className="inline-block px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 font-mono text-[10px] border border-blue-500/20 font-semibold">
              {variables.length} FIELDS
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3">
            <SummaryField label="Vendor" value={getVar("vendor_name")} />
            <SummaryField label="Invoice #" value={getVar("invoice_number")} />
            <SummaryField label="Invoice Date" value={getVar("invoice_date")} />
            <SummaryField label="Due Date" value={getVar("due_date")} />
            <SummaryField label="Subtotal" value={getVar("subtotal")} />
            <SummaryField label="Tax Amount" value={getVar("tax_amount")} />
            <SummaryField label="Discount" value={getVar("discount_amount")} />
            <SummaryField label="Grand Total" value={getVar("grand_total")} highlight />
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryField({ label, value, highlight }: { label: string; value?: string; highlight?: boolean }) {
  return (
    <div>
      <span className="text-[9px] text-slate-500 uppercase tracking-wider block mb-1">{label}</span>
      <span className={highlight ? "font-mono text-emerald-400 font-semibold" : "font-mono text-white"}>
        {value ?? "—"}
      </span>
    </div>
  );
}
