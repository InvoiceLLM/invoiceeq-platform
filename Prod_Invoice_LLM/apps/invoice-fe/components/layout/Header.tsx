"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, ChevronDown, User, LogOut, Settings } from "lucide-react";
import { useClerk, useUser } from "@clerk/nextjs";
import { useAuth, clearAuth } from "@/hooks/useAuth";
import PageHeader from "./PageHeader";
import { usePageHeaderActionsRef, usePageHeaderMeta } from "./PageHeaderContext";

// Marketing site's login page -- separate deployment, so this needs the full
// origin, not an internal Next.js route. Local dev port is unconfirmed since
// invoice-website has no dev script/port assignment yet; update once it does.
const WEBSITE_URL = process.env.NEXT_PUBLIC_WEBSITE_URL || "http://localhost:3000";

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

/**
 * FE Gap 116 — who is actually signed in.
 *
 * The old code was `user?.firstName || "Alex"` / `user?.lastName || "R."`,
 * described as a pre-load placeholder. It was not behaving as one: `useUser()`
 * is reactive, so a *loading* profile does resolve and re-render on its own.
 * The reason every real user saw "Alex R" is that `firstName`/`lastName` are
 * genuinely empty on these accounts -- `invoice-website`'s `app/signup/page.tsx`
 * calls `signUp.create({ emailAddress, password, unsafeMetadata })` and collects
 * organisation name, org type and country, but never a person's name. Nothing
 * ever writes those two fields, so the fallback was permanent, and it read as
 * real data rather than as missing data.
 *
 * So the fallback chain is now honest about what it knows:
 *   1. real first/last name, when Clerk has them (it will, once sign-up asks);
 *   2. otherwise the email local part, which is real user-specific data;
 *   3. otherwise nothing -- the caller renders a skeleton, not an invented name.
 * `isLoaded` is now read and handled explicitly instead of being implied, so
 * the pre-load moment shows a skeleton rather than any name at all.
 */
function useDisplayIdentity() {
  const { user, isLoaded } = useUser();

  const email = user?.primaryEmailAddress?.emailAddress ?? "";
  const first = user?.firstName?.trim() ?? "";
  const last = user?.lastName?.trim() ?? "";

  // "sanjib.banerjee" -> "Sanjib Banerjee". Separators are the only reliable
  // word boundary in a local part; anything else would be guesswork.
  const fromEmail = email
    .split("@")[0]
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

  const name = [first, last].filter(Boolean).join(" ") || fromEmail;
  const initials =
    (first && last
      ? `${first.charAt(0)}${last.charAt(0)}`
      : name.replace(/\s+/g, "").slice(0, 2)
    ).toUpperCase() || "";

  return { isLoaded, email, name, initials };
}

export default function Header() {
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const { signOut, openUserProfile } = useClerk();
  const { user } = useUser();
  // Gated on canAudit for the same reason Sidebar hides the Audit Queue item:
  // a user who cannot open the queue gains nothing from a count of it, and the
  // backend would 403 the calls anyway.
  const { canAudit, role, tenantName, loading: authLoading } = useAuth();
  const needsAttention = useNeedsAttentionCount(canAudit);
  const isAdmin = role === "Admin";

  // FE Gap 110: the active route's title/badge/subtitle and its own header-row
  // controls, both fed up from the page through PageHeaderContext.
  const pageMeta = usePageHeaderMeta();
  const actionsRef = usePageHeaderActionsRef();

  // Gap 142: dismiss the profile menu on navigation and outside click.
  useEffect(() => {
    setShowProfileMenu(false);
  }, [pathname]);

  useEffect(() => {
    if (!showProfileMenu) return;
    const onPointerDown = (event: MouseEvent) => {
      if (
        profileMenuRef.current &&
        !profileMenuRef.current.contains(event.target as Node)
      ) {
        setShowProfileMenu(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [showProfileMenu]);

  const handleSignOut = async () => {
    setShowProfileMenu(false);
    // Gap 138: clear the module-level identity cache before tearing down the
    // Clerk session so a later sign-in in the same tab cannot inherit stale
    // role/plan from the previous user.
    clearAuth();
    try {
      try {
        const response = await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clerk_user_id: user?.id }),
        });
        if (!response.ok) {
          console.warn("Backend logout returned:", response.status);
        }
      } catch (backendErr) {
        // Non-blocking -- proceed with Clerk sign-out even if the backend call fails
        console.warn("Backend logout failed (non-blocking):", backendErr);
      }

      await signOut();
    } catch (err) {
      console.error("Sign out error", err);
    }

    window.location.href = `${WEBSITE_URL}/login`;
  };

  const handleOpenProfile = () => {
    setShowProfileMenu(false);
    // Gap 142: no in-app profile page — Clerk's account modal is the real dest.
    openUserProfile();
  };

  const { isLoaded, email: userEmail, name: displayName, initials } = useDisplayIdentity();

  // BE Gap 133: the org name shown here is the backend's *resolved tenant*, not
  // Clerk's `unsafeMetadata.orgName`. Those were two independent sources: the
  // metadata is written once at sign-up and never reconciled, so a user whose
  // organisation failed to provision saw the org they signed up with while
  // their invoices lived in an entirely different tenant -- with nothing in the
  // UI able to reveal the divergence. `unsafeMetadata.orgName` is kept only as
  // a placeholder for the moment before /auth/me resolves, so the header does
  // not flicker empty on every page load.
  // (The role beside it is the backend's for a related reason -- that same
  // metadata holds the literal string "admin,user".)
  const orgName = authLoading
    ? (user?.unsafeMetadata?.orgName as string) || ""
    : tenantName || "";
  const orgLine = [orgName, !authLoading && role ? `(${role})` : ""]
    .filter(Boolean)
    .join(" ");

  return (
    // FE Gap 110: this is now the app's one and only page header. Three flex
    // children read left-to-right across the top of the screen -- the sidebar's
    // brand mark, this row's title cluster, and the tenant/profile block -- so
    // `justify-between` here puts the title where the agreed design has it,
    // between the brand and the profile, rather than every screen drawing its
    // own title bar underneath (which on Trainer/Settings meant two stacked
    // header bars, the leftover half of Gaps 76/88).
    <header className="h-16 shrink-0 border-b border-[#222D3D] bg-[#0B0F19]/80 backdrop-blur-md flex items-center justify-between gap-4 px-8 text-slate-300 z-10">
      {/* Active route's title cluster. Empty on routes that declare none. */}
      <div className="min-w-0 flex-1">{pageMeta && <PageHeader {...pageMeta} />}</div>

      {/* Right Controls Container */}
      <div className="flex items-center gap-6 shrink-0">
        {/* Page-specific header controls portal in here (Trainer's Commit /
            Rule History, Ingestion's Receiving/Sending toggle, an invoice's
            status badge). Always rendered so the portal has a stable target;
            it collapses to zero width when the route contributes nothing.

            Gap 110 also removed the HelpCircle link that used to sit here: it
            was a second entry point to the exact same /help route the Sidebar
            already has. The Sidebar's "Help" item is the one that stays. */}
        <div ref={actionsRef} className="flex items-center gap-3 empty:hidden" />

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
            className="p-1.5 rounded-lg hover:bg-[#1E293B]/50 hover:text-white transition-all text-slate-400 relative"
          >
            <Bell className="h-5 w-5" />
            {needsAttention !== null && needsAttention > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-amber-500 text-[10px] font-bold text-[#0B0F19] flex items-center justify-center ring-2 ring-[#0B0F19]">
                {needsAttention > 99 ? "99+" : needsAttention}
              </span>
            )}
          </Link>
        )}

        {/* Vertical Divider */}
        <div className="h-6 w-px bg-[#222D3D]"></div>

        {/* User Profile Card Dropdown */}
        <div className="relative" ref={profileMenuRef}>
          <button
            type="button"
            onClick={() => setShowProfileMenu(!showProfileMenu)}
            className="flex items-center gap-3.5 pl-2 py-1.5 pr-3 rounded-lg hover:bg-[#1E293B]/40 transition-all duration-200 group"
          >
            {/* Gap 116: while Clerk is still resolving, this shows a skeleton.
                It used to show "AR"/"Alex R." -- a specific, plausible, wrong
                person, indistinguishable from real data. */}
            <div className="w-8 h-8 rounded-full bg-[#3B82F6]/10 border border-[#3B82F6]/30 flex items-center justify-center text-[#3B82F6] text-sm font-semibold select-none">
              {isLoaded ? initials : <span className="w-4 h-4 rounded bg-slate-600/40 animate-pulse" />}
            </div>
            <div className="text-left hidden md:block">
              {isLoaded ? (
                <>
                  <p className="text-xs font-semibold text-white tracking-wide">
                    {displayName || "Signed in"}
                  </p>
                  {orgLine && <p className="text-[10px] text-slate-400 mt-0.5">{orgLine}</p>}
                </>
              ) : (
                <>
                  <span className="block w-24 h-3 rounded bg-slate-600/40 animate-pulse" />
                  <span className="block w-16 h-2 rounded bg-slate-700/40 animate-pulse mt-1.5" />
                </>
              )}
            </div>
            <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
          </button>

          {/* Profile Menu Dropdown — Gap 142: real destinations + dismiss on
              outside click / route change (handlers above). */}
          {showProfileMenu && (
            <div className="absolute right-0 mt-2.5 w-52 bg-[#0F172A] border border-[#222D3D] rounded-xl shadow-xl py-2 z-20 animate-in fade-in slide-in-from-top-2 duration-150">
              <div className="px-4 py-2 border-b border-[#222D3D] mb-1.5">
                <p className="text-xs text-slate-400">Signed in as</p>
                {/* Gap 116: was `|| "admin@acme.com"` -- a fabricated address
                    shown as if it were the account's own. */}
                <p className="text-xs font-semibold text-white truncate mt-0.5">
                  {userEmail || (isLoaded ? "—" : "…")}
                </p>
              </div>
              <button
                type="button"
                onClick={handleOpenProfile}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-[#1E293B]/70 hover:text-white transition-colors text-left"
              >
                <User className="w-4 h-4 text-slate-400" />
                My Profile
              </button>
              {isAdmin && (
                <Link
                  href="/settings"
                  onClick={() => setShowProfileMenu(false)}
                  className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-[#1E293B]/70 hover:text-white transition-colors text-left"
                >
                  <Settings className="w-4 h-4 text-slate-400" />
                  Account Settings
                </Link>
              )}
              <div className="h-px bg-[#222D3D] my-1.5"></div>
              <button
                type="button"
                onClick={handleSignOut}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors text-left"
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
