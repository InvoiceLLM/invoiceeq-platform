"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bell, HelpCircle, ChevronDown, User, LogOut, Settings } from "lucide-react";
import { useClerk, useUser } from "@clerk/nextjs";
import { useAuth } from "@/hooks/useAuth";

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
 */
function useNeedsAttentionCount(enabled: boolean): number | null {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    if (!enabled) {
      setCount(null);
      return;
    }
    let cancelled = false;

    const readTotal = async (url: string): Promise<number> => {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) return 0;
      return Number(res.headers.get("X-Total-Count") ?? "0") || 0;
    };

    Promise.allSettled([
      readTotal("/api/invoices?status=AUDIT_REQUIRED&limit=1"),
      readTotal("/api/outbound-dashboard/invoices?status=NEEDS_REVIEW&limit=1"),
    ]).then((results) => {
      if (cancelled) return;
      setCount(
        results.reduce((sum, r) => sum + (r.status === "fulfilled" ? r.value : 0), 0)
      );
    });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return count;
}

export default function Header() {
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const { signOut } = useClerk();
  const { user } = useUser();
  // Gated on canAudit for the same reason Sidebar hides the Audit Queue item:
  // a user who cannot open the queue gains nothing from a count of it, and the
  // backend would 403 the calls anyway.
  const { canAudit } = useAuth();
  const needsAttention = useNeedsAttentionCount(canAudit);

  const handleSignOut = async () => {
    setShowProfileMenu(false);
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

  const userEmail = user?.primaryEmailAddress?.emailAddress || "admin@acme.com";
  const firstName = user?.firstName || "Alex";
  const lastName = user?.lastName || "R.";
  const initials = `${firstName.charAt(0)}${lastName.charAt(0)}`.toUpperCase() || "AR";
  const orgName = (user?.unsafeMetadata?.orgName as string) || "Acme Corp.";
  const userRole = (user?.unsafeMetadata?.role as string) || "Admin";

  return (
    // Gap 87/95: the global search box was removed from this row, so there is
    // no left-hand group left to justify against -- `justify-end` rather than
    // `justify-between`, which would otherwise leave the controls floating in
    // the middle of an empty header. Page titles already live in PageHeader, so
    // nothing needs to take the search box's place.
    <header className="h-16 border-b border-[#222D3D] bg-[#0B0F19]/80 backdrop-blur-md flex items-center justify-end px-8 text-slate-300 z-10">
      {/* Right Controls Container */}
      <div className="flex items-center gap-6">
        {/* Help Link -- Gap 87 finding G: this was a <button> with a title and
            no onClick and no href at all, so clicking it did nothing even
            though /help has existed as a real route (app/help/) all along. Now
            a real Link to it. */}
        <Link
          href="/help"
          aria-label="Help Center"
          className="p-1.5 rounded-lg hover:bg-[#1E293B]/50 hover:text-white transition-all text-slate-400 relative"
          title="Help Center"
        >
          <HelpCircle className="h-5 w-5" />
        </Link>

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
        <div className="relative">
          <button
            onClick={() => setShowProfileMenu(!showProfileMenu)}
            className="flex items-center gap-3.5 pl-2 py-1.5 pr-3 rounded-lg hover:bg-[#1E293B]/40 transition-all duration-200 group"
          >
            <div className="w-8 h-8 rounded-full bg-[#3B82F6]/10 border border-[#3B82F6]/30 flex items-center justify-center text-[#3B82F6] text-sm font-semibold select-none">
              {initials}
            </div>
            <div className="text-left hidden md:block">
              <p className="text-xs font-semibold text-white tracking-wide">{firstName} {lastName}</p>
              <p className="text-[10px] text-slate-400 mt-0.5">{orgName} ({userRole})</p>
            </div>
            <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
          </button>

          {/* Profile Menu Dropdown */}
          {showProfileMenu && (
            <div className="absolute right-0 mt-2.5 w-52 bg-[#0F172A] border border-[#222D3D] rounded-xl shadow-xl py-2 z-20 animate-in fade-in slide-in-from-top-2 duration-150">
              <div className="px-4 py-2 border-b border-[#222D3D] mb-1.5">
                <p className="text-xs text-slate-400">Signed in as</p>
                <p className="text-xs font-semibold text-white truncate mt-0.5">{userEmail}</p>
              </div>
              <button 
                onClick={() => setShowProfileMenu(false)}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-[#1E293B]/70 hover:text-white transition-colors text-left"
              >
                <User className="w-4 h-4 text-slate-400" />
                My Profile
              </button>
              <button 
                onClick={() => setShowProfileMenu(false)}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-[#1E293B]/70 hover:text-white transition-colors text-left"
              >
                <Settings className="w-4 h-4 text-slate-400" />
                Account Settings
              </button>
              <div className="h-px bg-[#222D3D] my-1.5"></div>
              <button
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
