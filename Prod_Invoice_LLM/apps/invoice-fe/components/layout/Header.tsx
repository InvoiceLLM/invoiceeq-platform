"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, Palette, Moon } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import AtlasModeToggle from "./AtlasModeToggle";
import PageHeader from "./PageHeader";
import { usePageHeaderActionsRef, usePageHeaderMeta } from "./PageHeaderContext";

/**
 * Gap 87 / Gap 95 — how many invoices are actually waiting on a human.
 *
 * The bell used to be a `<button>` with no `onClick` and a hardcoded blue dot
 * that was *always* lit, i.e. it permanently implied unread notifications that
 * did not exist. Rather than build a notification system nobody asked for, it
 * now shows the one number this product genuinely has to chase: the same
 * "Needs Attention" set the dashboard widget lists (inbound `AUDIT_REQUIRED`
 * + outbound `NEEDS_REVIEW`), and links to the real queue.
 *
 * Counts come from the `X-Total-Count` header both list endpoints already set
 * for pagination, so `limit=1` is enough — no page of rows is fetched just to
 * count them. Settled independently: a receive-only tenant's outbound call may
 * 403, which must not suppress the inbound count.
 *
 * Gap 199: Header stays mounted under the app layout, so deps of `[enabled]`
 * alone froze the badge across client navigations. Re-fetch on `pathname`
 * change and on tab focus/visibility (debounced) so clearing a review queue
 * updates the bell without a hard reload.
 */
function useNeedsAttentionCount(enabled: boolean): number | null {
  const [count, setCount] = useState<number | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    if (!enabled) {
      setCount(null);
      return;
    }
    let cancelled = false;
    let focusTimer: ReturnType<typeof setTimeout> | null = null;

    const readTotal = async (url: string): Promise<number> => {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) return 0;
      return Number(res.headers.get("X-Total-Count") ?? "0") || 0;
    };

    const fetchCount = () => {
      Promise.allSettled([
        readTotal("/api/invoices?status=AUDIT_REQUIRED&limit=1"),
        readTotal("/api/outbound-dashboard/invoices?status=NEEDS_REVIEW&limit=1"),
      ]).then((results) => {
        if (cancelled) return;
        setCount(
          results.reduce((sum, r) => sum + (r.status === "fulfilled" ? r.value : 0), 0)
        );
      });
    };

    fetchCount();

    const onFocusOrVisible = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      if (focusTimer) clearTimeout(focusTimer);
      focusTimer = setTimeout(() => {
        if (!cancelled) fetchCount();
      }, 500);
    };
    window.addEventListener("focus", onFocusOrVisible);
    document.addEventListener("visibilitychange", onFocusOrVisible);

    return () => {
      cancelled = true;
      if (focusTimer) clearTimeout(focusTimer);
      window.removeEventListener("focus", onFocusOrVisible);
      document.removeEventListener("visibilitychange", onFocusOrVisible);
    };
  }, [enabled, pathname]);

  return count;
}

export default function Header() {
  const { canAudit } = useAuth();
  const needsAttention = useNeedsAttentionCount(canAudit);
  const { toggleTheme, isInfinevo } = useTheme();

  // FE Gap 110: the active route's title/badge/subtitle and its own header-row
  // controls, both fed up from the page through PageHeaderContext.
  const pageMeta = usePageHeaderMeta();
  const actionsRef = usePageHeaderActionsRef();

  return (
    // FE Gap 110: this is now the app's one and only page header. Three flex
    // children read left-to-right across the top of the screen -- the sidebar's
    // brand mark, this row's title cluster, and the tenant/profile block -- so
    // `justify-between` here puts the title where the agreed design has it,
    // between the brand and the profile, rather than every screen drawing its
    // own title bar underneath (which on Trainer/Settings meant two stacked
    // header bars, the leftover half of Gaps 76/88).
    <header className="h-16 shrink-0 border-b border-[#222D3D] bg-[#0B0F19]/80 backdrop-blur-md flex items-center justify-between gap-2 sm:gap-3 xl:gap-4 px-3 sm:px-4 xl:px-6 2xl:px-8 text-slate-300 z-10">
      {/* Active route's title cluster. Empty on routes that declare none. */}
      <div className="min-w-[130px] sm:min-w-[160px] flex-1 max-w-fit sm:max-w-none">{pageMeta && <PageHeader {...pageMeta} />}</div>

      {/* Right Controls Container */}
      <div className="flex items-center gap-2 sm:gap-3 xl:gap-4 shrink-0 min-w-0">
        {/* Page-specific header controls portal in here (Trainer's Commit /
            Rule History, Ingestion's Receiving/Sending toggle, an invoice's
            status badge). Always rendered so the portal has a stable target;
            it collapses to zero width when the route contributes nothing.

            Gap 110 also removed the HelpCircle link that used to sit here: it
            was a second entry point to the exact same /help route the Sidebar
            already has. The Sidebar's "Help" item is the one that stays. */}
        <div ref={actionsRef} className="flex items-center gap-1 sm:gap-1.5 xl:gap-2.5 empty:hidden" />

        {/* Needs Attention -- Gap 87/95. Rendered only for a user who can
            actually open the queue; the badge appears only when the count is
            genuinely non-zero, replacing the old always-lit dot that implied
            unread notifications at all times. */}
        {canAudit && (
          <Link
            href="/invoices"
            aria-label={
              needsAttention
                ? `${needsAttention} invoice${needsAttention === 1 ? "" : "s"} need review`
                : "Invoice queue"
            }
            title={
              needsAttention
                ? `${needsAttention} invoice${needsAttention === 1 ? "" : "s"} need review`
                : "Nothing needs review right now"
            }
            className="p-1.5 rounded-lg hover:bg-[#1E293B]/50 hover:text-white transition-colors text-slate-400 relative"
          >
            <Bell className="h-5 w-5" />
            {needsAttention !== null && needsAttention > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-amber-500 text-[10px] font-bold text-[#0B0F19] flex items-center justify-center ring-2 ring-[#0B0F19]">
                {needsAttention > 99 ? "99+" : needsAttention}
              </span>
            )}
          </Link>
        )}

        {/* ATLAS / traditional toggle — D48, FE Gap 694.
            Beside the bell, as ruled. D48 partially reverses D10: the classic
            toggle was deleted because there was no second surface, and ATLAS
            (`/work`) is one. The existing screens are not removed, not re-homed
            and not redirected — this only chooses where the user goes.
            Not gated on any grant: every signed-in user has a work screen, and
            an ungranted one is told so by the screen itself (D3). */}
        <AtlasModeToggle />

        {/* Dual-Theme Toggle Switch — FE Gap 478 */}
        <button
          type="button"
          role="switch"
          aria-checked={isInfinevo}
          onClick={toggleTheme}
          aria-label={isInfinevo ? "Switch to Classic Dark Theme" : "Switch to InfiNevo PPT Brand Theme"}
          title={isInfinevo ? "Active Theme: InfiNevo PPT Brand (Click to toggle Classic Dark)" : "Active Theme: Classic Dark (Click to toggle InfiNevo Brand)"}
          className={`relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-300 cursor-pointer focus:outline-none select-none ${
            isInfinevo
              ? "bg-gradient-to-r from-[#0F6FC6] to-[#009DD9] border border-[#009DD9]/80 shadow-[0_0_12px_rgba(0,157,217,0.4)]"
              : "bg-[#131B2A] border border-[#222D3D] hover:border-slate-600"
          }`}
        >
          {/* Background Track Icons */}
          <Moon className={`w-3.5 h-3.5 absolute left-1.5 transition-opacity duration-200 pointer-events-none ${isInfinevo ? "text-white/80 opacity-100" : "opacity-0"}`} />
          <Palette className={`w-3.5 h-3.5 absolute right-1.5 transition-opacity duration-200 pointer-events-none ${isInfinevo ? "opacity-0" : "text-slate-400 opacity-100"}`} />

          {/* Sliding Thumb Knob */}
          <span
            className={`w-5 h-5 rounded-full bg-white shadow-md transform transition-transform duration-300 ease-in-out flex items-center justify-center ${
              isInfinevo ? "translate-x-8" : "translate-x-1"
            }`}
          >
            {isInfinevo ? (
              <Palette className="w-3 h-3 text-[#0F6FC6]" />
            ) : (
              <Moon className="w-3 h-3 text-slate-700" />
            )}
          </span>
        </button>
      </div>
    </header>
  );
}
