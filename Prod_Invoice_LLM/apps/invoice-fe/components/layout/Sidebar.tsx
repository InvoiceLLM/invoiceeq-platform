"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  UploadCloud,
  Files,
  MessageSquare,
  GraduationCap,
  Settings,
  CreditCard,
  HelpCircle,
  FileText,
  ListChecks,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { useAuth } from "../../hooks/useAuth";
import { canAccessRoute } from "@/lib/routePermissions";

// FE Gap 273: persisted so the collapsed/expanded choice survives a reload.
const SIDEBAR_COLLAPSED_KEY = "sidebar-collapsed";

export default function Sidebar() {
  const pathname = usePathname();
  // FE Gap 99 / Feature 1.1 Task 1.1.5: real permissions, from GET /auth/me.
  // Until this landed, useAuth() was a localStorage mock that made everyone an
  // Admin, and this list rendered unconditionally -- every user saw every item.
  const { tenantId, role, canTrain, canAudit, canLoad, loading } = useAuth();

  // FE Gap 273: collapses to an icon-only rail so the main content area gets
  // more room. Starts false on both server and first client render (avoids a
  // hydration mismatch) and only reads localStorage after mount, matching
  // this app's other durable-preference toggles.
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    if (window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true") {
      setCollapsed(true);
    }
  }, []);
  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      return next;
    });
  };

  // Navigation items definition for the primary sidebar.
  // `visible` implements feature_1.1_rbac.md's access model:
  //   Dashboard / Chat / Help  -> every signed-in user
  //   Ingest                   -> can_load
  //   Audit Queue              -> can_audit
  //   AI Trainer               -> can_train
  //   Settings / Subscriptions -> Admin only
  // Admins pass all three permission checks (resolved backend-side in
  // dependencies.resolve_permissions, not re-derived here).
  // NOTE FOR DEVELOPERS: Feature 6 (AI Trainer Interactive Sandbox) route is registered at '/trainer'
  // using the GraduationCap icon to provide direct access to rule fine-tuning.
  // /admin is intentionally absent -- it has never been in the sidebar and
  // adding it was explicitly out of scope for this change.
  const menuItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard, visible: true },
    { name: "Ingest", href: "/ingestion", icon: UploadCloud, visible: canLoad },
    // Re-added 2026-07-29 (Task 4.9, Dashboard/Audit split): previously
    // removed because it pointed at "/audit", which never existed as a
    // route -- there was nowhere real to land. Now points at the real
    // /invoices queue screen.
    { name: "Audit Queue", href: "/invoices", icon: ListChecks, visible: canAudit },
    // Feature 27 E10 / task R5(c). A classified non-invoice document leaves the
    // `invoice` table entirely, so it is absent from both Ingest and the Audit
    // Queue by design -- this is the only place it is visible. Gated on the same
    // permission as the audit queue: it is the same population of uploaded
    // documents, minus the ones that turned out to be payables.
    { name: "Documents", href: "/documents", icon: Files, visible: canAudit },
    // AI Trainer link for rule scope fine-tuning & sandbox evaluation (Feature 6)
    { name: "AI Trainer", href: "/trainer", icon: GraduationCap, visible: canTrain },
    { name: "Chat", href: "/chat", icon: MessageSquare, visible: true },
    { name: "Settings", href: "/settings", icon: Settings, visible: role === "Admin" },
    // FE Gap 143: the one page a paying tenant checks regularly -- plan, spend
    // and remaining allowance -- was three clicks deep behind AI Trainer ->
    // View Plan, or two behind the Settings tile grid, and invisible to anyone
    // who doesn't already know it exists. Gated on Admin exactly as Settings
    // is: the screen it lands on is the workspace's billing record, and no
    // role that can't open Settings can act on it anyway (changing plan is
    // Admin-only backend-side too, routers/billing.py::create_checkout_session).
    { name: "Subscriptions", href: "/settings/subscriptions", icon: CreditCard, visible: role === "Admin" },
    { name: "Help", href: "/help", icon: HelpCircle, visible: true },
  ];

  // While identity is still in flight, show only the three universal items.
  // Rendering the full list optimistically would flash Trainer/Audit/Settings
  // at users who are not allowed to see them.
  // Gap 423: `visible` above and the route guard must never disagree -- a link
  // you can see leading to a screen that refuses you (or the reverse) is worse
  // than either alone. Both now consult lib/routePermissions.ts, and this
  // assertion is the tripwire: if the two ever diverge for a route, the nav
  // item is hidden (the safe direction) and it is logged rather than silently
  // rendering a link the guard will block.
  const visibleItems = menuItems.filter((item) => {
    if (loading) {
      return item.href === "/dashboard" || item.href === "/chat" || item.href === "/help";
    }
    const guardAllows = canAccessRoute(item.href, { role, canLoad, canAudit, canTrain });
    if (item.visible !== guardAllows && process.env.NODE_ENV !== "production") {
      console.warn(
        `[Gap 423] Sidebar/RouteGuard disagree for ${item.href}: ` +
        `sidebar=${item.visible} guard=${guardAllows}. Reconcile lib/routePermissions.ts.`
      );
    }
    return item.visible && guardAllows;
  });

  // FE Gap 143: the most specific matching item wins. "Settings" (/settings)
  // and "Subscriptions" (/settings/subscriptions) both prefix-match while the
  // subscriptions page is open, which would light up two nav items at once --
  // the longer href is the one the user is actually on.
  const activeHref = visibleItems
    .filter((item) => pathname === item.href || pathname.startsWith(item.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    // data-auth-loading exposes whether identity has resolved yet. The nav is
    // deliberately reduced to the 3 universal items while loading, so "only
    // Dashboard/Chat/Help are rendered" is ambiguous between "still loading"
    // and "permission-less user" -- e2e/rbac-sidebar.spec.ts waits on this
    // attribute to tell them apart instead of racing the fetch.
    <aside
      data-auth-loading={loading ? "true" : "false"}
      data-collapsed={collapsed ? "true" : "false"}
      className={`${
        collapsed ? "w-[76px]" : "w-64"
      } border-r border-[#222D3D] bg-[#0F172A]/40 backdrop-blur-md flex flex-col h-full text-slate-300 transition-all duration-200`}
    >
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 border-b border-[#222D3D] gap-3">
        <FileText className="w-6 h-6 text-accent-blue shrink-0" />
        {!collapsed && (
          <span className="font-semibold text-lg text-white tracking-wide truncate">Invoice AI</span>
        )}
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-4 py-6 space-y-1.5">
        {visibleItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.href === activeHref;

          return (
            <Link
              key={item.name}
              href={item.href}
              title={collapsed ? item.name : undefined}
              className={`flex items-center gap-3.5 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 hover:text-white hover:bg-[#1E293B]/50 ${
                collapsed ? "justify-center px-0" : ""
              } ${
                isActive
                  ? "bg-[#1E293B] text-white border-l-2 border-[#3B82F6] rounded-l-none"
                  : "text-slate-400"
              }`}
            >
              <Icon className={`w-5 h-5 shrink-0 ${isActive ? "text-[#3B82F6]" : "text-slate-400"}`} />
              {!collapsed && item.name}
            </Link>
          );
        })}
      </nav>

      {/* FE Gap 273: collapse toggle. */}
      <button
        type="button"
        onClick={toggleCollapsed}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="flex items-center justify-center gap-2 mx-3 mb-2 py-2 rounded-lg text-slate-500 transition-colors hover:bg-[#1E293B]/50 hover:text-white"
      >
        {collapsed ? (
          <ChevronsRight className="w-4 h-4" />
        ) : (
          <>
            <ChevronsLeft className="w-4 h-4" />
            <span className="text-xs">Collapse</span>
          </>
        )}
      </button>

      {/* Tenant Context Footer — Admin only (Gap 144) */}
      {role === "Admin" && !collapsed && (
        <div className="p-4 border-t border-[#222D3D] flex flex-col gap-1.5 text-xs text-slate-500 bg-[#070A13]/20">
          <span>Tenant Isolation ID:</span>
          <span className="font-mono text-[10px] text-slate-400 break-all select-all bg-[#0F172A]/50 p-1.5 rounded border border-[#222D3D]">
            {loading ? "…" : tenantId || "—"}
          </span>
        </div>
      )}
    </aside>
  );
}
