"use client";

import React from "react";
import { Check, FileText, X } from "lucide-react";

export type VendorPanelTab = "rules" | "style";
export type TrainerSessionMode = "qa_test" | "rule_creation";

/**
 * Feature 14 Component: TrainerControlBar
 *
 * FOR MANAGERS & DEVELOPERS:
 * The bar above the Trainer workspace. FE Gap 220 gave it two sections —
 * "Global Rules" and "Vendor Rules". **The Global section is gone.**
 *
 * Why: Global-scope rule *creation* was removed from the backend
 * (`POST /trainer/sessions/global` is now 410 Gone, and `trainer_commit()`
 * refuses a `scope="global"` session outright). A Global session had no document
 * and no vendor, so a rule created there was anchored to nothing — which is
 * precisely the ungrounded-rule problem the redesign exists to fix. Keeping the
 * tab would have offered a destination every write path now rejects.
 *
 * **Already-committed Global rules are untouched and still apply.** They are
 * still read by the extraction prompt builders, the queue worker and the chat
 * agent; only the ability to author new ones from this screen is removed.
 *
 * What remains is the vendor workspace, with two panel tabs:
 *   * Extraction Rules — the alert-anchored correction flow.
 *   * Chat Response Style — tenant-wide answering style (length/tone/custom
 *     instructions). Note it already lived under the *vendor* branch before this
 *     change, despite FE Gap 221's entry saying "Global Rules section"; that
 *     entry was stale, and the tracker now carries a correction.
 */

interface TrainerControlBarProps {
  panelTab: VendorPanelTab;
  onPanelTabChange: (tab: VendorPanelTab) => void;
  sessionMode: TrainerSessionMode;
  onSessionModeChange: (mode: TrainerSessionMode) => void;
  /** Name of the vendor/party the active session is anchored to. */
  vendorName?: string;
  /** File name of the session's source document. */
  activeFileName?: string;
  /** Clears the session and returns to the entry picker. */
  onChangeDocument?: () => void;
  /** True once a session is loaded. */
  hasSession: boolean;
  disabled?: boolean;
}

function StepLabel({
  step,
  label,
  done,
}: {
  step: number;
  label: string;
  done: boolean;
}) {
  const toneCls = done
    ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400"
    : "bg-blue-500/10 border-blue-500/40 text-blue-400";

  return (
    <div className="flex items-center gap-1.5 shrink-0 select-none">
      <span
        className={`w-4 h-4 rounded-full border flex items-center justify-center text-[9px] font-mono transition-colors ${toneCls}`}
      >
        {done ? <Check className="w-2.5 h-2.5" /> : step}
      </span>
      <span
        className={`hidden md:inline text-[10px] font-semibold uppercase tracking-wider ${
          done ? "text-slate-300" : "text-slate-400"
        }`}
      >
        {label}
      </span>
    </div>
  );
}

export default function TrainerControlBar({
  panelTab,
  onPanelTabChange,
  sessionMode,
  onSessionModeChange,
  vendorName,
  activeFileName,
  onChangeDocument,
  hasSession,
  disabled = false,
}: TrainerControlBarProps) {
  return (
    <div className="px-4 py-2.5 border-b border-[#222D3D] bg-[#0D131F]/90 shrink-0">
      <div className="flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-0 bg-[#0B1120]/60 border border-[#1E2D45] rounded-2xl px-3 py-2">
        {/* Step 1 — the document this session is anchored to. */}
        <div className="flex items-center gap-3 min-w-0">
          <StepLabel step={1} label="Document" done={hasSession} />
          {hasSession ? (
            <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1.5 rounded-lg text-[11px] text-emerald-300 min-w-0">
              <FileText className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate max-w-[200px] font-semibold">
                {vendorName || activeFileName || "Loaded invoice"}
              </span>
              {onChangeDocument && (
                <button
                  type="button"
                  onClick={onChangeDocument}
                  disabled={disabled}
                  title="Choose a different document"
                  data-testid="trainer-change-document"
                  className="text-emerald-400/60 hover:text-red-400 hover:bg-red-500/10 p-0.5 rounded transition-colors cursor-pointer disabled:opacity-40"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          ) : (
            <span className="text-[11px] font-medium text-slate-400 select-none">
              Pick an invoice or upload a PDF
            </span>
          )}
        </div>

        <div
          aria-hidden="true"
          className="lg:mx-4 h-px w-full lg:h-8 lg:w-px bg-[#1E2D45] shrink-0"
        />

        {/* Step 2 — what you're doing with it. */}
        <div className="flex items-center gap-3 min-w-0 lg:flex-1 flex-wrap">
          <StepLabel step={2} label="Workspace" done={hasSession} />

          <div className="flex items-center gap-1">
            {(["rules", "style"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                data-testid={`trainer-tab-${tab}`}
                onClick={() => onPanelTabChange(tab)}
                className={`px-3 py-1 rounded-lg text-[11px] font-medium border transition-colors ${
                  panelTab === tab
                    ? "bg-violet-600/20 border-violet-500/40 text-violet-200"
                    : "border-[#222D3D] text-slate-400 hover:text-slate-200"
                }`}
              >
                {tab === "rules" ? "Extraction Rules" : "Chat Response Style"}
              </button>
            ))}
          </div>

          {/* Rule creation vs. asking questions. Two modes, never one ambiguous
              text box — see QaChatPanel for why that separation is load-bearing. */}
          {hasSession && panelTab === "rules" && (
            <div className="flex items-center gap-1 ml-auto">
              {(["rule_creation", "qa_test"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  data-testid={`trainer-mode-${mode}`}
                  onClick={() => onSessionModeChange(mode)}
                  disabled={disabled}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium border transition-colors disabled:opacity-40 ${
                    sessionMode === mode
                      ? "bg-blue-600/20 border-blue-500/40 text-blue-200"
                      : "border-[#222D3D] text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {mode === "qa_test" ? "Ask Questions" : "Correct Alerts"}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
