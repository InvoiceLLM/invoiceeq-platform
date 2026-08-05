"use client";

/**
 * Feature 8 — Inbound/Outbound Email settings subpage
 *
 * Configures the inbound allowed senders, lists alias copyable values,
 * and manages custom outbound delivery email settings.
 */

import React, { useState } from "react";
import { Mail, Copy, Check, Info } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import EmailSendersList from "@/components/settings/EmailSendersList";
import OutboundEmailSettings from "@/components/settings/OutboundEmailSettings";

export default function EmailSettingsPage() {
  // FE Gap 110: own h-16 header bar replaced by the shared one; its back arrow
  // becomes the header's backHref.
  usePageHeader({
    title: "Email Ingestion & Delivery",
    subtitle: "Configure email-in invoice triggers and outbound delivery senders",
    backHref: "/settings",
  });

  const { tenantId, role } = useAuth();
  const isAdmin = role === "Admin";
  const [copied, setCopied] = useState(false);

  // Platform receiving domain
  const platformDomain = "invoice-ai.com";
  const inboundAlias = `${tenantId}@invoices.${platformDomain}`;

  const handleCopy = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard.writeText(inboundAlias);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      {/* Content Grid */}
      <main className="flex-1 px-6 py-8 max-w-4xl w-full mx-auto space-y-6">

        {/* Inbound address + Outbound target address, side by side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
          {/* Inbound Alias display card */}
          <section aria-labelledby="inbound-alias-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-4 space-y-3.5 shadow-lg h-full">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1 min-w-0">
                <h2 id="inbound-alias-heading" className="text-sm font-semibold text-white">Your Inbound Ingestion Address</h2>
                <p className="text-[11px] text-slate-400">
                  Forward supplier or contractor invoice PDFs to this address.
                </p>
              </div>
              <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shrink-0">
                <Mail className="w-4.5 h-4.5" />
              </div>
            </div>

            <div className="flex items-center gap-3 bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 pl-4 select-all">
              <span className="font-mono text-xs text-slate-200 truncate flex-1 leading-none">{inboundAlias}</span>
              <button
                onClick={handleCopy}
                className="p-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all flex items-center justify-center shrink-0"
                title="Copy to clipboard"
                aria-label="Copy to clipboard"
              >
                {copied ? (
                  <Check className="w-4 h-4 text-emerald-400" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            </div>

            <div className="flex items-start gap-2.5 bg-blue-500/5 border border-blue-500/10 rounded-xl p-3 text-[11px] text-blue-300">
              <Info className="w-4 h-4 shrink-0 text-blue-400 mt-0.5" />
              <span>
                Emails are matched against your allowlist rules. Only approved senders can upload document attachments.
              </span>
            </div>
          </section>

          {/* Outbound Delivery Configuration */}
          <section aria-labelledby="outbound-heading" className="h-full">
            <OutboundEmailSettings isAdmin={isAdmin} />
          </section>
        </div>

        {/* Allowed Inbound Senders */}
        <section aria-labelledby="senders-heading">
          <EmailSendersList isAdmin={isAdmin} />
        </section>
      </main>
    </div>
  );
}
