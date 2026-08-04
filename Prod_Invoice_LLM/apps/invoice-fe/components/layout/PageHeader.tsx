import React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { PageHeaderMeta } from "./PageHeaderContext";

/**
 * The title cluster of the app's single shared header row.
 *
 * FE Gap 110: this used to be a full-width block each page rendered for itself
 * (title + agent badge + an `actions` slot). It is now rendered exactly once,
 * by `Header.tsx`, from whatever the active route declared through
 * `usePageHeader()`. The `actions` slot is gone -- page controls now portal
 * into the header via `<PageHeaderActions>` instead of being passed down as a
 * prop through a component the page no longer renders.
 *
 * Still deliberately compact (Gap 68/85): the title sits on one line, and the
 * optional subtitle is a single small line under it, so the whole cluster fits
 * the header's 64px row and no screen spends body space on a title.
 *
 * Widths are the constraint here, not height -- the header also carries the
 * page's own actions plus the notification/profile block, and it starts 256px
 * in from the left edge because of the sidebar. So the decorative parts drop
 * out first as the row tightens: the agent role text below 1536px, the whole
 * codename badge below 1280px, the subtitle below 640px. The title itself
 * truncates rather than pushing anything off the row.
 */
export default function PageHeader({
  title,
  agentIcon,
  agentName,
  agentRole,
  subtitle,
  backHref,
}: PageHeaderMeta) {
  return (
    <div className="flex items-center gap-3 min-w-0">
      {backHref && (
        <Link
          href={backHref}
          aria-label="Back"
          className="shrink-0 w-8 h-8 rounded-lg bg-[#1E293B]/60 border border-[#222D3D] flex items-center justify-center text-slate-400 hover:text-white hover:border-slate-500 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>
      )}

      <div className="min-w-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <h1 className="text-base sm:text-lg font-semibold text-white tracking-wide truncate">
            {title}
          </h1>
          {agentName && (
            <span className="hidden xl:flex items-center gap-1.5 shrink-0 text-[10px] px-2 py-0.5 rounded-full bg-[#6366F1]/10 text-[#6366F1] border border-[#6366F1]/30 font-mono font-semibold tracking-wide whitespace-nowrap">
              {agentIcon && <span className="text-xs leading-none not-italic">{agentIcon}</span>}
              {agentName}
              {agentRole && (
                <span className="hidden 2xl:inline text-slate-400 font-normal font-sans normal-case tracking-normal ml-1">
                  — {agentRole}
                </span>
              )}
            </span>
          )}
        </div>
        {subtitle && (
          <p className="hidden sm:block text-[11px] text-slate-400 truncate leading-tight">
            {subtitle}
          </p>
        )}
      </div>
    </div>
  );
}
