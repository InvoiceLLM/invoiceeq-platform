"use client";

import React, { useState } from "react";
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
 *     Renders a realistic document preview with:
 *       • Zoom controls toolbar (75% – 175%)
 *       • Simulated invoice body with OCR field table
 *       • Interactive blue dashed bounding-box highlight on variable selection
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
}

export default function PdfViewerPanel({
  fileName,
  pdfUrl,
  isGlobalScopeNoPdf = false,
  selectedVariable,
}: PdfViewerPanelProps) {
  // Zoom level for the document canvas; range 75% – 175%
  const [zoom, setZoom] = useState(100);

  const handleZoomIn = () => setZoom((z) => Math.min(z + 15, 175));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 15, 75));
  const handleResetZoom = () => setZoom(100);

  // ── MODE 2: Global Scope Chat-Only Empty State ──────────────────────────
  if (isGlobalScopeNoPdf || !pdfUrl) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-10 bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl text-center backdrop-blur-md relative overflow-hidden shadow-2xl shadow-black/30">
        {/* Ambient radial glow orbs — decorative only */}
        <div className="absolute -top-28 -left-28 w-80 h-80 bg-blue-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-28 -right-28 w-80 h-80 bg-indigo-600/8 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-48 h-48 bg-blue-500/5 rounded-full blur-2xl pointer-events-none" />

        {/* Central Icon Badge */}
        <div className="w-18 h-18 w-[72px] h-[72px] rounded-2xl bg-[#111827] border border-blue-500/25 flex items-center justify-center text-blue-400 mb-7 shadow-2xl shadow-blue-500/15 relative">
          <Globe className="w-8 h-8" />
          {/* Floating sparkle accent */}
          <Sparkles className="w-4 h-4 text-blue-300 absolute -top-2 -right-2 animate-pulse" />
        </div>

        {/* Heading & description */}
        <h3 className="text-lg font-semibold text-white mb-2 tracking-tight">
          Global Rule Grounding Sandbox
        </h3>
        <p className="text-sm text-slate-400 max-w-sm mb-9 leading-relaxed">
          You are editing <span className="text-blue-400 font-medium">tenant-wide rules</span>.
          No specific vendor PDF is required — chat directly on the right to teach or refine global constraints.
          Optionally upload a sample PDF above for visual grounding.
        </p>

        {/* Feature Info Cards grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-md text-left">
          {/* Card 1: Tenant-Wide Precedence */}
          <div className="p-4 bg-[#0D131F]/90 border border-blue-500/15 rounded-2xl hover:border-blue-500/30 transition-colors">
            <div className="flex items-center gap-2 text-xs font-semibold text-blue-400 mb-2">
              <ShieldCheck className="w-4 h-4" />
              <span>Tenant-Wide Precedence</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Applied on the first extraction pass before vendor identity is resolved.
            </p>
          </div>

          {/* Card 2: Automatic Re-Audit */}
          <div className="p-4 bg-[#0D131F]/90 border border-indigo-500/15 rounded-2xl hover:border-indigo-500/30 transition-colors">
            <div className="flex items-center gap-2 text-xs font-semibold text-indigo-400 mb-2">
              <Layers className="w-4 h-4" />
              <span>Automatic Re-Audit</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Committing re-evaluates past invoices across all vendors in the background.
            </p>
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

      {/* ── PDF Viewport Canvas Area ──────────────────────────────────── */}
      <div className="flex-1 bg-[#050810] p-4 overflow-auto flex items-start justify-center relative">
        {/* Zoomed document page card */}
        <div
          style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
          className="transition-transform duration-150 w-full max-w-[540px] bg-[#0B1120] border border-[#1E2D45] rounded-2xl shadow-2xl p-7 relative min-h-[600px] text-slate-300 text-xs select-none"
        >
          {/* ── Document Header Row ───────────────────────────────── */}
          <div className="border-b border-[#1E2D45] pb-4 mb-5 flex justify-between items-start">
            <div>
              <h2 className="text-sm font-bold text-white tracking-wide uppercase">Invoice Document</h2>
              <p className="text-[11px] text-slate-500 mt-0.5">Sample for rule verification</p>
            </div>
            <span className="inline-block px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 font-mono text-[10px] border border-blue-500/20 font-semibold">
              OCR PROCESSED
            </span>
          </div>

          {/* ── Vendor & Date Block ───────────────────────────────── */}
          <div className="grid grid-cols-2 gap-4 bg-[#070D1A] p-3.5 rounded-xl border border-[#1E2D45] mb-5">
            <div>
              <span className="text-[9px] text-slate-500 block uppercase tracking-wider font-semibold mb-1">Vendor</span>
              <span className="font-semibold text-white text-sm">Acme Logistics Corp</span>
            </div>
            <div className="text-right">
              <span className="text-[9px] text-slate-500 block uppercase tracking-wider font-semibold mb-1">Invoice Date</span>
              <span className="font-mono text-emerald-400 font-semibold">19/07/2026</span>
            </div>
          </div>

          {/* ── Invoice Number & PO Row ───────────────────────────── */}
          <div className="grid grid-cols-2 gap-4 mb-5 text-[11px]">
            <div>
              <span className="text-[9px] text-slate-500 uppercase tracking-wider block mb-1">Invoice No.</span>
              <span className="font-mono text-white">INV-2026-00742</span>
            </div>
            <div className="text-right">
              <span className="text-[9px] text-slate-500 uppercase tracking-wider block mb-1">PO Reference</span>
              <span className="font-mono text-white">PO-88213-A</span>
            </div>
          </div>

          {/* ── Line Items Table ──────────────────────────────────── */}
          <div className="space-y-1.5 mb-5">
            <span className="text-[9px] text-slate-500 block uppercase tracking-wider font-semibold mb-2">Extracted Line Items</span>
            <div className="border border-[#1E2D45] rounded-xl overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[#111827] text-slate-500 text-[9px] uppercase tracking-wider">
                    <th className="p-2.5 font-semibold">Description</th>
                    <th className="p-2.5 text-right font-semibold">Qty</th>
                    <th className="p-2.5 text-right font-semibold">Rate</th>
                    <th className="p-2.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1E2D45] text-[11px]">
                  <tr className="hover:bg-[#111827]/60 transition-colors">
                    <td className="p-2.5 text-slate-200">Freight Express Handling</td>
                    <td className="p-2.5 text-right text-slate-400">10</td>
                    <td className="p-2.5 text-right text-slate-400">$450.00</td>
                    <td className="p-2.5 text-right text-white font-mono font-medium">$4,500.00</td>
                  </tr>
                  <tr className="hover:bg-[#111827]/60 transition-colors">
                    <td className="p-2.5 text-slate-200">Container Storage Fee</td>
                    <td className="p-2.5 text-right text-slate-400">25</td>
                    <td className="p-2.5 text-right text-slate-400">$318.00</td>
                    <td className="p-2.5 text-right text-white font-mono font-medium">$7,950.00</td>
                  </tr>
                  <tr className="hover:bg-[#111827]/60 transition-colors">
                    <td className="p-2.5 text-slate-200">VAT (18%)</td>
                    <td className="p-2.5 text-right text-slate-400">—</td>
                    <td className="p-2.5 text-right text-slate-400">18%</td>
                    <td className="p-2.5 text-right text-amber-400 font-mono font-medium">$2,241.00</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Total Amount Row ──────────────────────────────────── */}
          <div className="pt-4 border-t border-[#1E2D45] flex justify-between items-center">
            <span className="text-slate-400 text-sm">Total Amount Payable</span>
            <span className="text-white font-mono text-base bg-emerald-500/10 px-3.5 py-1.5 rounded-xl border border-emerald-500/20 text-emerald-400 font-bold">
              $14,691.00
            </span>
          </div>

          {/* ── Active Bounding Box Highlight ─────────────────────── */}
          {/* Shown when the user selects a variable in the Variables Inspector */}
          {selectedVariable && (
            <div className="absolute top-[88px] left-5 right-5 p-3 border-2 border-dashed border-blue-400/70 bg-blue-500/8 rounded-xl pointer-events-none transition-all duration-300 shadow-lg shadow-blue-500/10">
              <span className="absolute -top-3.5 left-3 bg-blue-500 text-white text-[9px] px-2 py-0.5 rounded-md font-mono font-bold tracking-wide shadow-md">
                ⬛ BBOX · {selectedVariable.label} = {selectedVariable.value}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
