"use client";

import React, { useLayoutEffect, useRef, useState } from "react";
import { cn } from "../../lib/utils";

interface KpiCardProps {
  title: string;
  /**
   * FE Gap 183: a KPI is now one figure *per currency*, not one blended
   * number. Pass an array and every entry is rendered on its own line inside
   * the card's fixed height, with the font auto-shrunk to fit (see
   * `useFitText` below). A plain string/number still works unchanged for the
   * non-money cards.
   */
  value: string | number | string[];
  subtext?: string;
  icon?: React.ReactNode;
  trend?: {
    value: string;
    type: "positive" | "negative" | "warning" | "neutral";
  };
  className?: string;
}

// Font-size bounds for the auto-fit. MAX is the old `text-2xl` (24px) so a
// single-currency card looks exactly as it always did.
//
// FE Gap 710 (founder, 2026-09-21) raised MIN from 9px to 12px. 9px was chosen
// when shrinking was the *only* escape from a fixed-height card, so the font had
// to keep going until it fit whatever it was given. The value box now scrolls,
// so a fifth currency no longer has to be paid for by making the other four
// unreadable: the text shrinks to a size a person can still read, and anything
// past that is reached by scrolling.
const MAX_FONT_PX = 24;
const MIN_FONT_PX = 12;
// The floor for the WIDTH case, which has no escape hatch: the box scrolls
// vertically, never sideways, so a figure too wide for the card would simply be
// cut off mid-digit. "₹23,227,070.20" is wider than a narrow card at 12px, so
// width keeps the old 9px floor while height stops at MIN_FONT_PX and scrolls.
const MIN_WIDTH_FONT_PX = 9;

/**
 * FE Gap 183: shrink-to-fit, explicitly required over the alternatives. The
 * card height is fixed (h-[84px]) and a multi-currency tenant can need three
 * or four lines in the space one used to take, so:
 *   - truncating would hide a currency's total outright (the exact failure
 *     this gap exists to fix),
 *   - letting it overflow spills text over the neighbouring row,
 *   - letting the card grow breaks the KPI strip's alignment.
 * So the text scales down instead. Measured imperatively against the real
 * rendered box (and re-measured on resize) rather than guessed from the number
 * of lines, because the limiting dimension is often *width* — "₹40,00,000.00"
 * overflows a 200px card long before the line count matters.
 */
function useFitText(fitKey: string) {
  const boxRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  // FE Gap 710: whether anything is still out of view once the font has shrunk
  // as far as it may. Drives the fade hint only -- the scrolling itself is
  // plain `overflow-y-auto` and needs no JavaScript.
  const [overflowing, setOverflowing] = useState(false);

  useLayoutEffect(() => {
    const box = boxRef.current;
    const content = contentRef.current;
    if (!box || !content) return;

    const fit = () => {
      // A zero-sized box means the card isn't laid out yet (hidden tab, SSR
      // hydration frame). Leave the size alone rather than collapsing to MIN.
      if (box.clientHeight <= 0 || box.clientWidth <= 0) return;

      let size = MAX_FONT_PX;
      content.style.fontSize = `${size}px`;
      const tooTall = () => content.scrollHeight > box.clientHeight + 0.5;
      const tooWide = () => content.scrollWidth > box.clientWidth + 0.5;
      while (
        size > MIN_WIDTH_FONT_PX &&
        (tooWide() || (tooTall() && size > MIN_FONT_PX))
      ) {
        size -= 1;
        content.style.fontSize = `${size}px`;
      }

      // Compared against the BOX, not the content: `content` is the inner div
      // and its own scrollHeight equals its height once it is free to be as
      // tall as it likes. Only ever flips state on a real change -- a
      // ResizeObserver callback that always set state would re-render on every
      // layout pass.
      const spills = content.scrollHeight > box.clientHeight + 0.5;
      setOverflowing((prev) => (prev === spills ? prev : spills));
    };

    fit();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fit);
    observer.observe(box);
    return () => observer.disconnect();
  }, [fitKey]);

  return { boxRef, contentRef, overflowing };
}

export default function KpiCard({
  title,
  value,
  subtext,
  icon,
  trend,
  className,
}: KpiCardProps) {
  const values = Array.isArray(value) ? value : [String(value)];
  const fitKey = values.join("|");
  const { boxRef, contentRef, overflowing } = useFitText(fitKey);
  // FE Gap 710: the fade is a "there is more below" hint, so it is wrong once
  // the reader has reached the bottom. Reset when the figures change, or a card
  // whose last state was "scrolled to the end" would open without the hint.
  const [atBottom, setAtBottom] = useState(false);
  React.useEffect(() => setAtBottom(false), [fitKey]);
  const showFade = overflowing && !atBottom;

  return (
    <div
      className={cn(
        // FE Gap 183: was a hard h-[84px]. Now min/max instead -- the card
        // takes its old height for a single-currency tenant, may grow a little
        // for two or three, and stops dead at 124px. The KPI strip is a
        // `flex flex-wrap` row, so its default align-items:stretch keeps all
        // four cards the same height as whichever one needs the most. Past the
        // cap, useFitText shrinks the text rather than the card growing on.
        "glass-panel p-3.5 rounded-xl relative overflow-hidden flex flex-col justify-between min-h-[84px] max-h-[124px] transition-all duration-300 hover:shadow-lg hover:shadow-accent-blue/5 hover:translate-y-[-2px] group",
        className
      )}
    >
      {/* Decorative gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-r from-white/0 via-white/[0.01] to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000 ease-out" />

      {/* Top Header Row */}
      <div className="flex items-center justify-between z-10 shrink-0">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          {title}
        </span>
        {icon && (
          <div className="p-2 rounded-lg bg-slate-800/40 border border-[#222D3D] text-slate-400 group-hover:text-white group-hover:border-slate-700 transition-colors">
            {icon}
          </div>
        )}
      </div>

      {/* Value & Trend Row. `items-stretch` (not `items-end`) on purpose: the
          measurement box below needs a definite height from the flex chain,
          and an `items-end` row leaves its children content-sized, which made
          the box collapse to 0 and the fit loop a no-op. The trend badge keeps
          its bottom alignment via `self-end`. */}
      <div className="flex items-stretch justify-between gap-2 mt-1 z-10 min-h-0 flex-1">
        <div className="flex flex-col min-w-0 flex-1 justify-end">
          {/* min-h-0 gives useFitText a real box to measure against; without a
              bounded parent scrollHeight always equals clientHeight and nothing
              would ever shrink.

              FE Gap 710: `overflow-y-auto`, not `overflow-hidden`. Gap 183 chose
              hidden because the font always shrank until it fit -- but with four
              or more currencies the shrink hit its floor and the lines that did
              not fit were clipped off the TOP, silently (founder, 2026-09-21,
              with a screenshot of ₹23,227,070.20 sliced in half). Scrolling is
              the escape hatch that clipping never was. The scrollbar is themed
              app-wide by FE Gap 704, and `scrollbar-gutter: stable` (globals.css)
              means its arrival does not reflow the number beside it.

              Alignment flips with the line count: a single figure stays bottom-
              aligned exactly as before, while a multi-currency stack is
              top-aligned so the FIRST currency is the one on screen. Bottom
              alignment is what put the clipped line out of sight to begin with. */}
          <div
            ref={boxRef}
            data-testid="kpi-value"
            onScroll={(e) => {
              const el = e.currentTarget;
              const done = el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
              setAtBottom((prev) => (prev === done ? prev : done));
            }}
            className={cn(
              "min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain flex flex-col [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
              values.length > 1 ? "justify-start" : "justify-end"
            )}
            style={{
              scrollbarWidth: "none",
              msOverflowStyle: "none",
              // Fades the last visible line instead of painting a gradient over
              // it: a mask needs no knowledge of the card's background, which is
              // a translucent `glass-panel` and differs between the two themes.
              ...(showFade
                ? {
                    maskImage:
                      "linear-gradient(to bottom, black calc(100% - 12px), transparent)",
                    WebkitMaskImage:
                      "linear-gradient(to bottom, black calc(100% - 12px), transparent)",
                  }
                : {}),
            }}
          >
            <div
              ref={contentRef}
              // No `truncate` here on purpose -- a clipped currency line is
              // exactly what this gap exists to prevent.
              className="font-bold text-white tracking-tight leading-tight whitespace-nowrap"
              style={{ fontSize: `${MAX_FONT_PX}px` }}
            >
              {values.map((v, i) => (
                <div key={i}>{v}</div>
              ))}
            </div>
          </div>
          {subtext && (
            // FE Gap 183: the hard max-w-[140px] cap is gone -- subtext now
            // carries per-currency detail ("USD 57% paid · INR 20% paid") and
            // the cap clipped it well before the card ran out of room. It
            // still truncates against the real available width, and the full
            // string is on the title attribute.
            <span
              title={subtext}
              className="text-[9px] text-slate-400 mt-1 font-medium truncate shrink-0"
            >
              {subtext}
            </span>
          )}
        </div>

        {trend && (
          <span
            className={cn(
              "text-xs font-semibold px-2 py-0.5 rounded-full flex items-center gap-0.5 border shrink-0 ml-2 self-end",
              trend.type === "positive" && "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
              trend.type === "negative" && "bg-rose-500/10 border-rose-500/20 text-rose-400",
              trend.type === "warning" && "bg-amber-500/10 border-amber-500/20 text-amber-400",
              trend.type === "neutral" && "bg-slate-500/10 border-slate-500/20 text-slate-400"
            )}
          >
            {trend.value}
          </span>
        )}
      </div>
    </div>
  );
}
