// =============================================================================
// FILE: components/chat/CitationPill.tsx
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: When the backend query agent takes the RAG execution path, the
//   response includes a `citations[]` array — each entry identifies the exact
//   invoice and page number that was retrieved from ChromaDB to build the
//   assistant answer.  This component renders each citation as a compact
//   clickable pill so users can immediately verify the source material.
//   Clicking navigates to /invoices/review/{invoice_id}?page=... so the full
//   PDF viewer can open on the correct page (rather than opening a modal here,
//   which would block the chat flow). NOTE: /audit?invoice_id=...&page=... was
//   the original target here, but no /audit route has ever existed in this app
//   (the review page has always lived at /invoices/review/[id]) -- fixed
//   2026-07-27 alongside Gap 53/FE 26, which found the same dead link pattern
//   in RecentInvoicesTable.tsx and StatusTable.tsx.
//   Styling matches the exact spec in feature_5_chat.md:
//     bg-[#1E293B] border border-[#222D3D] text-slate-300 hover:text-white
//     cursor-pointer px-3 py-1 rounded-full text-xs
// =============================================================================

"use client";

import { useRouter } from "next/navigation";
import type { Citation } from "@/types/chat";

interface CitationPillProps {
  citation: Citation;
}

export default function CitationPill({ citation }: CitationPillProps) {
  const router = useRouter();

  // WHY router.push instead of <Link>: We need to build a URL from dynamic
  //   props (invoice_id, page) at runtime, not at render time.
  //   router.push is cleaner here than constructing an href string in JSX.
  const handleClick = () => {
    if (!citation.invoice_id) return;
    const pageParam = citation.page != null ? `?page=${citation.page}` : "";
    router.push(`/invoices/review/${citation.invoice_id}${pageParam}`);
  };

  return (
    <button
      onClick={handleClick}
      // Tooltip shows full context for screen readers and on hover
      title={`Open ${citation.vendor_name} invoice — page ${citation.page}`}
      className="
        inline-flex items-center gap-1.5
        bg-[#1E293B] border border-[#222D3D]
        text-slate-300 hover:text-white
        cursor-pointer px-3 py-1 rounded-full text-xs
        transition-all duration-150 hover:border-blue-700/60 hover:bg-[#1e2d45]
        focus:outline-none focus:ring-1 focus:ring-blue-600
      "
    >
      {/* Blue dot — visual indicator that this is a verified source reference */}
      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />

      {/* Vendor name — truncated to 140px to prevent long names breaking the layout */}
      <span className="font-medium truncate max-w-[140px]">
        {citation.vendor_name}
      </span>

      {/* Separator */}
      <span className="text-slate-500">·</span>

      {/* Page reference — shrink-0 ensures it never gets truncated */}
      <span className="text-slate-400 shrink-0">p.{citation.page}</span>
    </button>
  );
}
