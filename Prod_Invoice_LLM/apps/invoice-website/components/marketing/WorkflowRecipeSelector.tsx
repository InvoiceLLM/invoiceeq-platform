"use client";

import React, { useState } from "react";
import { Wand2 } from "lucide-react";
import { SandboxKeyCta } from "./SandboxKeyCta";

/**
 * Feature 7 / Gap 348 — "Choose Your Workflow" recipe selector.
 *
 * Four steps, each a set of options that update a live summary line, ending
 * in a CTA. The four steps and the summary sentence are pure fixture + local
 * state and make no network calls, unchanged from Gap 348 (feature_7 spec
 * section 7).
 *
 * Gap 350 narrowed that contract rather than breaking it: the CTA slot is now
 * `<SandboxKeyCta />`, which *does* call the backend — but only on an explicit
 * click, only through this app's own relay, and only from that one component.
 * Nothing in this file fetches anything.
 *
 * Deviation from the approved mockup, deliberate: the mockup had three steps
 * (Input Channel / Audit Level / Output Destination). Chat Access is added
 * as a fourth to match the final wizard definition, so what a visitor picks
 * here covers the same surface the real Feature 25 wizard will ask about.
 */

interface RecipeOption {
  id: string;
  label: string;
  /** Short form used in the summary sentence. */
  summaryLabel: string;
}

interface RecipeStep {
  key: string;
  title: string;
  options: RecipeOption[];
}

const RECIPE_STEPS: RecipeStep[] = [
  {
    key: "input",
    title: "Input Channel",
    options: [
      { id: "email", label: "Dedicated Email Address", summaryLabel: "email in" },
      { id: "drive", label: "Google Drive Folder", summaryLabel: "a watched Drive folder" },
      { id: "api", label: "Developer REST API", summaryLabel: "your REST API calls" },
    ],
  },
  {
    key: "audit",
    title: "Audit Level",
    options: [
      { id: "auto", label: "Full Auto-Pilot", summaryLabel: "auto-approved when clean" },
      { id: "flagged", label: "Review Flagged Only", summaryLabel: "sent to a human only when flagged" },
      { id: "strict", label: "Strict Human Review", summaryLabel: "reviewed by a human every time" },
    ],
  },
  {
    key: "output",
    title: "Output Destination",
    options: [
      { id: "webhook", label: "Real-time Webhook", summaryLabel: "pushed to your webhook" },
      { id: "email", label: "Emailed CSV / JSON", summaryLabel: "emailed out as CSV/JSON" },
      { id: "drive", label: "Google Drive Archive", summaryLabel: "archived back to Drive" },
    ],
  },
  {
    key: "chat",
    title: "Chat Access",
    options: [
      { id: "on", label: "SAGE Chat Enabled", summaryLabel: "with SAGE chat over the data" },
      { id: "off", label: "Pipeline Only", summaryLabel: "pipeline only, no chat" },
    ],
  },
];

/** First option of each step is the default, so the summary is never empty. */
const DEFAULT_SELECTION: Record<string, string> = RECIPE_STEPS.reduce(
  (acc, step) => ({ ...acc, [step.key]: step.options[0].id }),
  {} as Record<string, string>
);

export function WorkflowRecipeSelector() {
  const [selection, setSelection] = useState<Record<string, string>>(DEFAULT_SELECTION);

  const summaryFor = (stepKey: string) => {
    const step = RECIPE_STEPS.find((s) => s.key === stepKey);
    const option = step?.options.find((o) => o.id === selection[stepKey]);
    return option?.summaryLabel ?? "";
  };

  return (
    <section
      id="choose-your-workflow"
      className="py-16 relative z-10 border-t border-[rgba(255,255,255,0.08)]"
    >
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">

        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-[rgba(255,255,255,0.08)] bg-white/[0.04] backdrop-blur-md text-xs font-semibold text-[#22D3EE]">
            <Wand2 className="w-3.5 h-3.5" />
            <span>Choose Your Workflow</span>
          </div>
          <h2 className="mt-4 text-2xl sm:text-3xl font-bold text-white tracking-tight">
            Build the pipeline you actually want
          </h2>
          <p className="mt-2 text-sm text-[#94A3B8] max-w-xl mx-auto">
            Four choices. No integration project, no rip-and-replace of what you already run.
          </p>
        </div>

        <div className="rounded-2xl border border-[rgba(255,255,255,0.08)] bg-white/[0.02] backdrop-blur-md p-5 sm:p-7">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {RECIPE_STEPS.map((step, stepIdx) => (
              <fieldset key={step.key}>
                <legend className="text-[11px] font-bold uppercase tracking-wider text-[#64748B] mb-2.5">
                  {stepIdx + 1} · {step.title}
                </legend>
                <div className="space-y-2">
                  {step.options.map((option) => {
                    const selected = selection[step.key] === option.id;
                    return (
                      <button
                        key={option.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() =>
                          setSelection((prev) => ({ ...prev, [step.key]: option.id }))
                        }
                        className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-left text-xs transition-all duration-200 ${
                          selected
                            ? "bg-[#3B82F6]/10 border-[#3B82F6]/50 text-white"
                            : "bg-white/[0.03] border-[rgba(255,255,255,0.08)] text-[#94A3B8] hover:text-white hover:border-white/20"
                        }`}
                      >
                        <span
                          className={`w-3.5 h-3.5 rounded-full border shrink-0 flex items-center justify-center ${
                            selected ? "border-[#3B82F6]" : "border-[#64748B]"
                          }`}
                        >
                          {selected && <span className="w-1.5 h-1.5 rounded-full bg-[#3B82F6]" />}
                        </span>
                        <span>{option.label}</span>
                      </button>
                    );
                  })}
                </div>
              </fieldset>
            ))}
          </div>

          {/* Live summary line — recomputed from local state on every click */}
          <div className="mt-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl border border-[#10B981]/35 bg-[#10B981]/[0.08]">
            <p className="text-xs sm:text-[13px] leading-relaxed text-[#A7F3D0]">
              Your pipeline: invoices arrive via <b className="text-white">{summaryFor("input")}</b>,
              are <b className="text-white">{summaryFor("audit")}</b>, results are{" "}
              <b className="text-white">{summaryFor("output")}</b> —{" "}
              <b className="text-white">{summaryFor("chat")}</b>.
            </p>

            {/*
              Gap 350: this slot held a bare `<Link href="/signup">Start Free
              Trial</Link>` plus a comment saying "retarget once BE Gap 340
              ships". Gap 340 shipped (2026-08-30), so the retarget is done —
              but as a component rather than a swapped href, because issuing a
              key is a POST with four outcomes to render (issued / rate-limited
              / feature-disabled / unreachable), not a navigation.

              `SandboxKeyCta` still renders this exact link, unchanged, when
              `NEXT_PUBLIC_SANDBOX_KEYS_ENABLED` is not "true" — which is the
              default and the state of every environment today, because the
              backend's own `SANDBOX_KEYS_ENABLED` defaults to False. No dead
              button ships by default; that was the failure mode Gap 348's
              original comment was written to avoid.
            */}
            <SandboxKeyCta />
          </div>
        </div>

      </div>
    </section>
  );
}
