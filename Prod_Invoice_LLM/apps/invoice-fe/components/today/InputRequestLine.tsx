"use client";

// =============================================================================
// FILE: components/today/InputRequestLine.tsx
// FEATURE: FE Feature 22 Task 22.5 — "Attach your Rajesh contract → check every
//          invoice against agreed rates".
//
// The phrase and its unlock value are the backend's. Clicking goes straight to
// Ask with its attach control focused (`/ask?attach=1`, read by task 22.6).
// No `POST /today/{id}/open` here: an input request's id is an InputRequest row,
// not a TodayItem, and the open route would 404 on it.
// =============================================================================

import React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Paperclip } from "lucide-react";
import { ASK_ATTACH_URL, type TodayLineModel } from "@/lib/today";

export default function InputRequestLine({ line }: { line: TodayLineModel }) {
  const router = useRouter();

  return (
    <li data-testid="today-line-input_request">
      <button
        type="button"
        onClick={() => router.push(ASK_ATTACH_URL)}
        className="group flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-[#1E293B]/50 focus-visible:bg-[#1E293B]/50 focus-visible:outline-none"
      >
        <Paperclip className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" aria-hidden="true" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="text-sm text-slate-100">{line.text}</p>
          {line.detail && <p className="text-xs text-slate-400">{line.detail}</p>}
        </span>
        <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 text-xs font-medium text-sky-400 group-hover:text-sky-300">
          Attach <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
      </button>
    </li>
  );
}
