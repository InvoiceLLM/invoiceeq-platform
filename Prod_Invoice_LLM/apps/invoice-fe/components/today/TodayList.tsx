"use client";

// =============================================================================
// FILE: components/today/TodayList.tsx
// FEATURE: FE Feature 22 Task 22.4 — the Today sections, from `todaySections()`
//          (lib/today.ts; founder ruling 2026-09-16, Option B).
//
// Renders exactly what the server sent, in the order it sent it. No sort, no
// filter, no arithmetic — a section the server left empty is simply absent.
// Each line kind has its own component (22.5): cash -> PositionLine, input
// request -> InputRequestLine, everything else -> TodayLine.
// =============================================================================

import React from "react";
import ActionLine from "@/components/today/ActionLine";
import ConventionLine from "@/components/today/ConventionLine";
import InputRequestLine from "@/components/today/InputRequestLine";
import PositionLine from "@/components/today/PositionLine";
import ScenarioControl from "@/components/today/ScenarioControl";
import TodayLine from "@/components/today/TodayLine";
import type { TodaySection } from "@/lib/today";

export default function TodayList({ sections }: { sections: TodaySection[] }) {
  return (
    <div className="flex flex-col gap-5">
      {sections.map((section) => (
        <section
          key={section.key}
          aria-labelledby={`today-${section.key}`}
          data-testid={`today-section-${section.key}`}
          className="overflow-hidden rounded-xl border border-[#1E293B] bg-[#0F172A]/60"
        >
          <h2
            id={`today-${section.key}`}
            className="border-b border-[#1E293B] px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400"
          >
            {section.title}
          </h2>
          <ul className="divide-y divide-[#1E293B]">
            {section.lines.map((line) =>
              line.kind === "position" ? (
                <PositionLine key={line.key} line={line} />
              ) : line.kind === "input_request" ? (
                <InputRequestLine key={line.key} line={line} />
              ) : line.kind === "proposal" ? (
                <ConventionLine key={line.key} line={line} />
              ) : line.kind === "action" ? (
                <ActionLine key={line.key} line={line} />
              ) : (
                <TodayLine key={line.key} line={line} />
              )
            )}
          </ul>
          {/* 22.20: what-if on the cash position, only where the server sent cash lines. */}
          {section.key === "cash" && <ScenarioControl />}
        </section>
      ))}
    </div>
  );
}
