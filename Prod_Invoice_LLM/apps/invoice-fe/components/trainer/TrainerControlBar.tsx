"use client";

import React from "react";
import { Check } from "lucide-react";
import { TrainerScope, VendorOption } from "@/lib/trainer-service";

import ScopeSelector from "./ScopeSelector";
import TrainerUploader from "./TrainerUploader";

/**
 * Feature 6 Component: TrainerControlBar — FE Gap 77.
 *
 * Before this, the row below the header was three independent widgets sitting
 * in a `justify-between` flex: the scope tabs on the left, a decorative
 * step-progress pill floating in the middle, and the grounding control off on
 * the far right. Nothing tied them together, so the two controls that are
 * actually one workflow ("pick a scope, then ground it") read as two unrelated
 * blocks the user had to mentally connect, and the middle pill described that
 * workflow without being part of it.
 *
 * This component is that connection made structural. One bordered bar, two
 * numbered segments separated by a rule:
 *
 *   [1] Scope   <scope tabs>   │   [2] Ground   <upload / vendor picker>
 *
 * The step numbers are no longer a separate progress widget — each one is the
 * label of the control it describes, and it ticks to a green check once that
 * step is genuinely satisfied. That removes the third block entirely while
 * keeping the progress information it carried, which is what made the row
 * crowded in the first place.
 *
 * The old bar's third element (step 3, "Teach") is deliberately not here: it
 * labels the chat panel, not a control on this row, and rendering a step marker
 * for something that isn't beside it is exactly the disconnect this gap is
 * about. The chat panel names itself.
 */

interface TrainerControlBarProps {
  activeScope: TrainerScope;
  onScopeChange: (scope: TrainerScope) => void;
  vendors: VendorOption[];
  selectedVendorName?: string;
  onSelectVendor: (vendorName: string) => void;
  onUploadFile: (file: File) => void;
  onClearFile?: () => void;
  activeFileName?: string;
  /** Disables both segments while a session request is in flight. */
  disabled?: boolean;
}

/**
 * A numbered step label. `done` swaps the number for a check — the same
 * information the old floating StepIndicator carried, attached to the control
 * it actually describes.
 */
function StepLabel({
  step,
  label,
  done,
  tone,
}: {
  step: number;
  label: string;
  done: boolean;
  tone: "blue" | "emerald";
}) {
  const toneCls = done
    ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400"
    : tone === "blue"
    ? "bg-blue-500/10 border-blue-500/40 text-blue-400"
    : "bg-slate-800/50 border-slate-700 text-slate-500";

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
  activeScope,
  onScopeChange,
  vendors,
  selectedVendorName,
  onSelectVendor,
  onUploadFile,
  onClearFile,
  activeFileName,
  disabled = false,
}: TrainerControlBarProps) {
  // Step 2 is satisfied by whatever grounds *that* scope, which differs per
  // scope and is why a single "hasFile" flag was never quite right:
  //   • Global        — grounding is optional, so the step is complete as soon
  //                     as the scope is chosen; a PDF only enriches it.
  //   • Existing Vendor — a vendor has been picked.
  //   • New Vendor    — a sample PDF has been uploaded (the only hard input).
  const groundingDone =
    activeScope === "global"
      ? true
      : activeScope === "existing_vendor"
      ? !!selectedVendorName
      : !!activeFileName;

  // What the second segment is asking for, spelled out. Gap 77 called the old
  // grounding control's purpose "not clear at a glance"; naming the input per
  // scope is the fix, rather than a bare unlabelled field beside the tabs.
  const groundingHint =
    activeScope === "global"
      ? "Optional — chat-only rules work without a document"
      : activeScope === "existing_vendor"
      ? "Pick a vendor to seed from a real production invoice"
      : "Upload a sample invoice to cold-start this vendor";

  return (
    <div className="px-4 py-2.5 border-b border-[#222D3D] bg-[#0D131F]/90 shrink-0">
      <div className="flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-0 bg-[#0B1120]/60 border border-[#1E2D45] rounded-2xl px-3 py-2">
        {/* ── Segment 1: Scope ─────────────────────────────────────────── */}
        <div className="flex items-center gap-3 min-w-0">
          <StepLabel step={1} label="Scope" done tone="blue" />
          <ScopeSelector
            activeScope={activeScope}
            onScopeChange={onScopeChange}
            disabled={disabled}
          />
        </div>

        {/* Divider — the visual join that makes this one bar rather than two
            blocks. Horizontal when the bar wraps to two rows below lg. */}
        <div
          aria-hidden="true"
          className="lg:mx-4 h-px w-full lg:h-8 lg:w-px bg-[#1E2D45] shrink-0"
        />

        {/* ── Segment 2: Ground ────────────────────────────────────────── */}
        <div className="flex items-center gap-3 min-w-0 lg:flex-1 lg:justify-start">
          <StepLabel step={2} label="Ground" done={groundingDone} tone="emerald" />

          <TrainerUploader
            scope={activeScope}
            vendors={vendors}
            selectedVendorName={selectedVendorName}
            onSelectVendor={onSelectVendor}
            onUploadFile={onUploadFile}
            onClearFile={onClearFile}
            activeFileName={activeFileName}
          />

          {/* Drops out first as the row tightens — it explains the control
              beside it, so losing it costs context, not function. */}
          <span className="hidden 2xl:inline text-[10px] text-slate-500 truncate">
            {groundingHint}
          </span>
        </div>
      </div>
    </div>
  );
}
