"use client";

/**
 * Feature 8 — Email Setup: one app mailbox + inbound/outbound authorized sets.
 */

import React, { useEffect, useState } from "react";
import { Mail, Copy, Check, Info } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import EmailSendersList from "@/components/settings/EmailSendersList";

export default function EmailSettingsPage() {
  usePageHeader({
    title: "Email Setup",
    subtitle: "Global mailbox; inbound and outbound authorized sets",
    backHref: "/settings",
  });

  const { role } = useAuth();
  const isAdmin = role === "Admin";
  const [copied, setCopied] = useState(false);
  const [mailbox, setMailbox] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/email/settings/mailbox");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setMailbox(data.mailbox || "");
          return;
        }
      } catch {
        /* fall through */
      }
      if (!cancelled) {
        setMailbox("invoices@invoiceeq.app");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCopy = () => {
    if (!mailbox || typeof window === "undefined") return;
    navigator.clipboard.writeText(mailbox);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      <main className="flex-1 px-6 py-5 max-w-5xl w-full mx-auto space-y-4">
        <section className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-4 space-y-3 shadow-lg">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-0.5 min-w-0">
              <h2 className="text-sm font-semibold text-white">App mailbox (shared)</h2>
              <p className="text-[11px] text-slate-400">
                One platform address for every workspace. Your tenant is identified by which authorized email sends the message.
              </p>
            </div>
            <div className="w-8 h-8 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shrink-0">
              <Mail className="w-4 h-4" />
            </div>
          </div>

          <div className="flex items-center gap-2 bg-[#0B0F19] border border-[#222D3D] rounded-xl p-2.5 pl-3 select-all">
            <span className="font-mono text-xs text-slate-200 truncate flex-1 leading-none">
              {mailbox || "Loading…"}
            </span>
            <button
              onClick={handleCopy}
              disabled={!mailbox}
              className="p-1.5 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all flex items-center justify-center shrink-0 disabled:opacity-40"
              title="Copy to clipboard"
              aria-label="Copy mailbox"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          <div className="flex items-start gap-2 text-[11px] text-slate-400">
            <Info className="w-3.5 h-3.5 shrink-0 mt-0.5 text-slate-500" />
            <span>
              Inbound set = AP emails sending vendor invoices. Outbound set = AR emails sending your own invoices for audit.
            </span>
          </div>
        </section>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
          <section className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-4 shadow-lg">
            <EmailSendersList
              isAdmin={isAdmin}
              emailSet="inbound"
              title="Inbound authorized emails"
              subtitle="AP team — vendor invoices into the app"
              placeholder="ap@yourcompany.com"
            />
          </section>
          <section className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-4 shadow-lg">
            <EmailSendersList
              isAdmin={isAdmin}
              emailSet="outbound"
              title="Outbound authorized emails"
              subtitle="AR team — your invoices for audit"
              placeholder="ar@yourcompany.com"
            />
          </section>
        </div>
      </main>
    </div>
  );
}
