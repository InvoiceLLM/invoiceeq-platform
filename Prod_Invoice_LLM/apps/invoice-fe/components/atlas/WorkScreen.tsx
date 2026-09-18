// =============================================================================
// FILE: components/atlas/WorkScreen.tsx
// FEATURE: FE Feature 23 task 3 (spec §3) — capability-filtered rendering and
//          the no-grants empty state. Reads `GET /api/atlas/lines` (BE §15.2).
//
// THE FE FILTERS NOTHING (spec §3). The server sends what this user may act on;
// this component renders what it receives, in the order it receives it. There
// is no capability check in this file and there must never be one: `visible_to()`
// DROPS a line the caller cannot act on (BE §2.1, "absent, not disabled"), and a
// second filter here would be a weaker copy of that rule which eventually
// disagrees with it.
//
// "NO TASKS ASSIGNED" IS A STATED POSITION, NOT AN EMPTY LIST (D3). It is shown
// when the server says `ungranted`, never inferred from `lines.length === 0` —
// an Auditor who is simply clear this morning must not be told they have no
// access.
//
// A DISMISSED LINE IS REMOVED BY THE SERVER, NOT BY THIS FILE (D49). The
// dismiss click posts, then re-reads. It does not splice the row out of local
// state: `routers/atlas.py` consults the dismissal store before it assembles
// the response, so the line is absent from the payload rather than flagged in
// it, and the re-read is what proves that at the only place it matters. A
// client-side splice would be a second copy of that rule and would mask the day
// the server stopped honouring it.
//
// NOTHING SUBSCRIBES, NOTHING POLLS (D36, D38). ATLAS speaks when the app is
// opened. There is no SSE stream for this screen, no badge count and no
// interval; one read on mount, and a Refresh the user chooses.
//
// NO BATCH CONTROL (D42). No checkbox, no multi-select, and no way to accept
// several lines on one click. Asserted grep-shaped by
// `tests/unit/atlas-no-client-arithmetic.test.ts`.
//
// NO ARITHMETIC (spec §2). Same rule as the line: nothing here computes.
// =============================================================================

"use client";

import { useCallback, useEffect, useState } from "react";

import AtlasLine from "@/components/atlas/AtlasLine";
import ReconPanel from "@/components/atlas/ReconPanel";
import {
  ATTACH_ACTION_KINDS,
  dismissAtlasLine,
  fetchAtlasLines,
  type AtlasLinesResponse,
  type AtlasRecommendation,
} from "@/lib/atlas";

/** D3's exact sentence, per spec §3. */
export const NO_TASKS_ASSIGNED = "No tasks assigned. Ask your admin for access.";

/** The other empty case, which must never be confused with the one above. */
const NOTHING_NEEDS_YOU = "Nothing needs you right now.";

export default function WorkScreen() {
  const [payload, setPayload] = useState<AtlasLinesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [attachFor, setAttachFor] = useState<AtlasRecommendation | null>(null);
  const [dismissingId, setDismissingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await fetchAtlasLines());
    } catch (err: any) {
      // Shown, never swallowed: a work screen that renders empty because a read
      // failed looks exactly like a clear queue, which is the one lie this
      // screen must not tell.
      setError(
        err?.response?.data?.detail ??
          "Your work could not be loaded. Nothing here is up to date."
      );
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** D49. Post, then re-read; never hide the row locally. */
  const onDismiss = useCallback(
    async (line: AtlasRecommendation) => {
      setDismissingId(line.id);
      try {
        await dismissAtlasLine(line.id);
        await load();
      } catch (err: any) {
        // Said out loud. A dismiss that silently failed would leave the user
        // believing the line is gone until the next open brings it back, which
        // is precisely the experience D49 exists to end.
        setError(
          err?.response?.data?.detail ??
            "That line could not be dismissed, so it is still here."
        );
      } finally {
        setDismissingId(null);
      }
    },
    [load]
  );

  const showRecon =
    payload?.lines.some((line) => ATTACH_ACTION_KINDS.has(line.action.kind)) ?? false;

  return (
    <div data-testid="work-screen" className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-[15px] font-medium text-slate-100">Your work</h1>
        <button
          type="button"
          data-testid="work-screen-refresh"
          onClick={() => void load()}
          className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800"
        >
          Refresh
        </button>
        {payload?.capabilities.length ? (
          <span data-testid="work-screen-capabilities" className="text-[11px] text-slate-500">
            {payload.capabilities.join(", ")}
          </span>
        ) : null}
      </div>

      {loading && (
        <p data-testid="work-screen-loading" className="text-[13px] text-slate-400">
          Working out what needs you…
        </p>
      )}

      {error && (
        <p data-testid="work-screen-error" className="text-[13px] text-amber-300">
          {error}
        </p>
      )}

      {payload?.ungranted && (
        <p data-testid="work-screen-ungranted" className="text-[13px] text-slate-300">
          {NO_TASKS_ASSIGNED}
        </p>
      )}

      {payload && !payload.ungranted && payload.lines.length === 0 && (
        <p data-testid="work-screen-clear" className="text-[13px] text-slate-300">
          {NOTHING_NEEDS_YOU}
        </p>
      )}

      {payload && payload.lines.length > 0 && (
        <ul data-testid="work-screen-lines" className="space-y-2">
          {payload.lines.map((line) => (
            <AtlasLine
              key={line.id}
              line={line}
              onAttach={setAttachFor}
              onDismiss={onDismiss}
              dismissing={dismissingId === line.id}
            />
          ))}
        </ul>
      )}

      {/* §13.5's cost, said out loud: a screen missing checks says so rather
          than looking complete. */}
      {payload && payload.doubt_checks_skipped > 0 && (
        <p data-testid="work-screen-skipped" className="text-[11px] text-slate-500">
          Invoices I did not get to this time: {payload.doubt_checks_skipped}
        </p>
      )}

      {showRecon && <ReconPanel openedBy={attachFor} />}
    </div>
  );
}
