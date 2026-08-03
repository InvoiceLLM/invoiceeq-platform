"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  UploadCloud,
  MessageSquare,
  GraduationCap,
  Settings,
  HelpCircle,
  FileText,
  ListChecks
} from "lucide-react";
import { useAuth } from "../../hooks/useAuth";

export default function Sidebar() {
  const pathname = usePathname();
  // FE Gap 99 / Feature 1.1 Task 1.1.5: real permissions, from GET /auth/me.
  // Until this landed, useAuth() was a localStorage mock that made everyone an
  // Admin, and this list rendered unconditionally -- every user saw every item.
  const { tenantId, role, canTrain, canAudit, canLoad, loading } = useAuth();

  // Navigation items definition for the primary sidebar.
  // `visible` implements feature_1.1_rbac.md's access model:
  //   Dashboard / Chat / Help  -> every signed-in user
  //   Ingest                   -> can_load
  //   Audit Queue              -> can_audit
  //   AI Trainer               -> can_train
  //   Settings                 -> Admin only
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
    // AI Trainer link for rule scope fine-tuning & sandbox evaluation (Feature 6)
    { name: "AI Trainer", href: "/trainer", icon: GraduationCap, visible: canTrain },
    { name: "Chat", href: "/chat", icon: MessageSquare, visible: true },
    { name: "Settings", href: "/settings", icon: Settings, visible: role === "Admin" },
    { name: "Help", href: "/help", icon: HelpCircle, visible: true },
  ];

  // While identity is still in flight, show only the three universal items.
  // Rendering the full list optimistically would flash Trainer/Audit/Settings
  // at users who are not allowed to see them.
  const visibleItems = menuItems.filter((item) =>
    loading ? item.href === "/dashboard" || item.href === "/chat" || item.href === "/help" : item.visible
  );

  return (
    // data-auth-loading exposes whether identity has resolved yet. The nav is
    // deliberately reduced to the 3 universal items while loading, so "only
    // Dashboard/Chat/Help are rendered" is ambiguous between "still loading"
    // and "permission-less user" -- e2e/rbac-sidebar.spec.ts waits on this
    // attribute to tell them apart instead of racing the fetch.
    <aside
      data-auth-loading={loading ? "true" : "false"}
      className="w-64 border-r border-[#222D3D] bg-[#0F172A]/40 backdrop-blur-md flex flex-col h-full text-slate-300"
    >
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 border-b border-[#222D3D] gap-3">
        <FileText className="w-6 h-6 text-accent-blue" />
        <span className="font-semibold text-lg text-white tracking-wide">Invoice AI</span>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-4 py-6 space-y-1.5">
        {visibleItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");

          return (
            <Link
              key={item.name}
              href={item.href}
              className={`flex items-center gap-3.5 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 hover:text-white hover:bg-[#1E293B]/50 ${
                isActive 
                  ? "bg-[#1E293B] text-white border-l-2 border-[#3B82F6] rounded-l-none" 
                  : "text-slate-400"
              }`}
            >
              <Icon className={`w-5 h-5 ${isActive ? "text-[#3B82F6]" : "text-slate-400"}`} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Tenant Context Footer */}
      <div className="p-4 border-t border-[#222D3D] flex flex-col gap-1.5 text-xs text-slate-500 bg-[#070A13]/20">
        <span>Tenant Isolation ID:</span>
        {/* Was the hardcoded all-zeroes mock UUID -- the same fabricated
            identity Gap 99 is about, displayed as if it were real. Now the
            actual tenant_id from GET /auth/me. */}
        <span className="font-mono text-[10px] text-slate-400 break-all select-all bg-[#0F172A]/50 p-1.5 rounded border border-[#222D3D]">
          {loading ? "…" : tenantId || "—"}
        </span>
      </div>
    </aside>
  );
}
