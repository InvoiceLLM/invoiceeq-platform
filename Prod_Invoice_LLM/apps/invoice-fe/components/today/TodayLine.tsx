"use client";

// =============================================================================
// FILE: components/today/TodayLine.tsx
// FEATURE: FE Feature 22 Tasks 22.4 + 22.5 — one Today line: the server's
//          sentence, rendered as-is. No figure is computed here.
//
// 22.5: a line backed by a TodayItem (findings, summary) opens Ask. The click
// calls `POST /today/{id}/open` exactly once — the button is disabled while the
// call is in flight — then navigates with the returned session id and seeded
// question. A failed open renders on the line itself, with no navigation.
// Lines without an item id (proposals until 22.18) stay display-only.
// =============================================================================

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { askUrlForOpenedItem, openTodayItem, todayErrorOf, type TodayLineModel } from "@/lib/today";

export default function TodayLine({ line }: { line: TodayLineModel }) {
  const router = useRouter();
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const text = (
    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
      <p className="text-sm text-slate-100">{line.text}</p>
      {line.detail && <p className="text-xs text-slate-400">{line.detail}</p>}
      {error && (
        <p role="alert" className="text-xs text-rose-300">
          {error}
        </p>
      )}
    </span>
  );

  if (!line.itemId) {
    return (
      <li data-testid={`today-line-${line.kind}`} className="flex px-5 py-3.5">
        {text}
      </li>
    );
  }

  const itemId = line.itemId;
  const open = async () => {
    if (opening) return;
    setOpening(true);
    setError(null);
    try {
      const result = await openTodayItem(itemId);
      router.push(askUrlForOpenedItem(result));
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not open this in Ask. Try again.");
      setOpening(false);
    }
  };

  return (
    <li data-testid={`today-line-${line.kind}`}>
      <button
        type="button"
        onClick={open}
        disabled={opening}
        aria-busy={opening}
        className="group flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-[#1E293B]/50 focus-visible:bg-[#1E293B]/50 focus-visible:outline-none disabled:cursor-wait"
      >
        {text}
        <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 text-xs font-medium text-[#3B82F6] group-hover:text-blue-300">
          {opening ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
          Ask <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
      </button>
    </li>
  );
}
