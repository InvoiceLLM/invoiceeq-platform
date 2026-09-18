// =============================================================================
// FILE: components/atlas/ActionLog.tsx
// FEATURE: FE Feature 23 — BE Feature 34 task 34.7c (§5.3). FE Gap 701.
//
// §5.3 IS A BOUNDARY, NOT A FEATURE: "never writes silently: every write is
// visible, attributed and timestamped — what ATLAS did is a real list." The list
// has existed on the backend since Slice C and could be reached only with
// `curl`. A list only a developer can query is not visible in the sense that
// sentence means, so the boundary was not actually held until this file existed.
//
// REFUSALS ARE ROWS, NOT ERRORS. `succeeded: false` is written before the caller
// is answered — the 409 a suggest-only kind gets (carrying D50's reasoning in
// full), a 403 on a grant the caller does not hold, the underlying endpoint's own
// 422. They are shown here beside the successes, and they are the rows most
// worth reading: a log holding only successes answers "did ATLAS touch this
// invoice?" with a confident no on exactly the occasions somebody is asking
// because something looks wrong.
//
// TENANT-WIDE, AND THE BACKEND DECIDES THAT (BE §2.2). A per-user list would
// hide one auditor's resolve from the Admin who is the superset and answerable
// for it. This component filters nothing and sorts nothing: the server sends
// newest first and this renders that order.
//
// THIS IS NOT THE AUDIT TRAIL. `AuditLog` is, and it is still written — a
// resolve from the work screen appears in `audit_logs` exactly as one from the
// audit queue does, because `resolve_audit_invoice` is called unchanged. What
// this answers is the narrower question: which of those came from an ATLAS line,
// and which line.
//
// NO ARITHMETIC (spec §2). No durations, no counts computed here, no relative
// times — `performed_at` is the server's string and is printed as sent.
// =============================================================================

"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { fetchAtlasActions, type AtlasActionLogEntry } from "@/lib/atlas";

/** The heading, in the sentence §5.3 uses for it. */
export const ACTION_LOG_TITLE = "What I did";

/** Shown when the list is genuinely empty, which is not the same as a failed read. */
export const ACTION_LOG_EMPTY = "I have not done anything in this workspace yet.";

/**
 * The two words a row is labelled with.
 *
 * "Refused" rather than "failed": most `succeeded: false` rows are ATLAS
 * declining on a ruling (D50), not something breaking, and calling a ruling a
 * failure would misdescribe the product's own boundaries to the person reading
 * them. The row's `summary` is the server's sentence and says which it was.
 */
export const OUTCOME_DID = "Did";
export const OUTCOME_REFUSED = "Refused";

export default function ActionLog() {
  const [entries, setEntries] = useState<AtlasActionLogEntry[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const payload = await fetchAtlasActions();
      // The functional form, deliberately: React treats a bare function passed
      // to a setter as an UPDATER, so `setEntries(x)` silently invokes `x` when
      // a malformed payload puts a function where a list should be. This says
      // "the new value is exactly this" and cannot be re-read as an instruction.
      setEntries(() => payload.entries);
    } catch (err: any) {
      // Said out loud, for the same reason the work screen says a failed read
      // out loud: an empty record and an unreadable record are different facts,
      // and this one is read precisely when somebody is checking whether
      // something happened.
      setError(
        err?.response?.data?.detail ??
          "I could not read back what I did, so this list is not a record of it."
      );
      setEntries(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section data-testid="atlas-action-log" className="space-y-2">
      <button
        type="button"
        data-testid="atlas-action-log-toggle"
        aria-expanded={open}
        onClick={() => {
          // Re-read on every open. The user opens this panel to check whether
          // something they just did is really recorded, and answering that from
          // a payload fetched before they did it is the exact failure this
          // surface exists to remove.
          setOpen((prev) => !prev);
          void load();
        }}
        className="flex w-full items-center gap-2 rounded border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-left text-[13px] text-slate-200 hover:bg-slate-800/60"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-500" />
        )}
        <span>{ACTION_LOG_TITLE}</span>
      </button>

      {open && (
        <div data-testid="atlas-action-log-body" className="space-y-2 pl-5">
          <button
            type="button"
            data-testid="atlas-action-log-refresh"
            onClick={() => void load()}
            className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800"
          >
            Refresh
          </button>

          {error && (
            <p data-testid="atlas-action-log-error" className="text-[12px] text-amber-300">
              {error}
            </p>
          )}

          {entries && entries.length === 0 && (
            <p data-testid="atlas-action-log-empty" className="text-[12px] text-slate-400">
              {ACTION_LOG_EMPTY}
            </p>
          )}

          {entries && entries.length > 0 && (
            <ul data-testid="atlas-action-log-entries" className="space-y-1">
              {/* NEWEST FIRST, AS SENT. This app never re-sorts the server's
                  order — a second ordering is the one that eventually
                  disagrees, and ordering by a timestamp string here would be
                  this app reading a date the server already read. */}
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  data-testid="atlas-action-log-entry"
                  data-succeeded={entry.succeeded}
                  className={
                    entry.succeeded
                      ? "rounded border border-slate-700/60 bg-slate-900/40 px-2 py-1.5"
                      : "rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5"
                  }
                >
                  <p className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                    <span
                      data-testid="atlas-action-log-outcome"
                      className={entry.succeeded ? "text-emerald-300" : "text-amber-300"}
                    >
                      {entry.succeeded ? OUTCOME_DID : OUTCOME_REFUSED}
                    </span>
                    <span data-testid="atlas-action-log-kind" className="text-slate-300">
                      {entry.kind}
                    </span>
                    <span data-testid="atlas-action-log-target">{entry.target_id}</span>
                    {/* Attributed and timestamped — §5.3's own two words. */}
                    <span data-testid="atlas-action-log-user">{entry.user_id}</span>
                    <span data-testid="atlas-action-log-when">{entry.performed_at}</span>
                  </p>
                  {/* The server's sentence: the outcome, or the refusal in the
                      words the ruling is stated in. Printed as sent. */}
                  <p data-testid="atlas-action-log-summary" className="text-[12px] text-slate-200">
                    {entry.summary}
                  </p>
                  <p data-testid="atlas-action-log-line" className="text-[11px] text-slate-600">
                    {entry.recommendation_id}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
