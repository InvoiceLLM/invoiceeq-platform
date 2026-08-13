"use client";

import React from "react";
import { Check } from "lucide-react";
import { TrainerScope, VendorOption } from "@/lib/trainer-service";
import TrainerUploader from "./TrainerUploader";

export type TrainerSection = "global" | "vendor";
export type VendorEntryMode = "existing" | "new";
export type TrainerSessionMode = "qa_test" | "rule_creation";
export type GlobalSubTab = "rules" | "style";

interface TrainerControlBarProps {
  activeSection: TrainerSection;
  onSectionChange: (section: TrainerSection) => void;
  vendorEntryMode: VendorEntryMode;
  onVendorEntryModeChange: (mode: VendorEntryMode) => void;
  globalSubTab: GlobalSubTab;
  onGlobalSubTabChange: (tab: GlobalSubTab) => void;
  sessionMode: TrainerSessionMode;
  onSessionModeChange: (mode: TrainerSessionMode) => void;
  vendors: VendorOption[];
  selectedVendorName?: string;
  onSelectVendor: (vendorName: string) => void;
  onUploadFile: (file: File) => void;
  onClearFile?: () => void;
  activeFileName?: string;
  showVendorModeToggle?: boolean;
  disabled?: boolean;
}

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

function SectionTabs({
  active,
  onChange,
  disabled,
}: {
  active: TrainerSection;
  onChange: (s: TrainerSection) => void;
  disabled?: boolean;
}) {
  const tabs: { id: TrainerSection; label: string }[] = [
    { id: "global", label: "Global Rules" },
    { id: "vendor", label: "Vendor Rules" },
  ];
  return (
    <div className="flex items-center gap-1 bg-[#111827]/60 p-1 border border-[#1E2D45] rounded-xl">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          disabled={disabled}
          onClick={() => onChange(tab.id)}
          className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
            active === tab.id
              ? "bg-blue-500/15 text-white border border-blue-500/40"
              : "text-slate-400 hover:text-slate-200 border border-transparent"
          } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export default function TrainerControlBar({
  activeSection,
  onSectionChange,
  vendorEntryMode,
  onVendorEntryModeChange,
  globalSubTab,
  onGlobalSubTabChange,
  sessionMode,
  onSessionModeChange,
  vendors,
  selectedVendorName,
  onSelectVendor,
  onUploadFile,
  onClearFile,
  activeFileName,
  showVendorModeToggle = false,
  disabled = false,
}: TrainerControlBarProps) {
  const activeScope: TrainerScope =
    activeSection === "global"
      ? "global"
      : vendorEntryMode === "existing"
      ? "existing_vendor"
      : "new_vendor";

  const groundingDone =
    activeSection === "global"
      ? true
      : vendorEntryMode === "existing"
      ? !!selectedVendorName
      : !!activeFileName;

  return (
    <div className="px-4 py-2.5 border-b border-[#222D3D] bg-[#0D131F]/90 shrink-0 space-y-2">
      <div className="flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-0 bg-[#0B1120]/60 border border-[#1E2D45] rounded-2xl px-3 py-2">
        <div className="flex items-center gap-3 min-w-0">
          <StepLabel step={1} label="Section" done tone="blue" />
          <SectionTabs active={activeSection} onChange={onSectionChange} disabled={disabled} />
        </div>

        <div
          aria-hidden="true"
          className="lg:mx-4 h-px w-full lg:h-8 lg:w-px bg-[#1E2D45] shrink-0"
        />

        <div className="flex items-center gap-3 min-w-0 lg:flex-1 flex-wrap">
          <StepLabel step={2} label="Setup" done={groundingDone} tone="emerald" />

          {activeSection === "global" ? (
            // Global Rules — no sub-tabs; always shows extraction rules workspace
            <span className="text-[11px] font-medium text-slate-400 select-none">Extraction Rules</span>
          ) : (
            <>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onVendorEntryModeChange("existing")}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium border ${
                    vendorEntryMode === "existing"
                      ? "bg-emerald-600/20 border-emerald-500/40 text-emerald-200"
                      : "border-[#222D3D] text-slate-400"
                  }`}
                >
                  Existing vendor
                </button>
                <button
                  type="button"
                  onClick={() => onVendorEntryModeChange("new")}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium border ${
                    vendorEntryMode === "new"
                      ? "bg-purple-600/20 border-purple-500/40 text-purple-200"
                      : "border-[#222D3D] text-slate-400"
                  }`}
                >
                  New vendor
                </button>
              </div>
              <div className="flex items-center gap-1">
                {(["rules", "style"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => onGlobalSubTabChange(tab)}
                    className={`px-3 py-1 rounded-lg text-[11px] font-medium border ${
                      globalSubTab === tab
                        ? "bg-violet-600/20 border-violet-500/40 text-violet-200"
                        : "border-[#222D3D] text-slate-400"
                    }`}
                  >
                    {tab === "rules" ? "Extraction Rules" : "Chat Response Style"}
                  </button>
                ))}
              </div>
              <TrainerUploader
                scope={activeScope}
                vendors={vendors}
                selectedVendorName={selectedVendorName}
                onSelectVendor={onSelectVendor}
                onUploadFile={onUploadFile}
                onClearFile={onClearFile}
                activeFileName={activeFileName}
              />
              {showVendorModeToggle && (
                <div className="flex items-center gap-1 ml-auto">
                  {(["qa_test", "rule_creation"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => onSessionModeChange(mode)}
                      className={`px-3 py-1 rounded-lg text-[11px] font-medium border ${
                        sessionMode === mode
                          ? "bg-blue-600/20 border-blue-500/40 text-blue-200"
                          : "border-[#222D3D] text-slate-400"
                      }`}
                    >
                      {mode === "qa_test" ? "Test Chat" : "Add Rules"}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
