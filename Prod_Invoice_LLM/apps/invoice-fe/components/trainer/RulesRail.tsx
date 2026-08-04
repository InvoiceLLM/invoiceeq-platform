"use client";

import React from "react";
import { Sparkles, Tag, ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Feature 6 Component: RulesRail — FE Gap 111.
 *
 * The rule candidates trained in a session used to share the "Variables &
 * Rules" tab inside `QnAPanel`, so seeing them meant hiding the chat that
 * creates them. Gap 111's agreed layout gives them the far-right rail instead:
 * slim and count-badge-only by default, expanding on click.
 *
 * Collapsed by default on purpose. Until there is a real draft rule there is
 * nothing here worth spending horizontal space on, and the chat panel — which
 * is where the work happens — takes whatever this rail gives back. The badge
 * still shows the count, so a rule appearing is visible without expanding.
 */

interface RulesRailProps {
  activeRules: string[];
  isExpanded: boolean;
  onToggle: () => void;
  /**
   * Renders as a full-width always-open panel instead of a collapsible rail.
   *
   * The rail only makes sense as a fourth column, and below `xl` the workspace
   * stacks into a single scrolling column where there is no fourth column to
   * be. Without this the rules would simply be unreachable on a narrow screen
   * -- a real regression, since the "Variables & Rules" tab this replaced was
   * available at every width. Vertical space is not the scarce resource in the
   * stacked layout, so it is open, and there is nothing to collapse it into.
   */
  stacked?: boolean;
}

export default function RulesRail({
  activeRules,
  isExpanded,
  onToggle,
  stacked = false,
}: RulesRailProps) {
  const count = activeRules.length;

  // ── Collapsed: a 44px strip, count badge and a vertical label ──────────
  if (!isExpanded && !stacked) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={false}
        aria-label={`Expand rule candidates (${count})`}
        title={`Rule candidates (${count})`}
        className="h-full w-11 shrink-0 flex flex-col items-center gap-3 py-3 bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl shadow-2xl shadow-black/30 hover:border-emerald-500/40 transition-colors cursor-pointer group"
      >
        <ChevronLeft className="w-3.5 h-3.5 text-slate-500 group-hover:text-slate-300 transition-colors shrink-0" />

        <span
          className={`shrink-0 min-w-[22px] px-1.5 py-0.5 rounded-md font-mono text-[10px] font-semibold border ${
            count > 0
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/25"
              : "bg-[#111827] text-slate-500 border-[#1E2D45]"
          }`}
        >
          {count}
        </span>

        {/* Vertical label — the rail is 44px wide, so the text turns rather
            than truncating to nothing. */}
        <span
          className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 group-hover:text-slate-300 transition-colors select-none"
          style={{ writingMode: "vertical-rl" }}
        >
          Rules
        </span>
      </button>
    );
  }

  // ── Expanded: the full candidate list ──────────────────────────────────
  return (
    <div
      className={`h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30 ${
        stacked ? "w-full" : "w-56 shrink-0"
      }`}
    >
      <div className="px-3 py-2.5 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Sparkles className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          <h2 className="text-xs font-semibold text-white truncate">Rule Candidates</h2>
          <span className="shrink-0 px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 font-mono text-[10px] border border-emerald-500/25 font-semibold">
            {count}
          </span>
        </div>
        {!stacked && (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded
            aria-label="Collapse rule candidates"
            title="Collapse"
            className="p-1 rounded-lg text-slate-500 hover:text-white hover:bg-[#1E293B] transition-colors cursor-pointer shrink-0"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5">
        {count === 0 ? (
          <p className="text-[10px] text-slate-500 text-center leading-relaxed px-1 py-6">
            No rules trained in this session yet. Teach one in the chat panel and
            it appears here, ready to commit.
          </p>
        ) : (
          activeRules.map((rule, idx) => (
            <div
              key={idx}
              className="p-2 bg-[#0B1120]/80 border border-emerald-500/20 rounded-xl flex items-start gap-1.5 hover:border-emerald-500/40 transition-colors"
            >
              <Tag className="w-3 h-3 text-emerald-400 shrink-0 mt-0.5" />
              <span className="font-mono text-[10px] text-emerald-300 leading-relaxed break-words">
                {rule}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
