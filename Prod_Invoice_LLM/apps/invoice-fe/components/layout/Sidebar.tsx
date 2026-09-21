"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  UploadCloud,
  History,
  MessageSquare,
  GraduationCap,
  ScrollText,
  FileText,
  ListChecks,
  ChevronsLeft,
  ChevronsRight,
  Settings,
  CreditCard,
  HelpCircle,
  LogOut,
  ChevronUp,
  ChevronDown,
  Copy,
  Check,
} from "lucide-react";
import { useClerk, useUser } from "@clerk/nextjs";
import { useAuth, clearAuth } from "../../hooks/useAuth";

// FE Gap 273: persisted so the collapsed/expanded choice survives a reload.
const SIDEBAR_COLLAPSED_KEY = "sidebar-collapsed";

const WEBSITE_URL = process.env.NEXT_PUBLIC_WEBSITE_URL || "http://localhost:3000";

/**
 * FE Gap 116 — who is actually signed in.
 * Derives user name, initials, and email cleanly without mock fallback.
 */
function useDisplayIdentity() {
  const { user, isLoaded } = useUser();

  const email = user?.primaryEmailAddress?.emailAddress ?? "";
  const first = user?.firstName?.trim() ?? "";
  const last = user?.lastName?.trim() ?? "";

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

export default function Sidebar() {
  const pathname = usePathname();
  // Permissions & identity from GET /api/auth/me
  const { tenantId, role, tenantName, canTrain, canAudit, canLoad, loading } = useAuth();
  const { isLoaded, email: userEmail, name: displayName, initials } = useDisplayIdentity();
  const { user } = useUser();
  const { signOut } = useClerk();

  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [copied, setCopied] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  // FE Gap 273: collapses to an icon-only rail so the main content area gets more room.
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

  // Close profile menu on route change
  useEffect(() => {
    setShowProfileMenu(false);
  }, [pathname]);

  // Close profile menu on outside click
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

  const handleCopyTenantId = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (tenantId) {
      navigator.clipboard.writeText(tenantId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleSignOut = async () => {
    setShowProfileMenu(false);
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
        console.warn("Backend logout failed (non-blocking):", backendErr);
      }

      await signOut({ redirectUrl: `${WEBSITE_URL}/login` });
      return;
    } catch (err) {
      console.error("Sign out error", err);
    }

    window.location.href = `${WEBSITE_URL}/login`;
  };

  // Streamlined primary navigation items:
  // Settings, Subscriptions (Upgrade Plan), and Help are now housed under the
  // bottom-left Profile Popover (like ChatGPT & Claude), keeping the main nav
  // uncluttered and dedicated to core workflows.
  const menuItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard, visible: true },
    { name: "Ingest", href: "/ingestion", icon: UploadCloud, visible: canLoad },
    { name: "Audit Queue", href: "/invoices", icon: ListChecks, visible: canAudit },
    { name: "History", href: "/history", icon: History, visible: canAudit },
    { name: "AI Trainer", href: "/trainer", icon: GraduationCap, visible: canTrain },
    { name: "Chat Rules", href: "/settings/chat-rules", icon: ScrollText, visible: canTrain },
    { name: "Chat", href: "/chat", icon: MessageSquare, visible: true },
  ];

  // While identity is still in flight, show only the core universal items.
  const visibleItems = menuItems.filter((item) =>
    loading ? item.href === "/dashboard" || item.href === "/chat" : item.visible
  );

  const activeHref = visibleItems
    .filter((item) => pathname === item.href || pathname.startsWith(item.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  const orgName = loading
    ? (user?.unsafeMetadata?.orgName as string) || ""
    : tenantName || "";
  const orgLine = [orgName, !loading && role ? `(${role})` : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <aside
      data-auth-loading={loading ? "true" : "false"}
      data-collapsed={collapsed ? "true" : "false"}
      className={`${
        collapsed ? "w-[76px]" : "w-64"
      } border-r border-[#222D3D] bg-[#0F172A]/40 backdrop-blur-md flex flex-col h-full text-slate-300 transition-[width] duration-200 relative z-40`}
    >
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 border-b border-[#222D3D] gap-3">
        <FileText className="w-6 h-6 text-accent-blue shrink-0" />
        {!collapsed && (
          <span className="font-semibold text-lg text-white tracking-wide truncate">Invoice AI</span>
        )}
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-4 py-6 space-y-1.5 overflow-y-auto">
        {visibleItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.href === activeHref;

          return (
            <Link
              key={item.name}
              href={item.href}
              title={collapsed ? item.name : undefined}
              className={`flex items-center gap-3.5 px-4 py-3 rounded-lg text-sm font-medium transition-colors duration-200 hover:text-white hover:bg-[#1E293B]/50 ${
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

      {/* Collapse toggle */}
      <button
        type="button"
        onClick={toggleCollapsed}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="flex items-center justify-center gap-2 mx-3 mb-2 py-2 rounded-lg text-slate-500 transition-colors hover:bg-[#1E293B]/50 hover:text-white cursor-pointer"
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

      {/* User Profile Pill & Upward Popover Menu (ChatGPT & Claude Style) */}
      <div className="p-3 border-t border-[#222D3D] relative" ref={profileMenuRef}>
        {/* Profile Pill Button */}
        <button
          type="button"
          onClick={() => setShowProfileMenu((prev) => !prev)}
          className={`w-full flex items-center gap-3 p-2 rounded-xl hover:bg-[#1E293B]/60 transition-all duration-200 group text-left select-none cursor-pointer ${
            showProfileMenu ? "bg-[#1E293B]/80 ring-1 ring-[#3B82F6]/50" : ""
          } ${collapsed ? "justify-center px-0" : ""}`}
          title={collapsed ? displayName || "User Profile" : undefined}
          aria-expanded={showProfileMenu}
          aria-label="User Profile and Account Menu"
        >
          {/* Avatar */}
          <div className="w-8 h-8 rounded-full bg-[#3B82F6]/10 border border-[#3B82F6]/30 flex items-center justify-center text-[#3B82F6] text-xs font-semibold shrink-0 overflow-hidden">
            {isLoaded ? (
              user?.imageUrl ? (
                <img
                  src={user.imageUrl}
                  alt={displayName || "Profile"}
                  className="w-full h-full object-cover"
                  referrerPolicy="no-referrer"
                />
              ) : (
                initials
              )
            ) : (
              <span className="w-4 h-4 rounded bg-slate-600/40 animate-pulse" />
            )}
          </div>

          {/* Name & Role (hidden if collapsed) */}
          {!collapsed && (
            <div className="min-w-0 flex-1">
              {isLoaded ? (
                <>
                  <p className="text-xs font-semibold text-white truncate group-hover:text-white">
                    {displayName || "User"}
                  </p>
                  <p className="text-[11px] text-slate-400 truncate mt-0.5">
                    {orgLine || "Workspace"}
                  </p>
                </>
              ) : (
                <>
                  <span className="block w-20 h-3 rounded bg-slate-600/40 animate-pulse" />
                  <span className="block w-14 h-2 rounded bg-slate-700/40 animate-pulse mt-1" />
                </>
              )}
            </div>
          )}

          {/* Chevron icon (hidden if collapsed) */}
          {!collapsed && (
            showProfileMenu ? (
              <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-slate-200 shrink-0 transition-colors" />
            ) : (
              <ChevronUp className="w-4 h-4 text-slate-500 group-hover:text-slate-300 shrink-0 transition-colors" />
            )
          )}
        </button>

        {/* Upward Popover Menu */}
        {showProfileMenu && (
          <div
            className={`absolute bottom-full mb-2 bg-[#0F172A] border border-[#222D3D] rounded-xl shadow-2xl p-2 z-50 animate-in fade-in slide-in-from-bottom-2 duration-150 backdrop-blur-md ${
              collapsed ? "left-2 w-64" : "left-3 right-3"
            }`}
          >
            {/* Signed in as header */}
            <div className="px-3 py-2 border-b border-[#222D3D] mb-1">
              <p className="text-[11px] font-medium text-slate-400">Signed in as</p>
              <p className="text-xs font-semibold text-white truncate mt-0.5">
                {userEmail || (isLoaded ? "—" : "…")}
              </p>
              <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded bg-[#1E293B] text-slate-300 border border-[#222D3D] font-medium">
                {role || "Admin"}
              </span>
            </div>

            {/* Settings */}
            <Link
              href="/settings"
              onClick={() => setShowProfileMenu(false)}
              className="w-full flex items-center gap-3 px-3 py-2 text-xs font-medium text-slate-300 hover:bg-[#1E293B]/70 hover:text-white rounded-lg transition-colors text-left"
            >
              <Settings className="w-4 h-4 text-slate-400" />
              Settings
            </Link>

            {/* Upgrade Plan */}
            <Link
              href="/settings/subscriptions"
              onClick={() => setShowProfileMenu(false)}
              className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-slate-300 hover:bg-[#1E293B]/70 hover:text-white rounded-lg transition-colors text-left"
            >
              <div className="flex items-center gap-3">
                <CreditCard className="w-4 h-4 text-slate-400" />
                <span>Upgrade Plan</span>
              </div>
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-[#3B82F6]/20 text-[#60A5FA] border border-[#3B82F6]/30">
                {role === "Admin" ? "Active" : "Pro"}
              </span>
            </Link>

            {/* Help */}
            <Link
              href="/help"
              onClick={() => setShowProfileMenu(false)}
              className="w-full flex items-center gap-3 px-3 py-2 text-xs font-medium text-slate-300 hover:bg-[#1E293B]/70 hover:text-white rounded-lg transition-colors text-left"
            >
              <HelpCircle className="w-4 h-4 text-slate-400" />
              Help
            </Link>

            {/* Tenant Isolation ID */}
            <div className="px-3 py-2 bg-[#070A13]/40 border border-[#222D3D] rounded-lg my-1.5">
              <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
                <span>Tenant Isolation ID</span>
                <button
                  type="button"
                  onClick={handleCopyTenantId}
                  className="hover:text-white flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
                  title="Copy Tenant ID"
                >
                  {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>{copied ? "Copied" : "Copy"}</span>
                </button>
              </div>
              <span className="font-mono text-[10px] text-slate-300 break-all select-all block">
                {loading ? "…" : tenantId || "—"}
              </span>
            </div>

            <div className="h-px bg-[#222D3D] my-1"></div>

            {/* Sign Out */}
            <button
              type="button"
              onClick={handleSignOut}
              className="w-full flex items-center gap-3 px-3 py-2 text-xs font-medium text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 rounded-lg transition-colors text-left cursor-pointer"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
