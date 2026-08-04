"use client";

/**
 * Feature 10: Settings Page — /settings
 *
 * v1 renders the VendorFlowToggles section only.
 * Future sections (Connectors, Email Ingestion, Webhooks) will be added
 * as their respective features are implemented — no empty placeholders now.
 */

import React from "react";
import { Settings2 } from "lucide-react";
import ServiceFlowToggles from "@/components/settings/ServiceFlowToggles";

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { Loader2 } from "lucide-react";

export default function SettingsPage() {
  const { role, loading } = useAuth();
  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      {/* Page Header */}
      <header className="h-16 border-b border-[#222D3D] bg-[#0F172A]/70 backdrop-blur-md px-6 flex items-center shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-slate-500/10 border border-slate-500/20 flex items-center justify-center text-slate-300">
            <Settings2 className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-white tracking-wide">Settings</h1>
            <p className="text-xs text-slate-400">Configure your workspace integrations and features</p>
          </div>
        </div>
      </header>

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

        {/* Coming-soon chips for the next sections */}
        {[
          { label: "Webhooks", description: "Event routing for invoice status changes" },
        ].map(({ label, description }) => (
          <section key={label} aria-label={label}>
            <div className="flex items-center justify-between px-5 py-4 rounded-xl bg-[#0D131F] border border-[#1A2437]">
              <div>
                <p className="text-sm font-medium text-slate-300">{label}</p>
                <p className="text-xs text-slate-500 mt-0.5">{description}</p>
              </div>
              <span className="text-[10px] px-2 py-1 rounded-full bg-[#1E293B] border border-[#2D3F55] text-slate-500 font-mono whitespace-nowrap">
                Coming soon
              </span>
            </div>
          </section>
        ))}


      </main>
    </div>
  );
}
