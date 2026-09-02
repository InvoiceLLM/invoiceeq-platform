// =============================================================================
// FILE: components/chat/AttachmentMatchConfirm.tsx
// FEATURE: Feature 5 (chat) surface of BE Feature 26 Part 2 — task H10,
//          spec §P2.6.3 of apps/invoice-be/docs/feature_26_chat_attached_documents.md
//
// REASON ADDED: This renders the `attachment_confirmation` block, and it is the
//   UI half of decision D4 — **the gate the whole safety design rests on**. An
//   answer turn issued before confirmation returns this payload and never a
//   number, so until this card exists and a human ticks a box, the product has
//   deliberately said nothing financial about the attached document.
//
//   Shape verified against the live backend, not against the spec's summary:
//   `services/document_comparison.py::build_confirmation_payload()` emits
//   `kind` / `attachment_id` / `tier` / `candidates` / `requires_manual_entry` /
//   `message`, plus `truncated` on the populated branch only. Candidate rows
//   carry `party_name` (`vendor_name or customer_name`), NOT `vendor_name` as
//   §P2.8's sketch says — a quotation the tenant itself issued has a customer,
//   not a vendor.
//
// WIRING (task H12 supplies these — nothing renders this component yet; H11
// hangs it off MessageBubble when a turn carries `attachment_confirmation`):
//   `onConfirm(invoiceIds)`      → POST /api/v1/chat/attachments/{id}/confirm-matches
//                                  through the Next proxy route H12 adds.
//   `onManualEntry(number)`      → the zero-candidate path. NOT the confirm
//                                  endpoint: that endpoint takes invoice *ids*
//                                  and rejects anything the matcher did not
//                                  propose, so a typed invoice *number* has to
//                                  go back as the next chat message, which is
//                                  exactly what the backend's own copy asks for
//                                  ("Tell me the invoice number ... and I will
//                                  use that").
//   `error`                      → the endpoint's 400 detail, surfaced rather
//                                  than swallowed ("Only invoices offered as
//                                  candidates for this attachment can be
//                                  confirmed", chat_attachments.py L353).
// =============================================================================

"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Info } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";
import {
  attachmentTierLabel,
  attachmentTruncationNotice,
  candidatesArePreChecked,
  type AttachmentConfirmation,
} from "@/lib/chatAttachments";

export type { AttachmentConfirmation };

interface AttachmentMatchConfirmProps {
  confirmation: AttachmentConfirmation;
  onConfirm: (invoiceIds: string[]) => void | Promise<void>;
  onManualEntry?: (invoiceNumber: string) => void | Promise<void>;
  /** True while the confirm request is in flight. */
  isSubmitting?: boolean;
  /** The backend's rejection detail, shown inline. */
  error?: string | null;
  /** Set once this attachment's matches have been confirmed — the card locks. */
  isConfirmed?: boolean;
}

export default function AttachmentMatchConfirm({
  confirmation,
  onConfirm,
  onManualEntry,
  isSubmitting = false,
  error = null,
  isConfirmed = false,
}: AttachmentMatchConfirmProps) {
  const { tier, candidates, message, truncated, requires_manual_entry } = confirmation;

  // Tier 1 is an exact normalised PO-number join, so pre-checking it saves a
  // click on the confident case. Tier 2 (supplier + date window) and Tier 3
  // (similarity) are heuristics and start UNCHECKED on purpose: confirming a
  // guess has to be a deliberate act, not the default the user clicked past.
  const [selected, setSelected] = useState<string[]>(() =>
    candidatesArePreChecked(tier) ? candidates.map((c) => c.invoice_id) : []
  );
  const [manualNumber, setManualNumber] = useState("");

  // A second attachment in the same session produces a second payload; without
  // this the first document's ticks would carry over onto the second's list.
  useEffect(() => {
    setSelected(candidatesArePreChecked(tier) ? candidates.map((c) => c.invoice_id) : []);
    setManualNumber("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirmation.attachment_id]);

  const toggle = (invoiceId: string) => {
    setSelected((prev) =>
      prev.includes(invoiceId)
        ? prev.filter((id) => id !== invoiceId)
        : [...prev, invoiceId]
    );
  };

  const truncationNotice = attachmentTruncationNotice(candidates.length, truncated);
  const hasCandidates = candidates.length > 0;

  return (
    <div
      id="chat-attachment-match-confirm"
      data-tier={tier}
      className="mt-2 w-full rounded-xl border border-[#222D3D] bg-[#0B1220] p-3 text-xs"
    >
      {/* Tier label — a similarity guess must never render identically to an
          exact PO-number join. Colour is secondary to the words. */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span
          data-testid="attachment-tier-label"
          className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
            tier === 1
              ? "bg-emerald-900/20 border-emerald-800/40 text-emerald-300"
              : "bg-amber-900/20 border-amber-800/40 text-amber-300"
          }`}
        >
          {attachmentTierLabel(tier)}
        </span>
        {isConfirmed && (
          <span className="flex items-center gap-1 text-[10px] text-emerald-400">
            <CheckCircle2 className="w-3 h-3" />
            Confirmed
          </span>
        )}
      </div>

      {/* The backend's own message, verbatim — it already names the document
          type and explains how the set was found. */}
      <p className="text-slate-300 leading-relaxed">{message}</p>

      {truncationNotice && (
        <p
          data-testid="attachment-truncation-notice"
          className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-300/90"
        >
          <Info className="w-3.5 h-3.5 shrink-0 mt-px" />
          {truncationNotice}
        </p>
      )}

      {hasCandidates && (
        <div className="mt-2.5 divide-y divide-[#222D3D]/60 rounded-lg border border-[#222D3D] overflow-hidden">
          {candidates.map((candidate) => {
            const checked = selected.includes(candidate.invoice_id);
            return (
              <label
                key={candidate.invoice_id}
                className={`flex items-center gap-2.5 px-2.5 py-2 cursor-pointer transition-colors ${
                  checked ? "bg-blue-950/25" : "hover:bg-[#1E293B]/40"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={isConfirmed || isSubmitting}
                  onChange={() => toggle(candidate.invoice_id)}
                  className="shrink-0 accent-blue-500 w-3.5 h-3.5"
                />
                <div className="flex-1 min-w-0 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="font-medium text-slate-200 truncate max-w-[140px]">
                    {candidate.invoice_number || "(no number)"}
                  </span>
                  {candidate.party_name && (
                    <span className="text-slate-400 truncate max-w-[160px]">
                      {candidate.party_name}
                    </span>
                  )}
                  {candidate.invoice_date && (
                    <span className="text-slate-500">{formatDate(candidate.invoice_date)}</span>
                  )}
                  {candidate.grand_total != null && (
                    <span className="font-mono text-slate-200">
                      {formatCurrency(candidate.grand_total, candidate.currency)}
                    </span>
                  )}
                  {candidate.status && (
                    <span className="text-[10px] font-mono uppercase tracking-wide text-slate-500">
                      {candidate.status}
                    </span>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      )}

      {/* Zero candidates: say so plainly and offer manual entry. Never a guess,
          never a widened search — Part 1's flow step 5. */}
      {(!hasCandidates || requires_manual_entry) && (
        <div className="mt-2.5 flex items-center gap-2">
          <input
            id="chat-attachment-manual-invoice"
            type="text"
            value={manualNumber}
            onChange={(e) => setManualNumber(e.target.value)}
            placeholder="Invoice number to compare against…"
            disabled={isSubmitting || isConfirmed}
            className="flex-1 bg-[#0F172A] border border-[#222D3D] text-slate-200 placeholder:text-slate-500 px-2.5 py-1.5 rounded-lg outline-none focus:border-blue-500/50 disabled:opacity-50"
          />
          <button
            type="button"
            id="chat-attachment-manual-submit"
            disabled={!manualNumber.trim() || isSubmitting || isConfirmed || !onManualEntry}
            onClick={() => onManualEntry?.(manualNumber.trim())}
            className="shrink-0 px-3 py-1.5 rounded-lg bg-[#1E293B] border border-[#222D3D] text-slate-200 hover:border-blue-700/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Use this
          </button>
        </div>
      )}

      {hasCandidates && (
        <div className="mt-2.5 flex items-center justify-between gap-2">
          <span className="text-[11px] text-slate-500">
            {selected.length} of {candidates.length} selected
          </span>
          <button
            type="button"
            id="chat-attachment-confirm-btn"
            disabled={selected.length === 0 || isSubmitting || isConfirmed}
            onClick={() => onConfirm(selected)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium disabled:bg-[#1E293B] disabled:text-slate-500 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {isConfirmed ? "Confirmed" : "Confirm and compare"}
          </button>
        </div>
      )}

      {/* The 400 is shown, not swallowed — including the manual-entry case,
          where the id was never a candidate. */}
      {error && (
        <p
          data-testid="attachment-confirm-error"
          className="mt-2 text-[11px] text-rose-300 bg-rose-950/25 border border-rose-800/40 rounded-lg px-2.5 py-1.5"
        >
          {error}
        </p>
      )}
    </div>
  );
}
