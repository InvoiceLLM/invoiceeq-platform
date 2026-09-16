"use client";

import { useEffect, useState } from "react";
import { ChevronDown, History, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/apiClient";

/** One saved change, as `GET /audit-history/{invoice_id}` returns it. */
export interface ChangeHistoryEntry {
  id: string;
  timestamp: string;
  action: string;
  actor_email: string | null;
  actor_name: string | null;
  actor_role: string;
  auth_method?: string | null;
  api_key_prefix?: string | null;
  previous_status?: string | null;
  target_status?: string | null;
  reject_reason?: string | null;
  corrections: Record<string, { old: unknown; new: unknown }>;
  dismissed_alerts: unknown[];
  raised_alerts: unknown[];
  notify_emails: string[];
}

const DECISION_LABELS: Record<string, string> = {
  PAID: "Approved",
  REJECTED: "Rejected",
  REVIEW_LATER: "Marked for review later",
  NEEDS_RESUBMISSION: "Asked for resubmission",
};

const ACTION_LABELS: Record<string, string> = {
  REOPEN_INVOICE: "Reopened",
  CONFIRM_SEND_OUTBOUND_INVOICE: "Confirmed send",
  MARK_PAID_OUTBOUND_INVOICE: "Marked paid",
};

function entryTitle(entry: ChangeHistoryEntry): string {
  if (entry.action === "RESOLVE_INVOICE" && entry.target_status) {
    return DECISION_LABELS[entry.target_status] ?? `Set to ${entry.target_status}`;
  }
  if (entry.action === "RESOLVE_INVOICE" || entry.action === "RESOLVE_OUTBOUND_INVOICE") {
    return Object.keys(entry.corrections).length > 0 ? "Corrected fields" : "Dismissed alerts";
  }
  return ACTION_LABELS[entry.action] ?? entry.action;
}

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "empty";
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "entry" : "entries"}`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function alertText(alert: unknown): string {
  if (typeof alert === "string") return alert;
  if (alert && typeof alert === "object") {
    const { message, type } = alert as { message?: string; type?: string };
    return message || type || JSON.stringify(alert);
  }
  return String(alert);
}

/**
 * Admin-only "Change history" for one invoice: every saved decision and correction, newest first —
 * who made it, when, and what changed. Collapsed by default and loaded on first open; `refreshKey`
 * is bumped by the page after each successful save so an open panel shows the new entry.
 * Refused ("Not saved") attempts write nothing and so never appear.
 */
export default function ChangeHistoryPanel({ invoiceId, refreshKey }: { invoiceId: string; refreshKey: number }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<ChangeHistoryEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient
      .get<{ entries: ChangeHistoryEntry[] }>(`/audit-history/${invoiceId}`)
      .then((res) => {
        if (!cancelled) setEntries(res.data?.entries ?? []);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the change history. Please try again.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, invoiceId, refreshKey]);

  return (
    <div data-testid="change-history-panel" className="flex flex-col rounded-xl border border-[#222D3D] bg-[#0B1220]">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="flex items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
          <History size={12} />
          Change history
          <span className="font-normal normal-case tracking-normal text-slate-600">(Admin)</span>
        </span>
        <ChevronDown size={14} className={`text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="flex flex-col gap-2 border-t border-[#222D3D] p-3">
          {loading && (
            <p className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 size={12} className="animate-spin" /> Loading…
            </p>
          )}
          {!loading && error && <p className="text-xs text-red-300">{error}</p>}
          {!loading && !error && entries?.length === 0 && (
            <p className="text-xs italic text-slate-600">No saved changes yet.</p>
          )}
          {!loading &&
            !error &&
            entries?.map((entry) => (
              <div key={entry.id} className="flex flex-col gap-1 rounded-md border border-[#222D3D] bg-[#0F172A] p-2 text-xs">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                  <span className="font-semibold text-slate-200">{entryTitle(entry)}</span>
                  <time dateTime={entry.timestamp} className="text-[11px] tabular-nums text-slate-500">
                    {new Date(entry.timestamp).toLocaleString()}
                  </time>
                </div>
                <p className="break-words text-[11px] text-slate-400">
                  by {entry.actor_name ? `${entry.actor_name} (${entry.actor_email ?? "no email"})` : entry.actor_email ?? "unknown user"}
                  {" · "}
                  {entry.actor_role}
                  {entry.auth_method === "api_key" ? ` · API key ${entry.api_key_prefix ?? ""}` : ""}
                </p>
                {entry.previous_status && entry.target_status && (
                  <p className="text-slate-300">
                    Status: {entry.previous_status} → {entry.target_status}
                  </p>
                )}
                {Object.entries(entry.corrections).map(([field, change]) => (
                  <p key={field} className="break-words text-slate-300" title={JSON.stringify(change)}>
                    <span className="text-slate-500">{field.replace(/_/g, " ")}:</span>{" "}
                    <span className="text-slate-500 line-through">{valueText(change?.old)}</span> →{" "}
                    <span className="text-slate-100">{valueText(change?.new)}</span>
                  </p>
                ))}
                {entry.reject_reason && <p className="text-slate-300">Reason: {entry.reject_reason}</p>}
                {entry.dismissed_alerts.length > 0 && (
                  <p className="break-words text-slate-400">Dismissed: {entry.dismissed_alerts.map(alertText).join("; ")}</p>
                )}
                {entry.raised_alerts.length > 0 && (
                  <p className="break-words text-amber-300">
                    Alert raised by this correction: {entry.raised_alerts.map(alertText).join("; ")}
                  </p>
                )}
                {entry.notify_emails.length > 0 && (
                  <p className="break-words text-slate-400">Notified: {entry.notify_emails.join(", ")}</p>
                )}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
