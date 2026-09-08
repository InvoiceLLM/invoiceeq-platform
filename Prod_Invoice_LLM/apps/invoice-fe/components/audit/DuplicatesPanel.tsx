"use client";

/**
 * Gap 497 Phase 2: review an invoice against every other copy of it.
 *
 * WHY THIS EXISTS. The system has always detected duplicates two different
 * ways and shown the result of neither. An auditor looking at a flagged
 * invoice could not see what it duplicated, let alone compare them -- the
 * link existed only in the database (Layer 1) or inside an alert sentence
 * (Layer 2, until Phase 1 gave it a column).
 *
 * THE DESIGN POINT: the two match types are different risks and get
 * different treatment.
 *
 *   EXACT_FILE            the identical file was uploaded twice. There is
 *                         nothing to compare -- same bytes, copied fields.
 *                         The only question is which copy to keep, so this
 *                         renders as a one-line row.
 *
 *   SAME_NUMBER_AND_VENDOR  the same invoice number and vendor arrived as a
 *                         DIFFERENT file. That is a re-issue, a correction,
 *                         or double billing -- and the amounts may differ.
 *                         This is the case that earns a real comparison, so
 *                         it renders the field-by-field diff.
 *
 * Rendering both the same way is what made this feel unusable before.
 */

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Copy, AlertTriangle, FileWarning, Loader2, ExternalLink, Trash2, Crown } from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";

export type DuplicateMatchType = "EXACT_FILE" | "SAME_NUMBER_AND_VENDOR" | "BOTH";

export interface DuplicateMember {
  invoice_id: string;
  match_type: DuplicateMatchType;
  status: string;
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_date: string | null;
  grand_total: number | null;
  currency: string | null;
  submitted_by_email: string | null;
  created_at: string;
  is_original: boolean;
}

export interface DuplicateCluster {
  invoice_id: string;
  cluster_size: number;
  members: DuplicateMember[];
  differing_fields: string[];
  has_amount_difference: boolean;
}

/** The invoice currently open, so each duplicate can be diffed against it. */
export interface DuplicateSubject {
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_date: string | null;
  grand_total: number | null;
  currency: string | null;
}

const MATCH_LABEL: Record<DuplicateMatchType, string> = {
  EXACT_FILE: "Identical file",
  SAME_NUMBER_AND_VENDOR: "Same number & vendor",
  BOTH: "Identical file + same number",
};

const FIELD_LABEL: Record<string, string> = {
  invoice_number: "Invoice number",
  vendor_name: "Vendor",
  invoice_date: "Invoice date",
  grand_total: "Total",
  currency: "Currency",
};

/** Comparable fields, in the order a human reads them. */
const COMPARED_FIELDS = ["invoice_number", "vendor_name", "invoice_date", "grand_total", "currency"] as const;

function displayValue(
  field: string,
  source: DuplicateMember | DuplicateSubject
): string {
  const raw = (source as unknown as Record<string, unknown>)[field];
  if (raw === null || raw === undefined || raw === "") return "—";
  if (field === "grand_total") {
    return formatCurrency(Number(raw), (source as { currency?: string | null }).currency);
  }
  return String(raw);
}

export default function DuplicatesPanel({
  invoiceId,
  subject,
  onChanged,
}: {
  invoiceId: string;
  subject: DuplicateSubject;
  /** Called after a duplicate is deleted, so the parent can refresh. */
  onChanged?: () => void;
}) {
  const router = useRouter();
  const [cluster, setCluster] = useState<DuplicateCluster | null>(null);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!invoiceId) return;
    setLoading(true);
    apiClient
      .get<DuplicateCluster>(`/invoices/${invoiceId}/duplicates`)
      .then((res) => setCluster(res.data))
      // Best effort: a failure here must never block the review screen, which
      // works perfectly well without this panel.
      .catch(() => setCluster(null))
      .finally(() => setLoading(false));
  }, [invoiceId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = async (member: DuplicateMember) => {
    const label = member.invoice_number || member.invoice_id.slice(0, 8);
    if (
      !window.confirm(
        `Delete the copy ${label}?\n\nIt is removed from lists, totals and chat answers, and the AI forgets it. The original PDF is kept.`
      )
    )
      return;
    setDeletingId(member.invoice_id);
    setError(null);
    try {
      await apiClient.delete(`/invoices/${member.invoice_id}`);
      load();
      onChanged?.();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not delete that copy. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  // Nothing to say when this invoice has no other copies -- the panel is
  // deliberately absent rather than rendering an empty "no duplicates" box on
  // the overwhelming majority of invoices.
  if (loading) return null;
  if (!cluster || cluster.members.length === 0) return null;

  const amountDiffers = cluster.has_amount_difference;

  return (
    <div
      id="duplicates-panel"
      className={`rounded-xl border px-4 py-3 ${
        amountDiffers
          ? "border-red-600/40 bg-red-950/20"
          : "border-amber-600/40 bg-amber-950/15"
      }`}
    >
      <div className="flex items-start gap-3">
        {amountDiffers ? (
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-300" />
        ) : (
          <Copy size={16} className="mt-0.5 shrink-0 text-amber-300" />
        )}
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-semibold ${amountDiffers ? "text-red-200" : "text-amber-200"}`}>
            {cluster.cluster_size} copies of this invoice are in the system
          </p>
          {/* The loudest thing on the panel when it applies: same invoice,
              different money is the case that costs someone real money. */}
          {amountDiffers ? (
            <p className="mt-0.5 text-xs text-red-200">
              The totals do not match. Check this is a corrected re-issue and not a
              second bill for the same work before approving anything.
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-slate-400">
              Review them below and delete the copies you do not need.
            </p>
          )}
        </div>
      </div>

      {error && <p className="mt-2 text-[11px] text-red-300">{error}</p>}

      <div className="mt-3 space-y-2">
        {cluster.members.map((member) => {
          const isExactFile = member.match_type === "EXACT_FILE";
          // Only fields that actually differ from the invoice being reviewed.
          // Showing every field would bury the one that matters.
          const diffs = COMPARED_FIELDS.filter(
            (f) => displayValue(f, member) !== displayValue(f, subject)
          );

          return (
            <div
              key={member.invoice_id}
              className="rounded-lg border border-[#222D3D] bg-[#0F1724]/60 px-3 py-2.5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                    isExactFile
                      ? "border-slate-500/30 bg-slate-500/10 text-slate-300"
                      : "border-red-500/30 bg-red-500/10 text-red-300"
                  }`}
                >
                  <FileWarning className="h-3 w-3" />
                  {MATCH_LABEL[member.match_type]}
                </span>

                {member.is_original && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                    <Crown className="h-3 w-3" />
                    Original
                  </span>
                )}

                <span className="rounded-full border border-[#222D3D] px-2 py-0.5 text-[10px] font-semibold text-slate-400">
                  {member.status}
                </span>

                <span className="text-[11px] text-slate-500">
                  {new Date(member.created_at).toLocaleString()}
                  {member.submitted_by_email ? ` · ${member.submitted_by_email}` : ""}
                </span>

                <div className="ml-auto flex items-center gap-1.5">
                  <button
                    onClick={() => router.push(`/invoices/review/${member.invoice_id}`)}
                    className="flex items-center gap-1 rounded-lg border border-[#222D3D] px-2 py-1 text-[11px] font-semibold text-slate-300 transition hover:bg-[#1E293B]"
                  >
                    <ExternalLink size={12} />
                    Open
                  </button>
                  <button
                    onClick={() => handleDelete(member)}
                    disabled={deletingId === member.invoice_id}
                    className="flex items-center gap-1 rounded-lg border border-red-500/40 px-2 py-1 text-[11px] font-semibold text-red-300 transition hover:bg-red-600/20 disabled:opacity-40"
                  >
                    {deletingId === member.invoice_id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Trash2 size={12} />
                    )}
                    Delete
                  </button>
                </div>
              </div>

              {/* An identical file has nothing to diff -- saying so is more
                  useful than an empty comparison table. */}
              {isExactFile && diffs.length === 0 ? (
                <p className="mt-2 text-[11px] text-slate-500">
                  Byte-for-byte the same file — nothing differs.
                </p>
              ) : diffs.length === 0 ? (
                <p className="mt-2 text-[11px] text-slate-500">
                  A different file, but every compared field matches.
                </p>
              ) : (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[420px] text-left text-[11px]">
                    <thead>
                      <tr className="text-slate-500">
                        <th className="py-1 pr-3 font-medium">Field</th>
                        <th className="py-1 pr-3 font-medium">This invoice</th>
                        <th className="py-1 font-medium">This copy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diffs.map((field) => {
                        const isMoney = field === "grand_total";
                        return (
                          <tr key={field} className="border-t border-[#222D3D]/60">
                            <td className="py-1 pr-3 text-slate-400">{FIELD_LABEL[field] || field}</td>
                            <td className="py-1 pr-3 text-slate-200">{displayValue(field, subject)}</td>
                            <td className={`py-1 font-semibold ${isMoney ? "text-red-300" : "text-amber-300"}`}>
                              {displayValue(field, member)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
