// =============================================================================
// FILE: components/chat/AttachmentChip.tsx
// FEATURE: Feature 5 (chat) surface of BE Feature 26 Part 2 — task H10,
//          spec §P2.6.2 of apps/invoice-be/docs/feature_26_chat_attached_documents.md
//
// REASON ADDED: An attached PO/quotation has to be visible *inside the composer*
//   while the user types the question it grounds — not in a separate panel they
//   can forget about — because the whole feature is "ask a question about THIS
//   document" and a question sent against a document the user thought they had
//   removed is a wrong answer with no visible cause.
//
//   Four explicit states, because three of them are real waits or real failures
//   and collapsing any of them would hide something the user needs:
//     uploading   — determinate progress; cancellable
//     extracting  — a genuine synchronous Document Intelligence round trip
//                   inside the upload request (`_extract_attachment`), NOT an
//                   instant success
//     ready       — the five fields `AttachmentOut` actually returns
//     failed      — upload-rejected vs extraction-failed, distinguishable
//
// WIRING (task H12 supplies these — nothing calls this component yet):
//   `state`      comes from useChatSession's `AttachmentState`, driven by an
//                XMLHttpRequest upload (fetch has no upload progress event).
//   `onCancel`   aborts that XHR while `status === "uploading"`.
//   `onRemove`   clears the attachment so the next turn is not silently
//                re-grounded on a stale document.
// =============================================================================

"use client";

import { FileText, Loader2, X, AlertTriangle } from "lucide-react";
import { formatCurrency } from "@/lib/utils";
import {
  attachmentFailureHeadline,
  docTypeBadgeLabel,
  truncateFilenameMiddle,
  EXTRACTION_FAILED_HINT,
  type AttachmentState,
} from "@/lib/chatAttachments";

export type { AttachmentState };

interface AttachmentChipProps {
  state: AttachmentState;
  /** Abort the in-flight upload. Only meaningful while uploading. */
  onCancel?: () => void;
  /** Detach — used from the ready and failed states. */
  onRemove?: () => void;
}

const SHELL =
  "flex items-center gap-2.5 w-full text-xs rounded-xl border px-3 py-2 transition-colors duration-150";

export default function AttachmentChip({
  state,
  onCancel,
  onRemove,
}: AttachmentChipProps) {
  const shortName = truncateFilenameMiddle(state.filename);

  // --- uploading -----------------------------------------------------------
  if (state.status === "uploading") {
    // Clamped rather than trusted: XHR's loaded/total can momentarily exceed
    // 100 with chunked transfer encoding, and a bar wider than its track looks
    // like a rendering bug rather than a fast upload.
    const pct = Math.max(0, Math.min(100, Math.round(state.progress)));
    return (
      <div
        id="chat-attachment-chip"
        data-attachment-status="uploading"
        className={`${SHELL} bg-[#0B1220] border-[#222D3D] text-slate-300`}
      >
        <FileText className="w-4 h-4 shrink-0 text-slate-500" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium text-slate-200" title={state.filename}>
              {shortName}
            </span>
            <span className="text-[10px] font-mono text-slate-500 shrink-0">{pct}%</span>
          </div>
          {/* Determinate bar — this is the one phase with real byte progress. */}
          <div className="mt-1.5 h-1 w-full rounded-full bg-[#1E293B] overflow-hidden">
            <div
              data-testid="chat-attachment-progress"
              className="h-full bg-blue-500 transition-[width] duration-150"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            title="Cancel upload"
            aria-label="Cancel upload"
            className="shrink-0 p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    );
  }

  // --- extracting ----------------------------------------------------------
  if (state.status === "extracting") {
    return (
      <div
        id="chat-attachment-chip"
        data-attachment-status="extracting"
        className={`${SHELL} bg-[#0B1220] border-[#222D3D] text-slate-300`}
      >
        <Loader2 className="w-4 h-4 shrink-0 text-blue-400 animate-spin" />
        <span className="truncate font-medium text-slate-200" title={state.filename}>
          {shortName}
        </span>
        {/* No progress bar and no cancel: extraction happens server-side inside
            the upload request, so there is nothing to measure and nothing this
            client can abort. Saying "Reading document…" is the honest render. */}
        <span className="text-slate-500 shrink-0">Reading document…</span>
      </div>
    );
  }

  // --- failed --------------------------------------------------------------
  if (state.status === "failed") {
    return (
      <div
        id="chat-attachment-chip"
        data-attachment-status="failed"
        data-attachment-failure={state.failure}
        className={`${SHELL} items-start bg-rose-950/20 border-rose-800/40 text-rose-200`}
      >
        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-rose-400" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-rose-200">
            {attachmentFailureHeadline(state.failure)}
          </p>
          {/* A row is rendered for BOTH failures. An extraction failure means
              the file IS stored server-side; rendering nothing would tell the
              user the opposite of what is true. */}
          <p className="truncate text-[11px] text-rose-300/80" title={state.filename}>
            {shortName}
          </p>
          <p className="text-[11px] text-rose-300/90 mt-0.5">{state.message}</p>
          {state.failure === "extraction_failed" && (
            <p className="text-[11px] text-rose-300/70 mt-0.5">{EXTRACTION_FAILED_HINT}</p>
          )}
        </div>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            title="Dismiss"
            aria-label="Dismiss attachment"
            className="shrink-0 p-1 rounded text-rose-300 hover:text-rose-100 hover:bg-rose-900/40 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    );
  }

  // --- ready ---------------------------------------------------------------
  const { attachment } = state;
  return (
    <div
      id="chat-attachment-chip"
      data-attachment-status="ready"
      className={`${SHELL} bg-[#0B1220] border-blue-800/40 text-slate-300`}
    >
      <FileText className="w-4 h-4 shrink-0 text-blue-400" />
      <div className="flex-1 min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1">
        {/* The type badge leads, for the same reason the retrieved-chunk header
            leads with it (E-2): it is what stops a *quoted* price being read as
            a *billed* one. */}
        <span className="text-[10px] font-mono font-semibold tracking-wider px-1.5 py-0.5 rounded bg-blue-900/30 border border-blue-800/40 text-blue-300">
          {docTypeBadgeLabel(attachment.doc_type)}
        </span>
        {attachment.doc_number && (
          <span className="font-medium text-slate-200 truncate max-w-[160px]">
            {attachment.doc_number}
          </span>
        )}
        {attachment.party_name && (
          <span className="text-slate-400 truncate max-w-[180px]">
            {attachment.party_name}
          </span>
        )}
        {attachment.grand_total != null && (
          <span className="font-mono text-slate-200">
            {formatCurrency(attachment.grand_total, attachment.currency)}
          </span>
        )}
        {/* Filename stays visible: doc_number/party_name can both be null on a
            document the extractor read only partially, and a chip with no
            identifying text at all would be unattributable. */}
        <span className="text-[11px] text-slate-500 truncate" title={attachment.filename}>
          {truncateFilenameMiddle(attachment.filename, 24)}
        </span>
      </div>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          title="Remove attachment"
          aria-label="Remove attachment"
          className="shrink-0 p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
