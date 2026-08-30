"use client";

import React, { useState } from "react";
import { Bot, Paperclip, Sparkles, Database } from "lucide-react";

/**
 * Feature 7 / Gap 347 — SAGE chat preview.
 *
 * SAGE is named twice on this page already (AITeamSection's agent card and
 * Hero's "SAGE Ready" chip) but never shown answering anything. This widget
 * shows one real-shaped question/answer pair per click.
 *
 * ZERO NETWORK CALLS — hard constraint, not a shortcut (feature_7 spec
 * section 7). `/` is public, unauthenticated and crawler-reachable; wiring a
 * real SAGE call in here would be an open, uncapped LLM endpoint spending
 * OpenAI quota on anonymous traffic and bots. Every answer, SQL snippet and
 * citation below is a module-level constant. If a future change wants live
 * answers here, that needs its own Gap entry and its own rate-limiting
 * story — it is not a refactor of this file.
 */

interface SagePreviewExchange {
  /** The chip label — also the question shown back in the answer header. */
  prompt: string;
  /** SAGE's natural-language answer. */
  answer: string;
  /** The SQL SAGE resolved the question to — this is what makes it credible. */
  sql: string;
  /** Invoice ids the answer is grounded in, rendered as citation pills. */
  citations: string[];
}

const SAGE_PREVIEW: SagePreviewExchange[] = [
  {
    prompt: "What did we spend on software last month?",
    answer:
      "$84,210.00 across 12 invoices — 6% above the month before. Two renewals (Azure Cloud Enterprise and a seat expansion on your BI tool) account for most of the increase.",
    sql: "SELECT SUM(total_amount)\n  FROM invoices\n WHERE category = 'software'\n   AND invoice_date >= date_trunc('month', now() - interval '1 month')\n   AND invoice_date <  date_trunc('month', now());",
    citations: ["SUB-7721", "INV-9842", "INV-9810"],
  },
  {
    prompt: "Which invoices are still held for review?",
    answer:
      "3 are open. One price variance (Global Freight Logistics, $18,750.50, flagged 34% over the vendor's own 90-day average) and two suspected duplicate charges from the same vendor, seven days apart.",
    sql: "SELECT invoice_number, vendor_name, total_amount, exception_type\n  FROM invoices\n WHERE routing = 'HOLD_FOR_REVIEW'\n   AND resolved_at IS NULL\n ORDER BY total_amount DESC;",
    citations: ["FRT-1048", "DUP-2201", "DUP-2202"],
  },
  {
    prompt: "How did Q2 vendor costs compare to Q1?",
    answer:
      "Q2 came in at $312,400 against $278,900 in Q1 — up 12%. Almost all of the delta sits with two logistics vendors you started using in April; every other vendor was flat or down.",
    sql: "SELECT vendor_name,\n       SUM(total_amount) FILTER (WHERE quarter = 'Q1') AS q1,\n       SUM(total_amount) FILTER (WHERE quarter = 'Q2') AS q2\n  FROM invoices\n GROUP BY vendor_name\n ORDER BY q2 - q1 DESC;",
    citations: ["FRT-1048", "FRT-1102"],
  },
];

export function SageChatPreview() {
  // null = nothing asked yet; the answer pane only exists after a click.
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const active = activeIndex === null ? null : SAGE_PREVIEW[activeIndex];

  return (
    <section
      id="sage-preview"
      className="py-16 relative z-10 border-t border-[rgba(255,255,255,0.08)]"
    >
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="rounded-2xl border border-[#8B5CF6]/30 bg-[#8B5CF6]/[0.05] backdrop-blur-md p-5 sm:p-7 shadow-[0_20px_50px_rgba(0,0,0,0.35)]">

          {/* Header */}
          <div className="flex items-center gap-3 pb-4 border-b border-[#8B5CF6]/20">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#8B5CF6] to-[#22D3EE] flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div>
              <div className="text-sm font-bold text-white">Ask SAGE</div>
              <p className="text-[11px] text-[#64748B]">
                Plain-English questions over your own invoice data — no SQL, no export.
              </p>
            </div>
            <span className="ml-auto hidden sm:inline-flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-lg bg-white/5 border border-[rgba(255,255,255,0.08)] text-[#94A3B8]">
              <Sparkles className="w-3 h-3 text-[#8B5CF6]" />
              Sample answers
            </span>
          </div>

          {/* Pre-seeded prompt chips */}
          <div className="mt-4 flex flex-wrap gap-2">
            {SAGE_PREVIEW.map((exchange, idx) => (
              <button
                key={exchange.prompt}
                type="button"
                onClick={() => setActiveIndex(idx)}
                aria-pressed={activeIndex === idx}
                className={`text-[11px] sm:text-xs font-semibold px-3 py-2 rounded-lg border transition-all duration-200 ${
                  activeIndex === idx
                    ? "bg-[#8B5CF6]/25 border-[#8B5CF6]/60 text-white shadow-[0_0_14px_rgba(139,92,246,0.3)]"
                    : "bg-[#8B5CF6]/10 border-[#8B5CF6]/35 text-[#DDD6FE] hover:bg-[#8B5CF6]/20 hover:text-white"
                }`}
              >
                {exchange.prompt}
              </button>
            ))}
          </div>

          {/* Answer pane — only after a chip is picked */}
          {active === null ? (
            <p className="mt-5 pt-4 border-t border-[#8B5CF6]/20 text-xs text-[#64748B]">
              Pick a question above to see the answer SAGE returns, the query it resolved to, and
              the invoices it read.
            </p>
          ) : (
            <div className="mt-5 pt-4 border-t border-[#8B5CF6]/20">
              <p className="text-[13px] leading-relaxed text-[#E2E8F0]">{active.answer}</p>

              <div className="mt-3">
                <div className="flex items-center gap-1.5 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#64748B]">
                  <Database className="w-3 h-3 text-[#10B981]" />
                  Resolved query
                </div>
                <pre className="p-3 rounded-lg bg-[#050816] border border-[rgba(255,255,255,0.08)] font-mono text-[10px] leading-relaxed text-[#10B981] overflow-x-auto">
                  {active.sql}
                </pre>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-[#64748B]">
                  Grounded in
                </span>
                {active.citations.map((id) => (
                  <span
                    key={id}
                    className="inline-flex items-center gap-1.5 text-[10px] font-mono px-2 py-1 rounded-lg bg-[#22D3EE]/10 border border-[#22D3EE]/30 text-[#22D3EE]"
                  >
                    <Paperclip className="w-3 h-3" />
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </section>
  );
}
