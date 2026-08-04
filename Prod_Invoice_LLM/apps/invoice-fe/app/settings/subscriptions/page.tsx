"use client";

import React from "react";
import Link from "next/link";
import { ArrowLeft, CreditCard, CheckCircle2, ShieldCheck, Sparkles, AlertTriangle } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

const WEBSITE_URL = process.env.NEXT_PUBLIC_WEBSITE_URL || "http://localhost:3000";

export default function SubscriptionsPage() {
  const { role, billingPlan, loading } = useAuth();
  const isAdmin = role === "Admin";

  const isProCombined = billingPlan === "pro_combined" || billingPlan === "active";
  const isPro = billingPlan === "pro";
  const isFree = !isPro && !isProCombined;

  const getPlanName = () => {
    if (loading) return "Loading...";
    if (isProCombined) return "Pro Combined Plan";
    if (isPro) return "Pro Plan";
    return "Free Plan";
  };

  const getPlanPrice = () => {
    if (isProCombined) return "₹8,999 / month";
    if (isPro) return "₹4,999 / month";
    return "₹0 / month";
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
            <h1 className="text-base font-semibold text-white tracking-wide">Subscriptions &amp; Billing</h1>
            <p className="text-xs text-slate-400">Manage your workspace pricing tier and limits</p>
          </div>
        </div>
      </header>

      {/* Content Grid */}
      <main className="flex-1 px-6 py-8 max-w-2xl w-full mx-auto space-y-6">
        {/* Current Plan Overview */}
        <section aria-labelledby="current-plan-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-6 space-y-4 shadow-lg relative overflow-hidden">
          <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/5 rounded-full blur-3xl pointer-events-none" />

          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <h2 id="current-plan-heading" className="text-xs uppercase font-bold text-slate-500 tracking-wider">
                Current Plan
              </h2>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xl font-bold text-white leading-none">{getPlanName()}</span>
                {isProCombined && (
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-bold font-mono">
                    ACTIVE
                  </span>
                )}
              </div>
              <p className="text-2xl font-extrabold text-slate-300 mt-2">{getPlanPrice()}</p>
            </div>
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shrink-0">
              <CreditCard className="w-5 h-5" />
            </div>
          </div>

          <div className="h-px bg-[#222D3D] my-4" />

          {/* Plan Limits Indicator */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Usage Limit (Invoices Processed)</span>
              <span className="font-semibold text-slate-200">
                {isProCombined ? "Unlimited" : isPro ? "1,000 / month" : "25 / month"}
              </span>
            </div>
            <div className="h-2 bg-slate-900 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full"
                style={{ width: isProCombined ? "100%" : isPro ? "10%" : "25%" }}
              />
            </div>
          </div>
        </section>

        {/* Plan Capabilities details */}
        <section aria-labelledby="capabilities-heading" className="space-y-3">
          <h3 id="capabilities-heading" className="text-xs uppercase font-bold text-slate-500 tracking-wider">
            Plan Capabilities
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[
              {
                title: "Inbound Receiving",
                desc: "OCR extraction & AI analysis of incoming invoices",
                enabled: true,
              },
              {
                title: "Outbound Sending",
                desc: "Verify and dispatch outbound invoices to clients",
                enabled: isProCombined,
              },
              {
                title: "AI Quality Rules",
                desc: "Train global & vendor-specific extraction templates",
                enabled: !isFree,
              },
              {
                title: "Priority Support",
                desc: "Direct support SLA for invoice processing delays",
                enabled: isProCombined,
              },
            ].map((cap) => (
              <div
                key={cap.title}
                className={`p-4 rounded-xl border flex gap-3 ${
                  cap.enabled
                    ? "bg-[#111827]/40 border-[#222D3D] text-slate-300"
                    : "bg-slate-950/20 border-slate-900/60 text-slate-500 opacity-60"
                }`}
              >
                <div className="shrink-0 mt-0.5">
                  {cap.enabled ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <AlertTriangle className="w-4 h-4 text-slate-600" />
                  )}
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-white">{cap.title}</h4>
                  <p className="text-[10px] text-slate-400 mt-0.5">{cap.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Change plan CTA */}
        {isAdmin ? (
          <section className="bg-slate-900/40 border border-[#222D3D] rounded-2xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="space-y-0.5 text-center sm:text-left">
              <p className="text-xs font-semibold text-white">Need to change your plan?</p>
              <p className="text-[11px] text-slate-400">Upgrades are processed securely via PayU checkout</p>
            </div>
            <a
              href={`${WEBSITE_URL}/?plan=pro_combined#pricing`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-600/10 hover:shadow-blue-600/20 transition-all whitespace-nowrap"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Change Subscription Plan</span>
            </a>
          </section>
        ) : (
          <div className="flex items-start gap-2.5 bg-[#1E293B]/20 border border-[#222D3D] rounded-xl p-3 text-[11px] text-slate-400">
            <ShieldCheck className="w-4 h-4 shrink-0 text-slate-500 mt-0.5" />
            <span>Only administrators can change the workspace subscription tier or manage checkout.</span>
          </div>
        )}
      </main>
    </div>
  );
}
