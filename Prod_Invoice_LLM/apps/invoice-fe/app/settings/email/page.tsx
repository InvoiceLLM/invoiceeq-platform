"use client";

/**
 * Feature 8 — Inbound/Outbound Email settings subpage
 *
 * Configures the inbound allowed senders, lists alias copyable values,
 * and manages custom outbound delivery email settings.
 */

import React, { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Mail, Copy, Check, Info } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import EmailSendersList from "@/components/settings/EmailSendersList";
import OutboundEmailSettings from "@/components/settings/OutboundEmailSettings";

export default function EmailSettingsPage() {
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
      {/* Header */}
      <header className="h-16 border-b border-[#222D3D] bg-[#0F172A]/70 backdrop-blur-md px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href="/settings"
            className="w-9 h-9 rounded-xl bg-slate-500/10 border border-slate-500/20 flex items-center justify-center text-slate-300 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-base font-semibold text-white tracking-wide">Email Ingestion & Delivery</h1>
            <p className="text-xs text-slate-400">Configure email-in invoice triggers and outbound delivery senders</p>
          </div>
        </div>
      </header>

      {/* Content Grid */}
      <main className="flex-1 px-6 py-8 max-w-2xl w-full mx-auto space-y-8">
        
        {/* Inbound Alias display card */}
        <section aria-labelledby="inbound-alias-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <h2 id="inbound-alias-heading" className="text-sm font-semibold text-white">Your Inbound Ingestion Address</h2>
              <p className="text-xs text-slate-400">
                Forward supplier or contractor invoice PDFs directly to this unique email address.
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

        {/* Allowed Inbound Senders */}
        <section aria-labelledby="senders-heading">
          <EmailSendersList isAdmin={isAdmin} />
        </section>

        {/* Outbound Delivery Configuration */}
        <section aria-labelledby="outbound-heading">
          <OutboundEmailSettings isAdmin={isAdmin} />
        </section>
      </main>
    </div>
  );
}
