// =============================================================================
// FILE: components/atlas/MissedThis.tsx
// FEATURE: FE Feature 23 — BE Feature 34 task 34.14 (§5.2 Q13, D34).
//
// THE ONLY FALSE-NEGATIVE DETECTOR THERE IS. §5.2's asymmetry: a false positive
// is cheap, visible and self-correcting; a false negative is real money and
// INVISIBLE — no feedback, no correction, no signal. Q13 asked how one is ever
// detected and D34 ruled that the user reports it. There is no automatic
// detector and there is not going to be one.
//
// UNDER-REPORTING IS ACCEPTED, EXPLICITLY (BE §13.4). So this control is built
// to be cheap to use rather than to be complete: one line of text, no category
// picker, no severity, no required fields beyond the sentence. Every field added
// here is a reason somebody does not bother, and a report nobody files is the
// failure mode this is already fighting.
//
// THE SENTENCE IS SENT EXACTLY AS TYPED. It is the evidence ATLAS was wrong and
// it becomes a memory rule the workspace can read (BE §7.2). Nothing here trims
// it, capitalises it or offers a template.
//
// ON ANY RECORD, WHICH IS WHAT D34 ACTUALLY SAYS (FE Gap 703, 2026-09-18).
// This shipped on ATLAS lines only, which is the one surface where it is least
// useful: a line is a thing ATLAS already noticed. A miss is noticed on a record
// ATLAS said nothing about. It is now mounted on:
//   - `app/invoices/review/[id]/page.tsx`   entity_kind "invoice"
//   - `app/trainer/page.tsx`                "invoice", or "trainer_session" for
//                                           a transient upload with no Invoice row
//   - `components/ingestion/IngestionHistoryTable.tsx` — the product's documents
//     list since `app/documents/page.tsx` was folded into History (FE Gap 464);
//     `entity_kind` is the row's own `file.kind`, passed through unchanged
// plus `components/atlas/AtlasLine.tsx`, where it started.
//
// NOT CAPABILITY-GATED ON ANY OF THEM, matching the backend (BE §17.7): a miss
// is noticed by whoever happens to be looking, and gating it would suppress
// exactly the evidence §5.2 says is scarcest.
// =============================================================================

"use client";

import { useState } from "react";
import { Flag } from "lucide-react";

import { reportMissed } from "@/lib/atlas";

export interface MissedThisProps {
  entityKind: string;
  entityId: string;
}

export default function MissedThis({ entityKind, entityId }: MissedThisProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (done) {
    // The acknowledgement §5.2 asks for after being wrong: plain, and then stop.
    // "Not an apology, an adjustment."
    return (
      <p data-testid="atlas-missed-done" className="mt-1 text-[11px] text-slate-400">
        Noted, in your words. You can read it, change it or delete it in what I remember.
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        data-testid="atlas-missed-open"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-300"
      >
        <Flag className="h-3 w-3" />
        You missed something here
      </button>
    );
  }

  return (
    <div className="mt-1 space-y-1">
      <textarea
        data-testid="atlas-missed-text"
        value={text}
        onChange={(event) => setText(event.target.value)}
        rows={2}
        placeholder="What should I have caught?"
        className="w-full rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-[12px] text-slate-200"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="atlas-missed-send"
          disabled={sending || !text.trim()}
          onClick={async () => {
            setSending(true);
            setError(null);
            try {
              await reportMissed({ entityKind, entityId, description: text });
              setDone(true);
            } catch (err: any) {
              setError(
                err?.response?.data?.detail ??
                  "That did not reach me, so I have not recorded it."
              );
            } finally {
              setSending(false);
            }
          }}
          className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {sending ? "Sending…" : "Tell me"}
        </button>
        <button
          type="button"
          data-testid="atlas-missed-cancel"
          onClick={() => setOpen(false)}
          className="text-[11px] text-slate-500 hover:text-slate-300"
        >
          Never mind
        </button>
      </div>
      {error && (
        <p data-testid="atlas-missed-error" className="text-[11px] text-amber-300">
          {error}
        </p>
      )}
    </div>
  );
}
