"use client";

/**
 * Feature 10 — Subscriptions & Billing page
 *
 * Gap 120: Added a real plan picker (Pro / Pro Combined) so the "Change Plan"
 * CTA routes to PayU with the correct `?plan=` pre-selected, instead of always
 * hardcoding pro_combined.
 */

import React, { useState, useEffect } from "react";
import { CreditCard, CheckCircle2, ShieldCheck, Sparkles, AlertTriangle, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

const PLANS = [
  {
    key: "pro",
    name: "Pro Plan",
    price: "₹4,999",
    period: "/ month",
    features: [
      "Up to 1,000 invoices / month",
      "Inbound AP processing",
      "AI Quality Rules & Trainer",
    ],
    accent: "blue",
  },
  {
    key: "pro_combined",
    name: "Pro Combined",
    price: "₹8,999",
    period: "/ month",
    features: [
      "Unlimited inbound & outbound",
      "Email, Webhook & Connector support",
      "Priority support SLA",
    ],
    accent: "violet",
  },
] as const;

export default function SubscriptionsPage() {
  // FE Gap 110: own h-16 header bar replaced by the shared one.
  usePageHeader({
    title: "Subscriptions & Billing",
    subtitle: "Manage your workspace pricing tier and limits",
    backHref: "/settings",
  });

  const { role, billingPlan, loading } = useAuth();
  const isAdmin = role === "Admin";

  const isProCombined = billingPlan === "pro_combined" || billingPlan === "active";
  const isPro = billingPlan === "pro";
  const isFree = !isPro && !isProCombined;

  // Gap 120: plan picker state — defaults to current plan, or pro if free
  const [selectedPlan, setSelectedPlan] = useState<"pro" | "pro_combined">(
    isProCombined ? "pro_combined" : "pro"
  );
  const [isCheckoutLoading, setIsCheckoutLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  // Gap 143: real usage tracker state
  const [invoicesCount, setInvoicesCount] = useState<number | null>(null);

  useEffect(() => {
    async function fetchUsage() {
      try {
        const res = await fetch("/api/invoices?limit=1");
        if (res.ok) {
          const data = await res.json();
          if (typeof data.total === "number") {
            setInvoicesCount(data.total);
          } else if (Array.isArray(data.invoices)) {
            setInvoicesCount(data.invoices.length);
          }
        }
      } catch {
        // Fallback to 0 if fetch fails
      }
    }
    void fetchUsage();
  }, []);

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

  /**
   * Gap 132: Direct PayU checkout session creation and POST form submit.
   * Eliminates extra landing-page redirects and opens the PayU payment screen
   * directly in the current window.
   */
  const handleUpgrade = async () => {
    if (isCheckoutLoading) return;
    setIsCheckoutLoading(true);
    setCheckoutError(null);

    try {
      const res = await fetch("/api/billing/create-checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: selectedPlan }),
      });

      const data = await res.json();
      if (!res.ok) {
        setCheckoutError(data?.error || data?.detail || "Could not start checkout. Please try again.");
        setIsCheckoutLoading(false);
        return;
      }

      // Build and submit the hidden form PayU's hosted payment gateway expects
      const form = document.createElement("form");
      form.method = "POST";
      form.action = data.action_url;

      const fields: Record<string, string> = {
        key: data.key,
        txnid: data.txnid,
        amount: String(data.amount),
        productinfo: data.productinfo,
        firstname: data.firstname,
        email: data.email,
        phone: data.phone || "",
        surl: data.surl,
        furl: data.furl,
        udf1: data.udf1 || "",
        hash: data.hash,
        service_provider: data.service_provider || "payu_paisa",
      };

      for (const [name, value] of Object.entries(fields)) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value ?? "";
        form.appendChild(input);
      }

      document.body.appendChild(form);
      form.submit();
    } catch (err) {
      setCheckoutError("Failed to connect to checkout gateway. Please check network connection.");
      setIsCheckoutLoading(false);
    }
  };

  const processedCount = invoicesCount ?? 0;
  const planLimit = isProCombined ? 999999 : isPro ? 1000 : 25;
  const usagePercentage = isProCombined ? 100 : Math.min(100, Math.round((processedCount / planLimit) * 100));

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
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

          {/* Gap 143: Real Usage Limits Indicator */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Usage Limit (Invoices Processed)</span>
              <span className="font-semibold text-slate-200 font-mono">
                {isProCombined ? `${processedCount} processed (Unlimited)` : `${processedCount} / ${planLimit} invoices processed`}
              </span>
            </div>
            <div className="h-2 bg-slate-900 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${usagePercentage}%` }}
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

        {/* Gap 120 & Gap 132: Plan Picker + Direct PayU Checkout CTA */}
        {isAdmin ? (
          <section className="space-y-4">
            <h3 className="text-xs uppercase font-bold text-slate-500 tracking-wider">
              Select a Plan to Upgrade
            </h3>

            <div className="grid grid-cols-2 gap-3">
              {PLANS.map((plan) => {
                const isSelected = selectedPlan === plan.key;
                const isCurrent =
                  (plan.key === "pro_combined" && isProCombined) ||
                  (plan.key === "pro" && isPro);
                const accentBorder = plan.accent === "violet"
                  ? "border-violet-500/60 ring-violet-500/20"
                  : "border-blue-500/60 ring-blue-500/20";
                const accentBg = plan.accent === "violet"
                  ? "bg-violet-500/5"
                  : "bg-blue-500/5";

                return (
                  <button
                    key={plan.key}
                    onClick={() => setSelectedPlan(plan.key as "pro" | "pro_combined")}
                    className={`relative text-left p-4 rounded-xl border-2 transition-all ${
                      isSelected
                        ? `${accentBorder} ${accentBg} ring-2`
                        : "border-[#222D3D] bg-[#111827]/40 hover:border-[#334155]"
                    }`}
                  >
                    {isCurrent && (
                      <span className="absolute top-2 right-2 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        CURRENT
                      </span>
                    )}
                    <p className="text-sm font-semibold text-white">{plan.name}</p>
                    <p className="text-lg font-extrabold text-slate-200 mt-1">
                      {plan.price}
                      <span className="text-xs font-normal text-slate-500"> {plan.period}</span>
                    </p>
                    <ul className="mt-3 space-y-1.5">
                      {plan.features.map((f) => (
                        <li key={f} className="flex items-center gap-1.5 text-[11px] text-slate-400">
                          <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                          {f}
                        </li>
                      ))}
                    </ul>
                  </button>
                );
              })}
            </div>

            {checkoutError && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{checkoutError}</span>
              </div>
            )}

            <div className="bg-slate-900/40 border border-[#222D3D] rounded-2xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="space-y-0.5 text-center sm:text-left">
                <p className="text-xs font-semibold text-white">
                  {selectedPlan === "pro" ? "Upgrade to Pro" : "Upgrade to Pro Combined"}
                </p>
                <p className="text-[11px] text-slate-400">Processed securely via PayU checkout</p>
              </div>
              <button
                type="button"
                onClick={handleUpgrade}
                disabled={isCheckoutLoading}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold shadow-lg shadow-blue-600/10 hover:shadow-blue-600/20 transition-all whitespace-nowrap"
              >
                {isCheckoutLoading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Connecting to PayU...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Change Subscription Plan</span>
                  </>
                )}
              </button>
            </div>
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
