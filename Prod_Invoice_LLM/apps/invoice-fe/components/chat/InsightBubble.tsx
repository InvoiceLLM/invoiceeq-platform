// =============================================================================
// FILE: components/chat/InsightBubble.tsx
// FEATURE: FE Feature 21 — Business Intelligence (spec §8, tasks 21.6 / 21.2 /
//          21.4 / 21.8). Renders BE Feature 30's insight block (§8.3 anatomy)
//          under the assistant turn that follows an attached document.
//
// WHY A BUBBLE AND NOT THE §1–§7 CARD GRID: §8 replaced the card grid, and the
// cards stayed as the COMPUTE units on the backend rather than as a rendered
// surface. `block.cards[]` is therefore not drawn one-per-card here; the two
// things a card contributes to the bubble are its findings (already flattened
// and ranked into `block.findings`) and, when it did not run, its line in
// `block.checks_not_run` — which is 21.2's "collapsed with reason", now one
// honest sentence instead of a row of empty cards.
//
// ANATOMY (§8.3), top to bottom:
//   1. verdict line          — one sentence, from the block
//   2. up to 3 findings      — currency impact (tabular numerals), a confidence
//                              chip with its reason, evidence links
//   3. "N more findings"     — collapsed, expandable
//   4. "Not checked: …"      — what did not run and why
//   5. action row            — Discuss · Add a note · Dismiss, plus thumbs
//
// INFORMATION ONLY (BE Gap 492): no control in this subtree changes an invoice,
// and there is no pin — §8 dropped `PinButton`/`pinInsight` outright.
//
// THE LIFECYCLE ROWS ARE FETCHED, NOT CARRIED. The block's findings hold a
// `finding_key`, but `POST /chat/insights/{id}/transition` is keyed by the
// `insight` row id, which the block does not contain (FE Gap 472). So the bubble
// resolves them once on mount through `GET /chat/insights?attachment_id=…` and
// keeps the action row disabled until it has. A failure there costs the two
// write actions and nothing else — the findings still render.
// =============================================================================

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Info, Sparkles } from "lucide-react";
import InsightActions from "./InsightActions";
import InsightCorrectionDialog from "./InsightCorrectionDialog";
import {
  checksNotRunLine,
  confidenceLabel,
  confidenceTone,
  evidenceInvoiceNumbers,
  fetchAttachmentInsights,
  findingImpact,
  hasRenderableInsights,
  insightForFinding,
  postInsightFeedback,
  splitFindings,
  transitionInsight,
  type Insight,
  type InsightBlock,
  type InsightFinding,
} from "@/lib/chatInsights";

export interface InsightBubbleProps {
  block: InsightBlock;
  /** The assistant turn carrying the block — the id the feedback route wants. */
  messageId: string;
  /**
   * Task 21.8's Discuss: seeds the composer with the finding text and focuses
   * it. Supplied by ChatWindow; when absent the Discuss button still renders and
   * simply has nothing to seed, so the bubble is useful in isolation.
   */
  onDiscussSeed?: (seedText: string) => void;
  /**
   * Set by ChatWindow when an `insight_update` has just redrawn this bubble
   * (§8.6 step 4's "brief updated pulse").
   */
  justUpdated?: boolean;
}

/** Confidence chip. Tone is derived, never taken from a backend colour. */
function ConfidenceChip({ finding }: { finding: InsightFinding }) {
  const tone = confidenceTone(finding.confidence);
  const palette = {
    high: "bg-emerald-950/40 text-emerald-300 border-emerald-800/50",
    med: "bg-amber-950/40 text-amber-300 border-amber-800/50",
    low: "bg-slate-800/60 text-slate-400 border-slate-700/60",
  }[tone];
  return (
    <span
      data-testid="insight-confidence-chip"
      data-confidence={tone}
      title={finding.confidence_reason || undefined}
      className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${palette}`}
    >
      {confidenceLabel(finding.confidence)}
      {finding.confidence_reason ? (
        <span className="font-normal opacity-80">— {finding.confidence_reason}</span>
      ) : null}
    </span>
  );
}

function FindingRow({
  finding,
  block,
}: {
  finding: InsightFinding;
  block: InsightBlock;
}) {
  const impact = findingImpact(finding, block);
  const invoiceNumbers = evidenceInvoiceNumbers(finding);

  return (
    <li data-testid="insight-finding" className="flex flex-col gap-1 py-1.5">
      <div className="flex items-start justify-between gap-3">
        <span className="text-[12px] leading-snug text-slate-200">{finding.title}</span>
        {impact && (
          <span
            data-testid="insight-finding-impact"
            // `tabular-nums` so amounts line up column-wise down the bubble,
            // which is the whole point of showing money in a list.
            className="shrink-0 tabular-nums text-[12px] font-semibold text-slate-100"
          >
            {impact}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <ConfidenceChip finding={finding} />
        {invoiceNumbers.map((number) => (
          // Founder 2026-09-08: evidence is plain text, not a link (FE Gap 473 closed).
          <span
            key={number}
            data-testid="insight-evidence"
            className="inline-flex items-center rounded-full border border-slate-700/60 bg-slate-800/40 px-1.5 py-0.5 text-[10px] text-slate-300"
          >
            {number}
          </span>
        ))}
      </div>
    </li>
  );
}

export default function InsightBubble({
  block,
  messageId,
  onDiscussSeed,
  justUpdated,
}: InsightBubbleProps) {
  const [rows, setRows] = useState<Insight[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [vote, setVote] = useState<"up" | "down" | null>(null);
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  const { shown, hidden } = useMemo(() => splitFindings(block), [block]);
  const notChecked = useMemo(() => checksNotRunLine(block), [block]);

  // The finding the row acts on: the top-ranked one, which is the finding the
  // verdict line is written from (`verdict_template()` takes the top finding).
  const primary = shown[0];
  const primaryRow = primary ? insightForFinding(rows, primary) : undefined;

  useEffect(() => {
    // `status: null` — a finding the user already noted or dismissed must still
    // resolve, or the bubble would offer to open it a second time on reload.
    let cancelled = false;
    fetchAttachmentInsights(block.attachment_id, { status: null })
      .then((result) => {
        if (!cancelled) setRows(result);
      })
      .catch((err) => {
        console.error("Could not load findings for this document:", err);
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
    // Re-runs when the async stage replaces the block: new findings, new rows.
  }, [block.attachment_id, block.generated_at]);

  // A row the user has already closed is reflected on first paint, so a reload
  // shows "You dismissed this finding." rather than the buttons again.
  useEffect(() => {
    if (primaryRow && !primaryRow.is_open && primaryRow.outcome) {
      setOutcome(primaryRow.outcome);
    }
  }, [primaryRow]);

  const handleTransition = useCallback(
    async (status: string, transitionOutcome: string, note?: string) => {
      if (!primaryRow) return;
      await transitionInsight(primaryRow.id, {
        status,
        outcome: transitionOutcome,
        ...(note ? { note } : {}),
      });
      setOutcome(transitionOutcome);
    },
    [primaryRow]
  );

  const handleVote = useCallback(
    async (next: "up" | "down") => {
      setVote(next);
      if (next === "down") {
        // The dialog writes the vote WITH its correction text, the same way
        // ThumbsDownTriage does — so an abandoned dialog still registers the
        // complaint but a completed one carries the reason.
        setCorrectionOpen(true);
        return;
      }
      await postInsightFeedback(messageId, {
        vote: "up",
        card: primary?.card,
        finding_key: primary?.finding_key,
        ...(primaryRow ? { insight_id: primaryRow.id } : {}),
      });
    },
    [messageId, primary, primaryRow]
  );

  if (!hasRenderableInsights(block)) return null;

  return (
    <div
      data-testid="insight-bubble"
      data-stage={block.stage}
      className={`
        mt-2 w-full rounded-xl border px-3 py-2.5
        border-purple-800/40 bg-gradient-to-r from-purple-950/20 to-blue-950/20
        ${justUpdated ? "ring-1 ring-purple-500/50 animate-pulse" : ""}
      `}
    >
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-purple-400" />
        <p data-testid="insight-verdict" className="text-[12px] font-medium leading-snug text-slate-100">
          {block.verdict}
        </p>
      </div>

      {shown.length > 0 && (
        <ul className="mt-1.5 divide-y divide-slate-700/30">
          {shown.map((finding) => (
            <FindingRow key={finding.finding_key} finding={finding} block={block} />
          ))}
        </ul>
      )}

      {hidden.length > 0 && (
        <>
          <button
            type="button"
            data-testid="insight-more-findings"
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
            className="
              mt-1 inline-flex items-center gap-1 text-[11px] text-slate-400
              hover:text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-600
            "
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded
              ? "Fewer findings"
              : `${hidden.length} more finding${hidden.length === 1 ? "" : "s"}`}
          </button>
          {expanded && (
            <ul data-testid="insight-hidden-findings" className="divide-y divide-slate-700/30">
              {hidden.map((finding) => (
                <FindingRow key={finding.finding_key} finding={finding} block={block} />
              ))}
            </ul>
          )}
        </>
      )}

      {notChecked && (
        <p
          data-testid="insight-checks-not-run"
          className="mt-1.5 flex items-start gap-1.5 text-[11px] text-slate-400"
        >
          <Info className="mt-px h-3 w-3 shrink-0" />
          {notChecked}
        </p>
      )}

      <InsightActions
        actions={block.actions || []}
        finding={primary}
        actionable={Boolean(primaryRow)}
        outcome={outcome}
        vote={vote}
        onAddNote={(note) => handleTransition("ACTED", "note", note)}
        onDismiss={() => handleTransition("DISMISSED", "dismissed")}
        onDiscuss={async () => {
          if (!onDiscussSeed) return;
          const { fetchInsightDiscussSeed } = await import("@/lib/chatInsights");
          // The backend writes the seed sentence (it knows the amount and the
          // currency); falling back to the finding title keeps Discuss useful
          // when the lifecycle row has not resolved.
          const seed = primaryRow
            ? await fetchInsightDiscussSeed(primaryRow.id)
            : `About this finding: ${primary?.title ?? block.verdict} — what should I do?`;
          onDiscussSeed(seed);
        }}
        onVote={handleVote}
      />

      {correctionOpen && (
        <InsightCorrectionDialog
          messageId={messageId}
          finding={primary}
          insightId={primaryRow?.id}
          onClose={() => setCorrectionOpen(false)}
        />
      )}
    </div>
  );
}
