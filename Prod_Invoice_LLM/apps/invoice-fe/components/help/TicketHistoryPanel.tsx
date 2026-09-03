"use client";

/**
 * FE Gap 404: Help Center Ticket History & Status portal.
 *
 * Lists the signed-in tenant's own support tickets (GET /support/tickets,
 * already built and proxied — see the route note below). Read-only: this
 * panel shows status and metadata, it does not let a user edit or close a
 * ticket, and it does not show agent replies.
 *
 * Reply-thread scope note (deliberate, not an oversight): the backend's
 * GET /support/tickets response (`routers/support.py::list_support_tickets`)
 * returns only `ticket_number`, `subject`, `category`, `priority`, `status`,
 * `source`, and `created_at` — it does not include `admin_notes` or any
 * reply content, even though the `SupportTicket` model has an `admin_notes`
 * column. Surfacing "agent replies" would need a backend response-shape
 * change first (and a product decision on whether `admin_notes` — a single
 * freeform field, not a threaded list — is the right shape for that at all).
 * That is out of scope here; see be_features_tracker.md Gap 404 for the full
 * reasoning. This panel shows exactly what the API returns today.
 */

import React, { useEffect, useState, useCallback } from "react";
import { Ticket, RefreshCw, AlertCircle, Inbox } from "lucide-react";

interface TicketSummary {
  ticket_number: string;
  subject: string;
  category: string;
  priority: "LOW" | "NORMAL" | "URGENT" | string;
  status: "OPEN" | "IN_PROGRESS" | "RESOLVED" | "CLOSED" | string;
  source: "WEBSITE_CONTACT" | "HELP_CHATBOT" | "DIRECT_TICKET" | string;
  created_at: string | null;
}

const PRIORITY_COLOURS: Record<string, string> = {
  LOW: "#10B981",
  NORMAL: "#3B82F6",
  URGENT: "#EF4444",
};

const STATUS_STYLES: Record<string, string> = {
  OPEN: "bg-blue-500/10 border-blue-500/30 text-blue-300",
  IN_PROGRESS: "bg-amber-500/10 border-amber-500/30 text-amber-300",
  RESOLVED: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  CLOSED: "bg-slate-700/30 border-slate-600/40 text-slate-400",
};

const SOURCE_LABELS: Record<string, string> = {
  WEBSITE_CONTACT: "Website Contact Form",
  HELP_CHATBOT: "Raised from SAGE Chat",
  DIRECT_TICKET: "Direct Ticket",
};

function formatTicketDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function TicketHistoryPanel() {
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadTickets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // GET /api/support/ticket (singular — the route file's name, not a typo)
      // already has a GET handler proxying to backend GET /support/tickets;
      // no new proxy route was needed for this gap.
      const res = await fetch("/api/support/ticket", { method: "GET" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.detail || `Failed to load tickets (${res.status})`);
      }
      setTickets(Array.isArray(data?.tickets) ? data.tickets : []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong loading your tickets.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  return (
    <div id="ticket-history-panel" className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-white tracking-wide">Your Support Tickets</h3>
          <p className="text-[11px] text-slate-500">
            Tickets you've raised from this workspace, most recent first.
          </p>
        </div>
        <button
          type="button"
          onClick={loadTickets}
          disabled={loading}
          title="Refresh"
          aria-label="Refresh ticket list"
          className="flex items-center gap-1.5 rounded-lg border border-[#222D3D] px-3 py-1.5 text-[11px] font-medium text-slate-400 transition hover:bg-white/5 hover:text-white disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center justify-between gap-2.5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          <span className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </span>
          <button
            type="button"
            onClick={loadTickets}
            className="font-semibold underline underline-offset-2 hover:text-rose-100"
          >
            Try again
          </button>
        </div>
      )}

      {!error && loading && tickets === null && (
        <div className="space-y-2">
          {[...Array(3)].map((_, idx) => (
            <div key={idx} className="h-16 rounded-xl border border-[#222D3D] bg-[#151B26] animate-pulse" />
          ))}
        </div>
      )}

      {!error && tickets !== null && tickets.length === 0 && (
        <div
          id="ticket-history-empty-state"
          className="glass-panel rounded-xl border border-[#222D3D] p-10 text-center flex flex-col items-center gap-3"
        >
          <div className="p-3 rounded-full bg-slate-900/50 border border-[#222D3D] text-slate-500">
            <Inbox className="w-6 h-6" />
          </div>
          <p className="text-xs text-slate-400 max-w-xs">
            No tickets yet. Raise one from the AI Support Assistant tab, or use the
            <span className="text-slate-300 font-semibold"> Raise Ticket Directly </span>
            button in its chat header.
          </p>
        </div>
      )}

      {!error && tickets !== null && tickets.length > 0 && (
        <div className="space-y-2">
          {tickets.map((t) => {
            const priorityColour = PRIORITY_COLOURS[t.priority] || PRIORITY_COLOURS.NORMAL;
            const statusStyle = STATUS_STYLES[t.status] || STATUS_STYLES.CLOSED;
            return (
              <div
                key={t.ticket_number}
                className="glass-panel rounded-xl border border-[#222D3D] p-4 flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[11px] text-cyan-400 font-semibold">
                      {t.ticket_number}
                    </span>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${statusStyle}`}
                    >
                      {t.status.replace(/_/g, " ")}
                    </span>
                    <span
                      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border"
                      style={{
                        borderColor: `${priorityColour}50`,
                        background: `${priorityColour}1A`,
                        color: priorityColour,
                      }}
                    >
                      {t.priority}
                    </span>
                  </div>
                  <p className="text-sm text-slate-200 font-medium mt-1 truncate" title={t.subject}>
                    {t.subject}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {SOURCE_LABELS[t.source] || t.source} · {t.category.replace(/_/g, " ")} · {formatTicketDate(t.created_at)}
                  </p>
                </div>
                <div className="shrink-0 text-slate-600" title="Ticket detail view not built yet">
                  <Ticket className="w-4 h-4" />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
