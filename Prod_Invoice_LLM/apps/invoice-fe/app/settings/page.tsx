"use client";

/**
 * Feature 10: Settings Page — /settings
 *
 * v1 renders the VendorFlowToggles section only.
 * Future sections (Connectors, Email Ingestion, Webhooks) will be added
 * as their respective features are implemented — no empty placeholders now.
 */

import React from "react";
import ServiceFlowToggles from "@/components/settings/ServiceFlowToggles";

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { Loader2 } from "lucide-react";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

export default function SettingsPage() {
  // FE Gap 110: this page used to render its own h-16 header bar below Shell's
  // global Header. Title and subtitle now go up to the one shared header.
  usePageHeader({
    title: "Settings",
    subtitle: "Configure your workspace integrations and features",
  });

  const { role, loading } = useAuth();
  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      {/* Content */}
      <main className="flex-1 px-6 py-8 max-w-2xl w-full mx-auto space-y-8">

        {/* Service Flow Section */}
        <section aria-labelledby="service-flow-heading">
          <div className="mb-4">
            <h2
              id="service-flow-heading"
              className="text-sm font-semibold text-white"
            >
              Service Flow
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
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

        {/* Divider — future sections will slot in here */}
        <hr className="border-[#1E293B]" />

        {/* Connectors Section */}
        <section aria-labelledby="connectors-heading">
          <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
            <div>
              <h2 id="connectors-heading" className="text-sm font-medium text-white">Connectors</h2>
              <p className="text-xs text-slate-400 mt-0.5">Google Drive & Salesforce folder mapping for imports and exports</p>
            </div>
            <Link
              href="/settings/connectors"
              className="px-4 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] border border-[#222D3D] text-white text-xs font-medium transition-colors whitespace-nowrap"
            >
              Configure
            </Link>
          </div>
        </section>

        {/* Email Ingestion & Delivery Section */}
        <section aria-labelledby="email-settings-heading">
          <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
            <div>
              <h2 id="email-settings-heading" className="text-sm font-medium text-white">Email Ingestion & Delivery</h2>
              <p className="text-xs text-slate-400 mt-0.5">Inbound alias and outbound sender configuration</p>
            </div>
            <Link
              href="/settings/email"
              className="px-4 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] border border-[#222D3D] text-white text-xs font-medium transition-colors whitespace-nowrap"
            >
              Configure
            </Link>
          </div>
        </section>

        {/* Admin Console Section */}
        <section aria-labelledby="admin-console-heading">
          <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
            <div>
              <h2 id="admin-console-heading" className="text-sm font-medium text-white">Admin Console</h2>
              <p className="text-xs text-slate-400 mt-0.5">Manage user permissions, roles, and view tenant stats</p>
            </div>
            <Link
              href="/admin"
              className="px-4 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] border border-[#222D3D] text-white text-xs font-medium transition-colors whitespace-nowrap"
            >
              Manage Org
            </Link>
          </div>
        </section>

        {/* Subscriptions & Billing Section */}
        <section aria-labelledby="subscriptions-heading">
          <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
            <div>
              <h2 id="subscriptions-heading" className="text-sm font-medium text-white">Subscriptions &amp; Billing</h2>
              <p className="text-xs text-slate-400 mt-0.5">Manage active plan limits, invoices cycle, and tier upgrades</p>
            </div>
            <Link
              href="/settings/subscriptions"
              className="px-4 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] border border-[#222D3D] text-white text-xs font-medium transition-colors whitespace-nowrap"
            >
              Configure
            </Link>
          </div>
        </section>

        {/* Webhooks Section */}
        <section aria-labelledby="webhooks-heading">
          <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
            <div>
              <h2 id="webhooks-heading" className="text-sm font-medium text-white">Developer Webhooks</h2>
              <p className="text-xs text-slate-400 mt-0.5">Register HTTP callback endpoints to receive real-time status updates</p>
            </div>
            <Link
              href="/settings/webhooks"
              className="px-4 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] border border-[#222D3D] text-white text-xs font-medium transition-colors whitespace-nowrap"
            >
              Configure
            </Link>
          </div>
        </section>


      </main>
    </div>
  );
}
