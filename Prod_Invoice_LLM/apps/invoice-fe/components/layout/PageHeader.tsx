import React from "react";

interface PageHeaderProps {
  title: string;
  /** Emoji "cartoon" icon representing this page's agent, e.g. "🤖". */
  agentIcon?: string;
  /** Agent codename, e.g. "NOVA". */
  agentName?: string;
  /** Short role explanation shown after the agent name, e.g. "Extraction & Validation". */
  agentRole?: string;
  /** Optional right-aligned controls (filters, buttons) sharing this same row. */
  actions?: React.ReactNode;
}

/**
 * Single-line page header used across the app -- replaces every page's own
 * bespoke title+subtitle block. Deliberately has no subtitle line: every
 * page's explanatory sentence was redundant with what the page itself shows,
 * and stacking title/subtitle/filter-bar as three separate blocks was the
 * biggest source of "have to scroll to see the real content" complaints.
 */
export default function PageHeader({ title, agentIcon, agentName, agentRole, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 w-full">
      <div className="flex items-center gap-3 min-w-0 w-full sm:w-auto">
        <h1 className="text-lg sm:text-xl md:text-2xl font-bold text-white tracking-wide truncate">{title}</h1>
        {agentName && (
          <span className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-[#6366F1]/10 text-[#6366F1] border border-[#6366F1]/30 font-mono font-semibold tracking-wide whitespace-nowrap">
            {agentIcon && <span className="text-sm leading-none not-italic">{agentIcon}</span>}
            {agentName}
            {agentRole && (
              <span className="text-slate-400 font-normal font-sans normal-case tracking-normal ml-1">
                — {agentRole}
              </span>
            )}
          </span>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-3 flex-wrap justify-start sm:justify-end w-full sm:w-auto">
          {actions}
        </div>
      )}
    </div>
  );
}
