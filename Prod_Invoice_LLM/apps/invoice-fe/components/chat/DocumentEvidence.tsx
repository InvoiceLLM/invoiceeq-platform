// =============================================================================
// FILE: components/chat/DocumentEvidence.tsx
// FEATURE: Feature 5 (chat) surface of BE Feature 26 Part 2 — task H11,
//          spec §P2.6.4 of apps/invoice-be/docs/feature_26_chat_attached_documents.md
//
// REASON ADDED: The content branch answers from the attached document's own
//   text, and §P2.8's contract rule is that `evidence` must be non-empty
//   whenever the answer makes any claim about the document. That evidence has
//   to be visible, or the rule buys nothing: the user cannot check a quote they
//   were never shown.
//
// WHY THIS IS NOT CitationPill.tsx — the important part, and the reason the
// spec insists on a distinct component rather than reusing the pill:
//   CitationPill navigates. It does `router.push("/invoices/review/{invoice_id}
//   ?page=N")`, because an invoice citation points at a real `Invoice` row with
//   a stored PDF and a review page. An attachment span has NONE of that. A
//   ChatAttachment is deliberately not an `Invoice` (D2), there is no audit or
//   review record for it, and `citations` is returned EMPTY on this route for
//   exactly that reason (query_agent.py L3516). Rendering these as pills that
//   look clickable would offer a destination that does not exist.
//   So: same visual family (dark chip, page reference, blue accent), zero
//   navigation. The only interaction is expand/collapse, and it stays inside
//   the chat thread.
//
// The distance is not shown. It is a cosine distance from the vector search,
// and dressing it up as a percentage confidence would be inventing a precision
// nobody measured — H3 deliberately applies no relevance threshold on this
// path, so a larger distance means "this is what was closest", not "this is
// probably wrong".
// =============================================================================

"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import {
  evidencePageLabel,
  evidencePreview,
  type AttachmentEvidenceSpan,
} from "@/lib/chatAttachments";

interface DocumentEvidenceProps {
  spans: AttachmentEvidenceSpan[];
  /** Shown in the header when known, so the quotes are attributable. */
  filename?: string | null;
}

function EvidenceSpanBlock({ span, index }: { span: AttachmentEvidenceSpan; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const text = (span.text ?? "").trim();
  const hasMore = text.length > evidencePreview(text).length;

  return (
    <div
      data-testid="document-evidence-span"
      data-page={span.page ?? ""}
      className="rounded-lg border border-[#222D3D] bg-[#0B1220] overflow-hidden"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        data-testid={`document-evidence-toggle-${index}`}
        className="w-full flex items-start gap-2 px-2.5 py-2 text-left hover:bg-[#1E293B]/40 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-600"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 shrink-0 mt-0.5 text-slate-500" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 shrink-0 mt-0.5 text-slate-500" />
        )}
        <span className="shrink-0 text-[10px] font-mono text-blue-300 bg-blue-950/30 border border-blue-900/40 rounded px-1.5 py-0.5">
          {evidencePageLabel(span)}
        </span>
        {!expanded && (
          <span className="flex-1 min-w-0 text-[11px] text-slate-400 italic truncate">
            {evidencePreview(text)}
          </span>
        )}
      </button>

      {expanded && (
        // A quote block, not prose: this is transcribed content of a file the
        // user uploaded, and it must read as something the document says rather
        // than as something SAGE said.
        <blockquote
          data-testid="document-evidence-text"
          className="border-l-2 border-blue-700/40 ml-6 mr-2.5 mb-2.5 pl-2.5 text-[11px] leading-relaxed text-slate-300 whitespace-pre-wrap break-words"
        >
          {text || "(no text)"}
        </blockquote>
      )}

      {/* `hasMore` is only used to keep the affordance honest — a span short
          enough to be shown whole still expands, it just does not promise
          anything extra. */}
      {!expanded && !hasMore && <span className="sr-only">Full quote already shown</span>}
    </div>
  );
}

export default function DocumentEvidence({ spans, filename }: DocumentEvidenceProps) {
  if (!spans || spans.length === 0) return null;

  return (
    <div id="chat-document-evidence" className="mt-2 w-full space-y-1.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 px-0.5">
        <FileText className="w-3 h-3" />
        <span data-testid="document-evidence-header">
          From the attached document
          {filename ? ` (${filename})` : ""} — {spans.length}{" "}
          {spans.length === 1 ? "passage" : "passages"}
        </span>
      </div>
      {spans.map((span, idx) => (
        // Page number alone is not a safe key: two chunks from the same page
        // are possible and a null page is possible, so the index carries it.
        <EvidenceSpanBlock key={`${span.page ?? "x"}-${idx}`} span={span} index={idx} />
      ))}
    </div>
  );
}
