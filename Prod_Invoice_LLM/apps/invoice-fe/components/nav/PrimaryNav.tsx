// =============================================================================
// FILE: components/nav/PrimaryNav.tsx
// FEATURE: FE Feature 22 Task 22.1 — the four surfaces: Today / Ask / Records /
//          Settings, sorted by what the user is doing rather than by which
//          feature built the screen (spec §1).
//
// WHY THIS FILE EXISTS: it replaces `Sidebar.tsx`'s ten items when the four
// surfaces are switched on (`lib/navigation.ts::fourSurfacesEnabled`). The
// Sidebar is NOT deleted — Task 22.21's classic layout renders it, plus Today.
//
// ROLE MODEL (spec §2 row 1): only Settings is gated, on Admin, exactly as the
// Sidebar gates it. Today / Ask / Records are universal because each surface
// shows only what the server sends that role — the nav does not second-guess
// the backend's clearance filter. So an Auditor sees 3 items, an Admin 4.
//
// Same visual shell and same `data-auth-loading` contract as Sidebar.tsx, so
// e2e specs can wait on identity the same way (e2e/rbac-sidebar.spec.ts).
// =============================================================================
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileText, FolderOpen, MessageSquare, Settings, Sun } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { activeNavHref } from "@/lib/navigation";

export default function PrimaryNav() {
  const pathname = usePathname() ?? "";
  const { role, loading } = useAuth();

  const menuItems = [
    { name: "Today", href: "/today", icon: Sun, visible: true },
    { name: "Ask", href: "/ask", icon: MessageSquare, visible: true },
    { name: "Records", href: "/records", icon: FolderOpen, visible: true },
    { name: "Settings", href: "/settings", icon: Settings, visible: role === "Admin" },
  ];

  // While identity is in flight, Settings stays hidden rather than flashing at
  // a user who may not be an Admin — the Sidebar's rule, for the same reason.
  const visibleItems = menuItems.filter((item) => (loading ? item.href !== "/settings" : item.visible));
  const activeHref = activeNavHref(visibleItems, pathname);

  return (
    <aside
      aria-label="Primary"
      data-auth-loading={loading ? "true" : "false"}
      className="w-64 border-r border-[#222D3D] bg-[#0F172A]/40 backdrop-blur-md flex flex-col h-full text-slate-300"
    >
      <div className="h-16 flex items-center px-6 border-b border-[#222D3D] gap-3">
        <FileText className="w-6 h-6 text-accent-blue shrink-0" />
        <span className="font-semibold text-lg text-white tracking-wide truncate">Invoice AI</span>
      </div>

      <nav className="flex-1 px-4 py-6 space-y-1.5">
        {visibleItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.href === activeHref;

          return (
            <Link
              key={item.name}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={`flex items-center gap-3.5 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 hover:text-white hover:bg-[#1E293B]/50 ${
                isActive ? "bg-[#1E293B] text-white border-l-2 border-[#3B82F6] rounded-l-none" : "text-slate-400"
              }`}
            >
              <Icon className={`w-5 h-5 shrink-0 ${isActive ? "text-[#3B82F6]" : "text-slate-400"}`} />
              {item.name}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
