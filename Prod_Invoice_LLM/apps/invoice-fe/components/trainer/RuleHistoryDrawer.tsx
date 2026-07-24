"use client";

import React, { useState } from "react";
import { History, X, RotateCcw, CheckCircle2, User, Clock, ShieldCheck } from "lucide-react";
import { RuleVersion, TrainerScope } from "@/lib/trainer-service";

/**
 * Feature 6 Component: RuleHistoryDrawer (Task 6.7)
 * 
 * FOR MANAGERS & DEVELOPERS:
 * This slide-over drawer lists historical committed rule template versions for auditability.
 * It addresses Gap 29 in be_features_tracker.md ("No rule versioning/rollback"):
 * 
 *   - Captures each version with version #, scope, changed_by, timestamp, and rules list.
 *   - Highlights the currently active template version with a green badge.
 *   - Allows single-click "Rollback" action to promote a past version back to active status.
 * 
 * Target Endpoint: POST /trainer/templates/{id}/rollback/{version} (Task 10.10)
 */

interface RuleHistoryDrawerProps {
  /** Controls drawer visibility */
  isOpen: boolean;
  /** Callback fired to dismiss drawer */
  onClose: () => void;
  /** Array of historical rule template versions */
  history: RuleVersion[];
  /** Active rule scope */
  scope: TrainerScope;
  /** Name of the active vendor (if Scope 2 or 3) */
  vendorName?: string;
  /** Callback fired when user confirms a version rollback */
  onRollback: (version: RuleVersion) => void;
  /** Loading state flag */
  isLoading?: boolean;
}

export default function RuleHistoryDrawer({
  isOpen,
  onClose,
  history,
  scope,
  vendorName,
  onRollback,
  isLoading = false,
}: RuleHistoryDrawerProps) {
  // State tracking version selected for rollback confirmation
  const [selectedRollbackVersion, setSelectedRollbackVersion] = useState<RuleVersion | null>(null);

  if (!isOpen) return null;

  const handleConfirmRollback = () => {
    if (selectedRollbackVersion) {
      onRollback(selectedRollbackVersion);
      setSelectedRollbackVersion(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md bg-[#151B26] border-l border-[#222D3D] shadow-2xl flex flex-col">
          {/* Drawer Header */}
          <div className="px-6 py-4 bg-[#0F172A] border-b border-[#222D3D] flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <History className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Rule Version History & Rollback</h3>
                <p className="text-[11px] text-slate-400 font-mono">
                  {scope === "global" ? "Global Scope Rules" : `Vendor: ${vendorName || "Active"}`}
                </p>
              </div>
            </div>

            <button
              onClick={onClose}
              className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-[#1E293B] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Drawer Body - Version Timeline */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {isLoading ? (
              <div className="py-12 text-center text-xs text-slate-400 flex flex-col items-center gap-2">
                <span className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <span>Loading version history...</span>
              </div>
            ) : history.length === 0 ? (
              <div className="py-12 text-center text-xs text-slate-400 border border-dashed border-[#222D3D] rounded-xl p-4">
                No past rule versions recorded yet.
              </div>
            ) : (
              history.map((item) => (
                <div
                  key={item.id}
                  className={`p-4 rounded-xl border transition-all space-y-3 ${
                    item.isCurrent
                      ? "bg-[#1E293B]/90 border-blue-500/40 shadow-lg"
                      : "bg-[#0F172A]/80 border-[#222D3D]"
                  }`}
                >
                  {/* Version Header Card */}
                  <div className="flex items-center justify-between border-b border-[#222D3D] pb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-xs text-white bg-[#151B26] px-2 py-0.5 rounded border border-[#222D3D]">
                        v{item.version}
                      </span>
                      {item.isCurrent && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Active Current Version</span>
                        </span>
                      )}
                    </div>

                    {/* Single-Click Rollback Action Trigger */}
                    {!item.isCurrent && (
                      <button
                        type="button"
                        onClick={() => setSelectedRollbackVersion(item)}
                        className="text-xs bg-[#1E293B] hover:bg-[#283548] text-slate-300 hover:text-white px-2.5 py-1 rounded-lg border border-[#222D3D] transition-all flex items-center gap-1.5 cursor-pointer"
                      >
                        <RotateCcw className="w-3.5 h-3.5 text-blue-400" />
                        <span>Rollback</span>
                      </button>
                    )}
                  </div>

                  {/* Version Metadata (Changed By & Changed At) */}
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                    <div className="flex items-center gap-1.5">
                      <User className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      <span className="truncate">{item.changedBy}</span>
                    </div>
                    <div className="flex items-center gap-1.5 justify-end">
                      <Clock className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      <span>{item.changedAt}</span>
                    </div>
                  </div>

                  {/* Rules Content in Version */}
                  <div className="space-y-1 pt-1">
                    <span className="text-[10px] uppercase font-mono text-slate-400 font-semibold block">
                      Rules in v{item.version}:
                    </span>
                    <ul className="space-y-1 text-xs text-slate-300 font-mono bg-[#0B0F19] p-2.5 rounded-lg border border-[#222D3D]">
                      {item.rules.map((r, idx) => (
                        <li key={idx} className="flex items-start gap-1.5">
                          <span className="text-blue-400">•</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Rollback Confirmation Bar */}
          {selectedRollbackVersion && (
            <div className="p-4 bg-[#0F172A] border-t border-[#222D3D] space-y-3 animate-in slide-in-from-bottom duration-200">
              <div className="flex items-center gap-2 text-xs font-semibold text-amber-400">
                <ShieldCheck className="w-4 h-4" />
                <span>Confirm Rollback to Version {selectedRollbackVersion.version}?</span>
              </div>
              <p className="text-xs text-slate-400">
                This will promote rule set v{selectedRollbackVersion.version} as the active current version and queue a re-audit.
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedRollbackVersion(null)}
                  className="px-3 py-1.5 text-xs text-slate-400 hover:text-white cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmRollback}
                  className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium shadow cursor-pointer"
                >
                  Confirm Rollback
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
