// =============================================================================
// FILE: components/atlas/ColdStart.tsx
// FEATURE: FE Feature 23 task 9 (spec §5) — cold-start orientation, per role.
//          BE Feature 34 task 34.12 (§7.1, D24, D25) owns every word rendered
//          here; this file composes none of it.
//
// THE TRAP THIS SCREEN EXISTS FOR: almost everything ATLAS does needs history,
// so its first month is its weakest — and that is the month a customer decides
// whether it was worth buying. §7.1's answer is that DAY ONE IS COMPREHENSION,
// NOT FINDINGS. So this is not an empty state dressed up, and it is not a demo.
//
// EVERY SENTENCE COMES FROM THE SERVER, INCLUDING THE PROMISE. Part 3 — "right
// now I do not know your vendors… in a month I will" — is a commitment about
// what the product will be able to do. It is a fixed table on the backend so it
// cannot vary per visit, and nothing here rewrites, shortens or re-orders it.
//
// NOT A TOUR, AND NOTHING TO DISMISS (D25: teach once, then keep teaching in
// place). There is no step counter, no "next", no "skip" and no completion flag
// anywhere in this file. It is shown while the server says `needed`, and it
// stops being shown when there is real work instead — which is the honest
// trigger, because "has this workspace seen an invoice" is the fact that decides
// whether the explanation is still true.
//
// NO ARITHMETIC, NO FIGURES (spec §2). There is not a number on this screen.
// =============================================================================

"use client";

import { useEffect, useState } from "react";

import { fetchAtlasOrientation, type AtlasOrientation } from "@/lib/atlas";

export default function ColdStart() {
  const [orientation, setOrientation] = useState<AtlasOrientation | null>(null);

  useEffect(() => {
    let live = true;
    void fetchAtlasOrientation()
      .then((data) => {
        if (live) setOrientation(data);
      })
      .catch(() => {
        // Silent, and deliberately so. This is an explanation, not work: a
        // failure to fetch it must not put an error banner above a queue that
        // loaded perfectly well. The work screen's own error line is for the
        // read that matters.
        if (live) setOrientation(null);
      });
    return () => {
      live = false;
    };
  }, []);

  if (!orientation?.needed) return null;

  return (
    <section
      data-testid="atlas-cold-start"
      className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-4 py-3"
    >
      <p className="text-[11px] uppercase tracking-wide text-slate-400">
        Nothing has arrived yet — so let me tell you how this works
      </p>

      <ul data-testid="atlas-cold-start-parts" className="mt-3 space-y-3">
        {orientation.parts.map((part) => (
          <li key={part.key} data-testid="atlas-cold-start-part" data-part={part.key}>
            <p className="text-[13px] font-medium text-slate-100">{part.title}</p>
            <p className="mt-0.5 text-[13px] text-slate-300">{part.body}</p>
          </li>
        ))}
      </ul>

      {/* "Comprehension, not findings" must not read as "nothing until next
          month". These are real checks that need no history at all. */}
      {orientation.day_one_finds.length > 0 && (
        <div className="mt-3">
          <p className="text-[12px] font-medium text-slate-200">
            What I can already catch, today
          </p>
          <ul data-testid="atlas-cold-start-day-one" className="mt-1 space-y-0.5">
            {orientation.day_one_finds.map((find) => (
              <li key={find} className="text-[12px] text-slate-400">
                · {find}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* AN OFFER, NEVER A GATE (§7.1). Rendered as a sentence and not as a
          button or a required step, because everything on this screen works
          without it — a first session held hostage to a file the customer may
          not have is the opposite of what this section is for. */}
      {orientation.historical_import_offer && (
        <p
          data-testid="atlas-cold-start-import-offer"
          className="mt-3 text-[12px] text-slate-400"
        >
          {orientation.historical_import_offer}
        </p>
      )}
    </section>
  );
}
