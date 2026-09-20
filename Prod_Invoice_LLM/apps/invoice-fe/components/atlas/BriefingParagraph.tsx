// =============================================================================
// FILE: components/atlas/BriefingParagraph.tsx
// FEATURE: FE Feature 24 task 24.4 (spec §2, §3 step 8) — one paragraph of the
//          briefing, with every record it rests on rendered as a way to go and
//          check it.
//
// **A CITATION IS THE READER'S WAY OUT OF THE PROSE.** The paragraph is model
// text about the user's money; the only thing that makes it checkable is that
// each record under it is one click away. So a citation is never decoration:
// `recommendation` scrolls to that line on this screen and highlights it for two
// seconds, `invoice` opens the invoice, `rule` opens what ATLAS remembers,
// `action` opens what ATLAS did.
//
// **THE TEXT IS PRINTED AS SENT.** No trimming, no capitalising, no markdown
// rendering, no figure formatting — the numbers in it were witnessed and
// re-checked on the backend (BE 35 §3.3's guards) and re-rendering one here
// would be this app writing prose about money. Same rule as `AtlasLine`: this
// file does no arithmetic.
//
// **A CITATION IS LABELLED WITH THE RECORD, NOT ITS KEY (FE Gap 706).** What the
// reader sees is the invoice number the `/atlas/lines` payload already carries
// (`lineLabels`), the number the paragraph itself names, or a plain word —
// never `audit-approve-530bd65a-…`, which is what the 2026-09-20 live run
// printed under a sentence about ₹4,37,190.00. The id is still on the element:
// `data-citation-id` for tests and automation, `title`/`aria-label` for anyone
// checking by hand. The label is DERIVED FROM DATA, never parsed out of the id —
// see `citationLabel()` in `lib/atlasBriefing.ts` for why.
//
// A KIND WITH NO DESTINATION IS STILL SHOWN. `shortfall` and `recon_row` name
// records that are not addressable by a route today; they render as plain
// evidence rather than being dropped, because hiding a citation would make a
// paragraph look better-founded than the panel can prove it is.
// =============================================================================

"use client";

import Link from "next/link";

import {
  citationLabel,
  type BriefingParagraph as BriefingParagraphData,
  type Citation,
} from "@/lib/atlasBriefing";

/** The class `revealCitation()` toggles. Asserted by the unit test. */
export const BRIEFING_HIGHLIGHT_CLASS = "atlas-briefing-cited";

/** Spec §3 step 8: "a two-second highlight". */
export const BRIEFING_HIGHLIGHT_MS = 2000;

/**
 * Where a citation of each kind lives on this app.
 *
 * `recommendation` targets `AtlasLine`'s own `data-line-id`, which is already on
 * every rendered line (FE 23 task 2) — this component does not need the line
 * list, only the DOM contract it already publishes.
 */
const PANEL_SELECTOR: Record<string, string> = {
  rule: '[data-testid="atlas-memory"]',
  action: '[data-testid="atlas-action-log"]',
};

/** `/invoices/review/<id>` — this app's own route, the one `actionDestination()` uses. */
export function invoiceHref(recordId: string): string {
  return `/invoices/review/${encodeURIComponent(recordId)}`; // hardcode-ok: this app's own route, no figure in it
}

/**
 * The rendered line carrying this record id, or null.
 *
 * Found by scanning the published attribute rather than by building a CSS
 * selector out of the id: a record id is the backend's string (composed ids
 * like `cash-INR` included) and quoting one into a selector is an escaping
 * problem this component does not need to have. It also keeps a regex literal
 * out of this file, which `atlas-no-client-arithmetic.test.ts` reads as a
 * division operator.
 */
function lineElement(recordId: string): Element | null {
  const candidates = Array.from(document.querySelectorAll("[data-line-id]"));
  return candidates.find((el) => el.getAttribute("data-line-id") === recordId) ?? null;
}

function highlight(el: Element | null): void {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add(BRIEFING_HIGHLIGHT_CLASS);
  setTimeout(() => el.classList.remove(BRIEFING_HIGHLIGHT_CLASS), BRIEFING_HIGHLIGHT_MS);
}

/**
 * Take the reader to the record a citation names (spec §3 step 8).
 *
 * Done by reaching into the DOM rather than by lifting the line list, the memory
 * panel and the action log into shared state: all three are siblings on this
 * screen that already own their own data, and giving the briefing a handle on
 * each one's internals would make the panel a controller of the screen instead
 * of a reader of it. The one thing it uses is each component's published
 * `data-` attribute.
 *
 * A collapsed panel is opened first — landing a user on a closed accordion would
 * be a link that visibly did nothing.
 */
export function revealCitation(citation: Citation): void {
  if (typeof document === "undefined") return;

  if (citation.record_kind === "recommendation") {
    highlight(lineElement(citation.record_id));
    return;
  }

  const selector = PANEL_SELECTOR[citation.record_kind];
  if (!selector) return;
  const panel = document.querySelector(selector);
  const toggle = panel?.querySelector<HTMLButtonElement>('button[aria-expanded="false"]');
  toggle?.click();
  highlight(panel);
}

/** Which citations are a link the user can follow, and which are plain evidence. */
function isFollowable(citation: Citation): boolean {
  return (
    citation.record_kind === "recommendation" ||
    citation.record_kind === "invoice" ||
    citation.record_kind in PANEL_SELECTOR
  );
}

export interface BriefingParagraphProps {
  paragraph: BriefingParagraphData;
  /**
   * FE Gap 706: recommendation id → the invoice number in that line's own
   * headline, built by `WorkScreen` from the `/atlas/lines` payload. Optional,
   * because the panel renders before the map can matter and a missing entry is
   * a generic word rather than an id.
   */
  lineLabels?: ReadonlyMap<string, string>;
  /** What a non-route citation does. Defaults to `revealCitation`. */
  onCitationClick?: (citation: Citation) => void;
  /**
   * The question renders its own text through this component and must not count
   * as a paragraph — "3 paragraphs, 2 withheld" has to mean paragraphs.
   */
  testId?: string;
}

export default function BriefingParagraphView({
  paragraph,
  lineLabels,
  onCitationClick = revealCitation,
  testId = "briefing-paragraph",
}: BriefingParagraphProps) {
  return (
    <div data-testid={testId} className="space-y-1">
      <p className="text-[13px] leading-relaxed text-slate-200">{paragraph.text}</p>
      <p
        data-testid="briefing-paragraph-citations"
        className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500"
      >
        {(paragraph.citations ?? []).map((citation, index) => {
          const key = `${citation.record_kind}:${citation.record_id}:${index}`; // hardcode-ok: a React key from ids, never rendered
          // FE Gap 706: what the reader sees is the record, not its primary
          // key. The id stays on the element — `data-citation-id` for tests and
          // automation, `title`/`aria-label` for anyone checking by hand.
          const label = citationLabel(citation, paragraph.text, lineLabels);
          const titled = `${citation.tool} ${citation.record_id}`; // hardcode-ok: the tool name and the id, neither a figure
          if (!isFollowable(citation)) {
            return (
              <span
                key={key}
                data-testid="briefing-citation"
                data-citation-kind={citation.record_kind}
                data-citation-id={citation.record_id}
                title={titled}
                aria-label={titled}
              >
                {label}
              </span>
            );
          }
          if (citation.record_kind === "invoice") {
            return (
              <Link
                key={key}
                href={invoiceHref(citation.record_id)}
                data-testid="briefing-citation"
                data-citation-kind={citation.record_kind}
                data-citation-id={citation.record_id}
                title={titled}
                aria-label={titled}
                className="underline decoration-dotted underline-offset-2 hover:text-slate-300"
              >
                {label}
              </Link>
            );
          }
          return (
            <button
              key={key}
              type="button"
              data-testid="briefing-citation"
              data-citation-kind={citation.record_kind}
              data-citation-id={citation.record_id}
              title={titled}
              aria-label={titled}
              onClick={() => onCitationClick(citation)}
              className="underline decoration-dotted underline-offset-2 hover:text-slate-300"
            >
              {label}
            </button>
          );
        })}
      </p>
    </div>
  );
}
