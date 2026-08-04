"use client";

import React from "react";
import { Globe, Building2, FilePlus, HelpCircle } from "lucide-react";
import { TrainerScope } from "@/lib/trainer-service";

/**
 * Feature 6 Component: ScopeSelector (Task 6.1)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This component renders the 3-way segmented control at the top of the AI Trainer page.
 * It enforces the redesigned multi-scope rule architecture (be_features/feature_10_trainer.md):
 *
 *   1. Global (Tenant-Wide): Teaches vendor-agnostic rules. PDF is optional grounding.
 *   2. Existing Vendor: Teaches rules for an existing production vendor (loads real invoice).
 *   3. New Vendor: Cold-starts rules for a brand-new vendor (requires PDF upload).
 *
 * Design: Premium glassmorphism pill segmented control with animated underline indicator,
 * colored icon glows per scope, and a contextual description tooltip strip.
 *
 * When a user clicks a tab, `onScopeChange(scope)` triggers page-level session re-initialization.
 */

interface ScopeSelectorProps {
  /** Currently active rule scope */
  activeScope: TrainerScope;
  /** Callback fired when the user selects a different rule scope tab */
  onScopeChange: (scope: TrainerScope) => void;
  /** Optional disabled flag during active network operations */
  disabled?: boolean;
}

export default function ScopeSelector({
  activeScope,
  onScopeChange,
  disabled = false,
}: ScopeSelectorProps) {
  // Definition of the 3 scopes with icon, label, description, and per-scope color tokens
  const scopes: {
    id: TrainerScope;
    label: string;
    description: string;
    icon: React.ElementType;
    badgeText: string;
    /* Tailwind classes for active glow ring and icon color */
    activeRing: string;
    activeIcon: string;
    activeBg: string;
    badgeCls: string;
  }[] = [
    {
      id: "global",
      label: "Global",
      description:
        "Tenant-wide, vendor-agnostic rules (e.g. VAT handling). Applies to every vendor automatically.",
      icon: Globe,
      badgeText: "Tenant-Wide",
      activeRing: "border-blue-500/60 shadow-blue-500/20",
      activeIcon: "text-blue-400",
      activeBg: "bg-blue-500/10",
      badgeCls: "bg-blue-500/10 text-blue-400 border-blue-500/25",
    },
    {
      id: "existing_vendor",
      label: "Existing Vendor",
      description:
        "Refine rules for a vendor with production history. Seeds from a real extracted invoice.",
      icon: Building2,
      badgeText: "Production Seed",
      activeRing: "border-emerald-500/60 shadow-emerald-500/20",
      activeIcon: "text-emerald-400",
      activeBg: "bg-emerald-500/10",
      badgeCls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
    },
    {
      id: "new_vendor",
      label: "New Vendor",
      description:
        "Cold-start rules for a brand new vendor. Upload a fresh sample PDF to begin.",
      icon: FilePlus,
      badgeText: "Cold-Start Upload",
      activeRing: "border-purple-500/60 shadow-purple-500/20",
      activeIcon: "text-purple-400",
      activeBg: "bg-purple-500/10",
      badgeCls: "bg-purple-500/10 text-purple-400 border-purple-500/25",
    },
  ];

  const activeScope_ = scopes.find((s) => s.id === activeScope);

  return (
    <div className="flex items-center gap-1 bg-[#111827]/60 p-1 border border-[#1E2D45] rounded-xl shadow-inner max-w-full overflow-x-auto no-scrollbar">
      {scopes.map((scope) => {
        const Icon = scope.icon;
        const isActive = activeScope === scope.id;

        return (
          <button
            key={scope.id}
            type="button"
            disabled={disabled}
            onClick={() => onScopeChange(scope.id)}
            className={`
              group flex items-center justify-center gap-2
              px-3.5 py-1.5 rounded-lg text-xs font-semibold
              transition-all duration-200 relative
              ${isActive
                ? `${scope.activeBg} text-white border ${scope.activeRing} shadow-md`
                : "text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent"
              }
              ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}
            `}
          >
            <Icon
              className={`w-3.5 h-3.5 transition-colors ${
                isActive ? scope.activeIcon : "text-slate-500 group-hover:text-slate-300"
              }`}
            />

            <span className="whitespace-nowrap">{scope.label}</span>

            {/* Gap 77: all three descriptor badges follow one rule -- same
                breakpoint, same shape, same per-scope colour token. Raised
                from `lg` to `xl` because Gap 77 moved these tabs into a shared
                bar with the grounding control: at lg they now compete with it
                for the row, and a badge is decoration where the vendor picker
                / Browse PDF button is function. */}
            <span
              className={`hidden xl:inline-block text-[9px] px-1.5 py-0.5 rounded border font-mono font-medium ${scope.badgeCls}`}
            >
              {scope.badgeText}
            </span>

            {isActive && (
              <span
                className={`absolute bottom-0 left-1/4 right-1/4 h-[1.5px] rounded-full ${
                  scope.id === "global"
                    ? "bg-blue-400"
                    : scope.id === "existing_vendor"
                    ? "bg-emerald-400"
                    : "bg-purple-400"
                }`}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
