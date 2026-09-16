"use client";

// =============================================================================
// FILE: components/settings/SettingsSections.tsx
// FEATURE: FE Feature 22 Task 22.3 — Settings as one scrolling page:
//          People / Inbox / Checks / Notify / Plan / Security (spec §3.4).
//
// A RE-LAYOUT, NOT A REWRITE. Every section mounts the existing screen's own
// page component, unchanged, inside <EmbeddedPage> — which stops each one from
// taking over the shared header title (components/layout/PageHeaderContext.tsx).
// The old routes redirect here to their `#section` anchor (lib/navigation.ts).
//
// WHERE EACH SCREEN WENT (founder to confirm — plan §6):
//   People   <- /admin                    (users, roles, permissions)
//   Inbox    <- Service Flow toggles (was on /settings) + /settings/email
//               + /settings/connectors
//   Checks   <- /settings/workflows (its core is the audit policy; the wizard
//               also sets inputs, outputs and chat access) + a link to
//               /settings/chat-rules, which keeps its own page (FE Gap 478)
//   Notify   <- /settings/webhooks
//   Plan     <- /settings/subscriptions
//   Security <- /settings/security
//
// `/settings/connectors` is mounted here but is NOT redirected: it is the
// backend's Google OAuth return URL (invoice-be routers/connectors.py:249),
// rendered inside the consent popup, which it closes itself.
// =============================================================================

import React, { Suspense, useRef } from "react";
import Link from "next/link";
import { Loader2, MessageSquareQuote } from "lucide-react";
import { EmbeddedPage, usePageHeader } from "@/components/layout/PageHeaderContext";
import LayoutPreference from "@/components/settings/LayoutPreference";
import ServiceFlowToggles from "@/components/settings/ServiceFlowToggles";
import { useAuth } from "@/hooks/useAuth";
import { useHashScroll } from "@/hooks/useHashScroll";
import AdminDashboardPage from "@/app/admin/page";
import EmailSettingsPage from "@/app/settings/email/page";
import ConnectorsPage from "@/app/settings/connectors/page";
import WorkflowSettingsPage from "@/app/settings/workflows/page";
import WebhooksPage from "@/app/settings/webhooks/page";
import SubscriptionsPage from "@/app/settings/subscriptions/page";
import SecuritySettingsPage from "@/app/settings/security/page";

function ServiceFlowBlock() {
  const { role, loading } = useAuth();
  return (
    <div className="px-6 pt-5">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Service Flow</h3>
      <p className="mb-3 mt-0.5 text-[11px] text-slate-500">Control which invoice directions are active for your workspace.</p>
      {loading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      ) : (
        <ServiceFlowToggles role={role} />
      )}
    </div>
  );
}

function ChatRulesLink() {
  return (
    <div className="px-6 pb-6">
      <Link
        href="/settings/chat-rules"
        className="group flex items-start gap-3 rounded-xl border border-[#1E293B] bg-[#111827] px-4 py-3.5 transition-all hover:border-[#334155] hover:bg-[#151D2E]"
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/10">
          <MessageSquareQuote className="h-4 w-4 text-sky-400" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium text-white transition-colors group-hover:text-blue-200">Chat Rules</p>
          <p className="mt-0.5 text-[11px] leading-tight text-slate-500">
            Answering rules taught from chat feedback — review &amp; remove
          </p>
        </div>
      </Link>
    </div>
  );
}

export const SETTINGS_SECTIONS: readonly { id: string; title: string; description: string; body: React.ReactNode }[] = [
  {
    id: "people",
    title: "People",
    description: "Users, roles and permissions",
    body: <AdminDashboardPage />,
  },
  {
    id: "inbox",
    title: "Inbox",
    description: "Which invoice directions are on, and how documents arrive",
    body: (
      <>
        <ServiceFlowBlock />
        <EmailSettingsPage />
        {/* useSearchParams inside: a Suspense boundary keeps it from bailing the whole page out of static rendering. */}
        <Suspense fallback={null}>
          <ConnectorsPage />
        </Suspense>
      </>
    ),
  },
  {
    id: "checks",
    title: "Checks",
    description: "How invoices are audited, and the answering rules taught from chat",
    body: (
      <>
        <WorkflowSettingsPage />
        <ChatRulesLink />
      </>
    ),
  },
  {
    id: "notify",
    title: "Notify",
    description: "Webhook callbacks for invoice status updates",
    body: <WebhooksPage />,
  },
  {
    id: "plan",
    title: "Plan",
    description: "Plan limits, billing cycle and upgrades",
    body: <SubscriptionsPage />,
  },
  {
    id: "security",
    title: "Security",
    description: "API keys, widget tokens and audit logs",
    body: <SecuritySettingsPage />,
  },
];

export default function SettingsSections() {
  usePageHeader({
    title: "Settings",
    subtitle: "Configure your workspace integrations and features",
  });

  const containerRef = useRef<HTMLDivElement>(null);
  useHashScroll(containerRef);

  return (
    <div ref={containerRef} className="mx-auto w-full max-w-5xl space-y-6 pb-16">
      {/* 22.21: the Settings-side mirror of the header's classic-layout switch. */}
      <LayoutPreference variant="settings" />

      <nav aria-label="Settings sections" className="flex flex-wrap gap-1 rounded-lg border border-[#222D3D] bg-[#0B0F19] p-1">
        {SETTINGS_SECTIONS.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-[#1E293B] hover:text-white"
          >
            {section.title}
          </a>
        ))}
      </nav>

      {SETTINGS_SECTIONS.map((section) => (
        <section
          key={section.id}
          id={section.id}
          aria-labelledby={`${section.id}-heading`}
          className="scroll-mt-4 overflow-hidden rounded-xl border border-[#1E293B] bg-[#0B0F19]"
        >
          <header className="border-b border-[#1E293B] px-6 py-4">
            <h2 id={`${section.id}-heading`} className="text-sm font-semibold text-white">
              {section.title}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">{section.description}</p>
          </header>
          <EmbeddedPage>{section.body}</EmbeddedPage>
        </section>
      ))}
    </div>
  );
}
