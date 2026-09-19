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
//
// A LINE APPEARS EXACTLY ONCE (2026-09-18, found by loading real data). An area
// owns the lines it stands for; everything else is a plain line below. See
// `looseLines` in the body for why that rule lives on this side of the seam and
// could not have been fixed on the other. It is asserted by counting rendered
// rows, not by inspecting props — `tests/unit/atlas-work-screen.test.tsx`.
// =============================================================================

"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import ActionLog from "@/components/atlas/ActionLog";
import AtlasLine from "@/components/atlas/AtlasLine";
import ColdStart from "@/components/atlas/ColdStart";
import MemoryPanel from "@/components/atlas/MemoryPanel";
import ReconPanel from "@/components/atlas/ReconPanel";
import {
  actOnAtlasLine,
  ATTACH_ACTION_KINDS,
  dismissAtlasLine,
  fetchActionKinds,
  fetchAtlasLines,
  PERFORMABLE_ACTION_KINDS,
  type AtlasLinesResponse,
  type AtlasRecommendation,
} from "@/lib/atlas";

/** D3's exact sentence, per spec §3. */
export const NO_TASKS_ASSIGNED = "No tasks assigned. Ask your admin for access.";

/** The other empty case, which must never be confused with the one above. */
const NOTHING_NEEDS_YOU = "Nothing needs you right now.";

/**
 * D30's escape hatch, in words: **ATLAS ranks; it does not hide.**
 *
 * Everything below the cut is already in the payload — this button reveals it,
 * it does not fetch it. If it fetched, the promise would depend on a request
 * that can fail, and "reachable" would quietly mean "reachable when the network
 * is up".
 */
const SHOW_EVERYTHING = "Show everything";

export default function WorkScreen() {
  const [payload, setPayload] = useState<AtlasLinesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [attachFor, setAttachFor] = useState<AtlasRecommendation | null>(null);
  const [dismissingId, setDismissingId] = useState<string | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [openAreas, setOpenAreas] = useState<ReadonlySet<string>>(new Set());
  /**
   * What the BACKEND says it can perform (BE 34.7d). Starts empty, which
   * renders every action disabled — "I do not know yet" and "I can" must not
   * look the same, and the safe one is the one that does nothing.
   */
  const [performableKinds, setPerformableKinds] =
    useState<ReadonlySet<string>>(PERFORMABLE_ACTION_KINDS);

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

  /**
   * Read once per mount, separately from the lines.
   *
   * **A failure here is silent on the screen and loud in the buttons.** If the
   * backend cannot say what it can perform, every action stays disabled and the
   * line's own "I cannot do it for you yet" is already the honest sentence.
   * Adding a second error banner for it would push the actual work down the
   * page to report a degradation the user can already see.
   */
  useEffect(() => {
    let live = true;
    void fetchActionKinds()
      .then((kinds) => {
        if (live) setPerformableKinds(new Set(kinds.performable));
      })
      .catch(() => {
        if (live) setPerformableKinds(PERFORMABLE_ACTION_KINDS);
      });
    return () => {
      live = false;
    };
  }, []);

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

  /**
   * BE 34.7 — perform the line's action, then **re-read**.
   *
   * The same rule as the dismiss click: this component does not decide what
   * happens to the row. D38 recomputes every line on open, so whether a resolved
   * invoice still has a line is the server's answer. Splicing it out here would
   * be this app holding an opinion about a record it did not write, and would
   * mask the day the backend stopped agreeing.
   */
  const onAct = useCallback(
    async (line: AtlasRecommendation) => {
      setActingId(line.id);
      setOutcome(null);
      setError(null);
      try {
        const result = await actOnAtlasLine(line);
        // The server's sentence, printed as sent. This app composes no outcome
        // text: the numbers in it are the backend's, like every other figure.
        setOutcome(result.summary);
        await load();
      } catch (err: any) {
        setError(
          err?.response?.data?.detail ??
            "That did not go through, so nothing has changed."
        );
      } finally {
        setActingId(null);
      }
    },
    [load]
  );

  const showRecon =
    payload?.lines.some((line) => ATTACH_ACTION_KINDS.has(line.action.kind)) ?? false;

  /**
   * EVERY LINE APPEARS EXACTLY ONCE — the seam §1 exists to close.
   *
   * Found by loading real data (2026-09-18): all nine lines rendered twice,
   * once inside their collapsed area and once in the list below it. **Neither
   * side was wrong on its own.** The backend is right to keep collapsed lines in
   * `lines`: collapse groups, it never removes (BE 34 §2.2, D20/D41), and that
   * is precisely what makes an area openable in place with no second request.
   * This component then rendered both lists independently, because each was
   * written against the field it read rather than against the screen.
   *
   * So the ownership rule is stated here, once: **an area owns the lines it
   * stands for.** Everything else is a plain line. It cannot be stated on the
   * backend without making `areas` a truncation of `lines`, which would cost the
   * openable-in-place property the whole design rests on.
   *
   * The ranking is untouched — `lines` keeps the server's order and this filters
   * it; it never re-sorts (BE §7.3, D30).
   */
  const claimedByAnArea = new Set(
    (payload?.areas ?? []).flatMap((area) => area.line_ids)
  );
  const looseLines = (payload?.lines ?? []).filter(
    (line) => !claimedByAnArea.has(line.id)
  );
  /**
   * The cut applies to what is actually in this list. `rank_cut` is a count of
   * rows above the fold, and applying the server's number to a list the areas
   * have taken rows out of would hide lines that were never below any cut.
   */
  const aboveTheCut = showAll ? looseLines : looseLines.slice(0, payload?.rank_cut ?? 0);

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

      {/* COLD START (BE §7.1, D24/D25 · task 34.12). It renders itself away
          once the workspace has history, so there is no condition here and no
          flag for this component to own. Placed above the work rather than
          below it: on day one it IS the content. */}
      <ColdStart />

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

      {/* The outcome of the last action, in the server's own words. Kept
          separate from the error line: "Invoice approved." and "that did not go
          through" are different facts and a user who sees one must not have to
          work out which they got. */}
      {outcome && (
        <p data-testid="work-screen-outcome" className="text-[13px] text-emerald-300">
          {outcome}
        </p>
      )}

      {/* COLLAPSED AREAS (BE §2.2, D20 · task 34.7g). Admin only, and the
          backend decides that — this renders what it was sent.

          The rows stand for lines that are STILL IN `payload.lines`, so opening
          one is an expansion of what this component already holds. There is no
          second request, and there is no state in which a row's contents are
          unavailable: that is what "coverage is total; volume is not" means in
          a client. */}
      {payload && payload.areas.length > 0 && (
        <ul data-testid="work-screen-areas" className="space-y-1">
          {payload.areas.map((area) => {
            const open = openAreas.has(area.capability);
            const inArea = new Set(area.line_ids);
            return (
              <li key={area.capability} data-testid="work-screen-area" data-area={area.capability}>
                <button
                  type="button"
                  data-testid="work-screen-area-toggle"
                  aria-expanded={open}
                  onClick={() =>
                    setOpenAreas((prev) => {
                      const next = new Set(prev);
                      if (next.has(area.capability)) next.delete(area.capability);
                      else next.add(area.capability);
                      return next;
                    })
                  }
                  className="flex w-full items-center gap-2 rounded border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-left text-[13px] text-slate-200 hover:bg-slate-800/60"
                >
                  {open ? (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                  )}
                  {/* The server's sentence, printed as sent — every count in it
                      is the backend's, like every figure on a line. */}
                  <span data-testid="work-screen-area-headline">{area.headline}</span>
                  <span className="text-[11px] text-slate-500">{area.reason}</span>
                </button>
                {open && (
                  <ul data-testid="work-screen-area-lines" className="mt-1 space-y-2 pl-5">
                    {payload.lines
                      .filter((line) => inArea.has(line.id))
                      .map((line) => (
                        <AtlasLine
                          key={line.id}
                          line={line}
                          onAttach={setAttachFor}
                          onDismiss={onDismiss}
                          dismissing={dismissingId === line.id}
                          onAct={onAct}
                          acting={actingId === line.id}
                          performableKinds={performableKinds}
                        />
                      ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {payload && looseLines.length > 0 && (
        <>
          <ul data-testid="work-screen-lines" className="space-y-2">
            {/* RANKED BY THE SERVER (BE §7.3, D30) AND NEVER RE-SORTED HERE.
                `rank_cut` decides how many are above the fold; `showAll` reveals
                the rest, which are already in this payload. ATLAS ranks; it does
                not hide, and the proof of that is that nothing below the cut
                needs another request.

                These are the lines NO AREA STANDS FOR. A line inside a collapsed
                area is rendered by that area, once, and is reachable by opening
                it — see `looseLines` above on why that rule lives here. */}
            {aboveTheCut.map(
              (line) => (
                <AtlasLine
                  key={line.id}
                  line={line}
                  onAttach={setAttachFor}
                  onDismiss={onDismiss}
                  dismissing={dismissingId === line.id}
                  onAct={onAct}
                  acting={actingId === line.id}
                  performableKinds={performableKinds}
                />
              )
            )}
          </ul>
          {looseLines.length > (payload.rank_cut ?? 0) && (
            <button
              type="button"
              data-testid="work-screen-show-everything"
              onClick={() => setShowAll((prev) => !prev)}
              className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800"
            >
              {showAll ? "Show less" : SHOW_EVERYTHING}
            </button>
          )}
        </>
      )}

      {/* §13.5's cost, said out loud: a screen missing checks says so rather
          than looking complete. */}
      {payload && payload.doubt_checks_skipped > 0 && (
        <p data-testid="work-screen-skipped" className="text-[11px] text-slate-500">
          Invoices I did not get to this time: {payload.doubt_checks_skipped}
        </p>
      )}

      {showRecon && <ReconPanel openedBy={attachFor} />}

      {/* WHAT I REMEMBER (BE §7.2, D31/D40/D12 · task 34.10) and WHAT I DID
          (BE §5.3 · task 34.7c). FE Gaps 700 and 701.

          Both are collapsed by default and sit BELOW the work, deliberately:
          they are how a user checks ATLAS rather than work ATLAS is asking for,
          and putting either above the queue would push the actual work down the
          page to show a record of the last time there was some.

          Neither is capability-gated here, and neither should be. The memory is
          what the workspace believes, and the action log is a record of writes,
          not a work queue — the backend answers both tenant-wide, and a second
          filter on this side would be a weaker copy of a rule it did not make
          (the same reasoning this file's header gives for `visible_to()`).

          They render unconditionally rather than on `payload`: a failed lines
          read must not also take away the user's ability to find and delete a
          wrong lesson. §7.2's whole argument is that a wrong lesson which
          cannot be found haunts the system forever. */}
      <MemoryPanel />
      <ActionLog />
    </div>
  );
}
