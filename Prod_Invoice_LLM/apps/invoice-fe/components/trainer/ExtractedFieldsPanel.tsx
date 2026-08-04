"use client";

import React from "react";
import { CheckCircle2, AlertCircle, ScanLine } from "lucide-react";
import { ExtractedVariable } from "@/lib/trainer-service";

/**
 * Feature 6 Component: ExtractedFieldsPanel — FE Gaps 78 & 111.
 *
 * The extracted field values used to live in two places, neither of them good:
 * a fixed 8-cell "Extracted Summary" grid pinned under the PDF inside
 * `PdfViewerPanel`, and a full click-to-select list behind the "Variables &
 * Rules" tab in `QnAPanel`. The first showed a hardcoded subset (so a field the
 * session actually extracted could be missing from it), and sat below a
 * viewport that grows with the document — on any PDF taller than the panel it
 * was pushed out of sight entirely, which is the "extracted fields poorly
 * placed" of Gap 78. The second was only visible if you gave up the chat you
 * were using to correct those very fields.
 *
 * This is the single dedicated column Gap 111 asked for: it renders whatever
 * the session actually extracted (no fixed field list), it scrolls on its own
 * so document length can never affect it, and it stays on screen next to the
 * chat that corrects it.
 *
 * Click-to-select is preserved from the old inspector tab — selecting a field
 * names it in a callout over the document in `PdfViewerPanel`.
 */

interface ExtractedFieldsPanelProps {
  variables: ExtractedVariable[];
  /** Currently selected field id, highlighted here and called out on the PDF. */
  selectedVariableId?: string;
  onSelectVariable?: (variable: ExtractedVariable) => void;
}

/** Below this the extraction is flagged amber — matches the old inspector. */
const LOW_CONFIDENCE = 0.8;

export default function ExtractedFieldsPanel({
  variables,
  selectedVariableId,
  onSelectVariable,
}: ExtractedFieldsPanelProps) {
  const correctedCount = variables.filter((v) => v.isCorrected).length;

  return (
    <div className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30">
      {/* ── Panel header ─────────────────────────────────────────────── */}
      <div className="px-3 py-2.5 bg-[#0B1120]/90 border-b border-[#1E2D45] shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <ScanLine className="w-3.5 h-3.5 text-blue-400 shrink-0" />
            <h2 className="text-xs font-semibold text-white truncate">Extracted Fields</h2>
          </div>
          <span className="shrink-0 px-1.5 py-0.5 rounded-md bg-blue-500/10 text-blue-400 font-mono text-[10px] border border-blue-500/20 font-semibold">
            {variables.length}
          </span>
        </div>
        {correctedCount > 0 && (
          <p className="mt-1 text-[10px] text-emerald-400 font-medium">
            {correctedCount} updated by a rule
          </p>
        )}
      </div>

      {/* ── Scrollable field list ────────────────────────────────────── */}
      {/* Gap 111.2: this panel owns its own scroll. The PDF beside it also owns
          its own. Neither can push the other -- which is the whole point of
          splitting them, since previously one long document moved everything. */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {variables.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-3 py-6 gap-2">
            <div className="w-9 h-9 rounded-xl bg-[#111827] border border-[#1E2D45] flex items-center justify-center text-slate-500">
              <ScanLine className="w-4 h-4" />
            </div>
            <p className="text-[11px] text-slate-400 font-medium">No fields yet</p>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Fields appear once a grounding PDF is loaded or a vendor seed is
              selected in the Ground step.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-[#1E2D45]">
            {variables.map((v) => {
              const isSelected = selectedVariableId === v.id;
              const isLowConfidence = !v.isCorrected && v.confidence < LOW_CONFIDENCE;

              return (
                <li key={v.id}>
                  {/* A real <button>, not a clickable <div> as the old
                      inspector used: this is keyboard-reachable and announces
                      itself, which the divide-based list never was. */}
                  <button
                    type="button"
                    onClick={() => onSelectVariable && onSelectVariable(v)}
                    aria-pressed={isSelected}
                    className={`w-full text-left px-3 py-2 transition-colors cursor-pointer ${
                      isSelected
                        ? "bg-blue-500/10 border-l-2 border-l-blue-500"
                        : "border-l-2 border-l-transparent hover:bg-[#111827]/60"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="text-[9px] text-slate-500 uppercase tracking-wider font-mono truncate">
                        {v.label}
                      </span>
                      {v.isCorrected ? (
                        <span title="Updated by a rule" className="shrink-0">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                        </span>
                      ) : isLowConfidence ? (
                        <span
                          title={`Low confidence (${Math.round(v.confidence * 100)}%)`}
                          className="shrink-0"
                        >
                          <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
                        </span>
                      ) : null}
                    </div>

                    {/* `break-words` rather than `truncate`: in a 220px column a
                        long vendor name or a full address would otherwise be
                        cut off, and an extracted value you cannot read is the
                        one thing this panel exists to prevent. */}
                    <span
                      className={`mt-0.5 block font-mono text-[11px] font-semibold break-words ${
                        v.isCorrected ? "text-emerald-400" : "text-white"
                      }`}
                    >
                      {v.value}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* ── Footer hint ──────────────────────────────────────────────── */}
      {variables.length > 0 && (
        <div className="px-3 py-1.5 border-t border-[#1E2D45] bg-[#0B1120]/90 shrink-0">
          <p className="text-[9px] text-slate-500 text-center">
            Click a field to call it out on the document
          </p>
        </div>
      )}
    </div>
  );
}
