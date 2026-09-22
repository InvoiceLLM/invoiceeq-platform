"use client";

// =============================================================================
// FILE: components/ingestion/IngestionHistoryDrawer.tsx
// FEATURE: FE Gap 712 — contextual Ingestion History drawer on /ingestion.
//
// Relocates the durable ingestion History log (FE Gap 464) from an isolated
// sidebar route into a slide-over drawer accessible directly from the Ingestion
// screen, mirroring RuleHistoryDrawer (AI Trainer) and ChatRulesDrawer (Chat).
// =============================================================================

import React, { useEffect } from "react";
import { History, X } from "lucide-react";
import IngestionHistoryTable from "@/components/ingestion/IngestionHistoryTable";
import OpenFindingsChip from "@/components/insights/OpenFindingsChip";

interface IngestionHistoryDrawerProps {
  /** Controls drawer visibility */
  isOpen: boolean;
  /** Callback fired to dismiss drawer */
  onClose: () => void;
}

export default function IngestionHistoryDrawer({
  isOpen,
  onClose,
}: IngestionHistoryDrawerProps) {
  // Close on Escape key press
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Ingestion History"
      className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
    >
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-5xl bg-[#151B26] border-l border-[#222D3D] shadow-2xl flex flex-col h-full">
          {/* Drawer Header */}
          <div className="px-6 py-4 bg-[#0F172A] border-b border-[#222D3D] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <History className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Ingestion History &amp; Outcomes</h3>
                <p className="text-[11px] text-slate-400">
                  Every file this workspace has ingested — uploads, inbound email, connector imports and Autopilot runs
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              title="Close drawer"
              aria-label="Close drawer"
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1E293B] transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {/* Open findings summary chip (if active) */}
            <OpenFindingsChip />

            {/* Ingestion runs log table */}
            <IngestionHistoryTable />
          </div>
        </div>
      </div>
    </div>
  );
}
