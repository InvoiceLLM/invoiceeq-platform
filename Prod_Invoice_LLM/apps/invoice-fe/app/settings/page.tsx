"use client";

/**
 * Feature 10: Settings Page — /settings
 *
 * Gap 114: Realigned layout — three compact service-flow tiles in a single row,
 * integrations in a 3×2 grid below, all fitting on one laptop viewport without scroll.
 */

import React from "react";
import ServiceFlowToggles from "@/components/settings/ServiceFlowToggles";

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import {
  Loader2,
  FolderSync,
  Mail,
  ShieldCheck,
  CreditCard,
  Webhook,
  UserCog,
} from "lucide-react";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

/**
 * FE Gap 167: `adminOnly` exists because the Admin Console tile used to render
 * for every role — the only tile on this page with no gate at all, while
 * ServiceFlowToggles and the Webhooks/Security screens behind the other tiles
 * all resolve `role === "Admin"` from `useAuth()`. A Viewer who followed it hit
 * `/admin`, whose own list call 403s, and was then shown a page labelling them
 * the organisation's Admin. The route itself now refuses non-Admins too (see
 * `app/admin/page.tsx`); hiding the tile is the discoverability half of that.
 */
interface IntegrationTile {
  id: string;
  title: string;
  desc: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  iconBg: string;
  iconColor: string;
  /** Hidden from anyone whose resolved role is not "Admin". */
  adminOnly?: boolean;
}

const INTEGRATIONS: IntegrationTile[] = [
  {
    id: "connectors",
    title: "Connectors",
    desc: "Google Drive folder mapping",
    href: "/settings/connectors",
    icon: FolderSync,
    iconBg: "bg-cyan-500/10 border-cyan-500/20",
    iconColor: "text-cyan-400",
  },
  {
    id: "email",
    title: "Email Setup",
    desc: "App mailbox & inbound/outbound authorized sets",
    href: "/settings/email",
    icon: Mail,
    iconBg: "bg-amber-500/10 border-amber-500/20",
    iconColor: "text-amber-400",
  },
  {
    id: "admin",
    title: "Admin Console",
    desc: "User permissions, roles & tenant stats",
    href: "/admin",
    icon: UserCog,
    iconBg: "bg-rose-500/10 border-rose-500/20",
    iconColor: "text-rose-400",
    adminOnly: true,
  },
  {
    id: "subscriptions",
    title: "Subscriptions",
    desc: "Plan limits, billing cycle & upgrades",
    href: "/settings/subscriptions",
    icon: CreditCard,
    iconBg: "bg-blue-500/10 border-blue-500/20",
    iconColor: "text-blue-400",
  },
  {
    id: "webhooks",
    title: "Webhooks",
    desc: "HTTP callback endpoints for status updates",
    href: "/settings/webhooks",
    icon: Webhook,
    iconBg: "bg-violet-500/10 border-violet-500/20",
    iconColor: "text-violet-400",
  },
  {
    id: "security",
    title: "Security",
    desc: "API keys, audit logs & access control",
    href: "/settings/security",
    icon: ShieldCheck,
    iconBg: "bg-emerald-500/10 border-emerald-500/20",
    iconColor: "text-emerald-400",
  },
];

export default function SettingsPage() {
  // FE Gap 110: this page used to render its own h-16 header bar below Shell's
  // global Header. Title and subtitle now go up to the one shared header.
  usePageHeader({
    title: "Settings",
    subtitle: "Configure your workspace integrations and features",
  });

  const { role, loading } = useAuth();
  // FE Gap 167: same resolution every other gated Settings screen uses
  // (`app/settings/webhooks/page.tsx`, `ServiceFlowToggles`) — the real role
  // from GET /auth/me, never Clerk's client-editable metadata. While identity
  // is still loading `role` is "", so admin-only tiles stay hidden rather than
  // flashing in and disappearing.
  const isAdmin = role === "Admin";
  const visibleIntegrations = INTEGRATIONS.filter((item) => !item.adminOnly || isAdmin);

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      {/* Content */}
      <main className="flex-1 px-6 py-6 max-w-5xl w-full mx-auto space-y-6">

        {/* Service Flow Section — Gap 114: compact row of 3 tiles */}
        <section aria-labelledby="service-flow-heading">
          <div className="mb-3">
            <h2
              id="service-flow-heading"
              className="text-xs font-semibold uppercase tracking-wider text-slate-500"
            >
              Service Flow
            </h2>
            <p className="text-[11px] text-slate-500 mt-0.5">
              Control which invoice directions are active for your workspace.
            </p>
          </div>

          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
            </div>
          ) : (
            <ServiceFlowToggles role={role} />
          )}
        </section>

        {/* Divider */}
        <hr className="border-[#1E293B]" />

        {/* Integrations — Gap 114: 3×2 compact grid */}
        <section aria-labelledby="integrations-heading">
          <h2
            id="integrations-heading"
            className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3"
          >
            Integrations & Management
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {visibleIntegrations.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className="group flex items-start gap-3 px-4 py-3.5 rounded-xl bg-[#111827] border border-[#1E293B] hover:border-[#334155] hover:bg-[#151D2E] transition-all"
                >
                  <div
                    className={`w-8 h-8 rounded-lg border flex items-center justify-center shrink-0 ${item.iconBg}`}
                  >
                    <Icon className={`w-4 h-4 ${item.iconColor}`} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white group-hover:text-blue-200 transition-colors">
                      {item.title}
                    </p>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-tight">
                      {item.desc}
                    </p>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>

      </main>
    </div>
  );
}
