"use client";

/**
 * Feature 10 — Subscriptions & Billing page
 *
 * Gap 120: Added a real plan picker (Pro / Pro Combined) so the "Change Plan"
 * CTA routes to PayU with the correct `?plan=` pre-selected, instead of always
 * hardcoding pro_combined.
 *
 * Gap 143: the usage bar now reads `GET /api/billing/usage` — the backend's own
 * allowance counter — instead of deriving usage locally. The previous version
 * was wrong twice over: it called `GET /api/invoices?limit=1` and looked for
 * `data.total`/`data.invoices` in a body that is a bare array (the count is in
 * the `X-Total-Count` *header*), so the count silently stayed at 0 forever; and
 * it compared that count to a hard-coded `planLimit` whose free-tier value (25)
 * was half the real limit the backend enforces (`DEFAULT_FREE_INVOICES_LIMIT`,
 * 50). Even read correctly, an invoice-row count could never have agreed with
 * the gate — the gate reads a monthly decrement-only counter, the list endpoint
 * counts inbound invoices for the lifetime of the account. There are no
 * client-side plan numbers left on this screen's usage bar as a result.
 *
 * Gap 188: the Pro plan card sold "Up to 1,000 invoices / month". No such cap
 * exists anywhere in the software — `routers/invoices.py` only ever consults
 * `free_invoices_remaining` under `billing_plan == "free"`, and
 * `GET /billing/usage` reports `metered=False` with null numbers for `pro`.
 * The commercial decision was to correct the copy rather than build enforcement,
 * so the feature line now reads "Unlimited invoices", identical to the Pro card
 * on invoice-website's `PricingTable.tsx` (the canonical pricing copy, which
 * already said unlimited). This screen now states the same thing in all three
 * places: the card, the usage bar's "Not metered on this plan", and its
 * "This plan has no invoice allowance enforced on it." caption.
 */

import React, { useState, useEffect } from "react";
import { CreditCard, CheckCircle2, ShieldCheck, Sparkles, AlertTriangle, Loader2 } from "lucide-react";
import { useAuth, refreshAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

const PLANS = [
  {
    key: "pro",
    name: "Pro Plan",
    price: "₹4,999",
    period: "/ month",
    features: [
      // Gap 188: was "Up to 1,000 invoices / month" — a cap the software has
      // never enforced. Wording now matches invoice-website's PricingTable Pro
      // card, which is the canonical pricing copy.
      "Unlimited invoices",
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

/** Gap 143: the shape of `GET /billing/usage` (routers/billing.py::BillingUsageResponse). */
interface BillingUsage {
  plan: string;
  /** Whether this plan has an invoice allowance the backend actually enforces. */
  metered: boolean;
  used: number | null;
  limit: number | null;
  remaining: number | null;
  /** ISO timestamp of the next allowance refill, or null when not metered. */
  resets_at: string | null;
  /** Gap 264: set once the workspace has asked not to renew. */
  cancel_requested_at: string | null;
  /** Gap 264: paid access continues until this date either way. */
  paid_through: string | null;
}

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
  const [checkoutHint, setCheckoutHint] = useState<string | null>(null);

  // Gap 143: real usage tracker state — mirrors BillingUsageResponse in
  // routers/billing.py. `metered` is false for every plan that has no enforced
  // invoice allowance, in which case the numeric fields are null rather than a
  // made-up ceiling; the component must not substitute one.
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [usageState, setUsageState] = useState<"loading" | "ready" | "error">("loading");

  // Gap 264: self-serve cancel/reactivate.
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [cancelLoading, setCancelLoading] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  useEffect(() => {
    function onPayuMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.source !== "invoice-payu" || data.type !== "payu-return") return;
      setIsCheckoutLoading(false);
      setCheckoutHint(null);
      if (data.status === "success") {
        // Gap 138: plan is already committed server-side; refresh identity
        // so billingPlan updates without requiring Ctrl+F5.
        setCheckoutHint("Payment succeeded — refreshing your plan…");
        void refreshAuth().then(() => {
          setCheckoutHint("Your plan is up to date.");
        });
      } else {
        setCheckoutError("Payment was not completed. You can try again whenever you're ready.");
      }
    }
    window.addEventListener("message", onPayuMessage);
    return () => window.removeEventListener("message", onPayuMessage);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function fetchUsage() {
      try {
        const res = await fetch("/api/billing/usage", { cache: "no-store" });
        if (!res.ok) throw new Error(`usage request failed: ${res.status}`);
        const data: BillingUsage = await res.json();
        if (cancelled) return;
        setUsage(data);
        setUsageState("ready");
      } catch {
        if (cancelled) return;
        // Deliberately surfaced rather than silently shown as 0 used: a zero is
        // indistinguishable from a real "nothing used yet", which is exactly
        // how the pre-Gap-143 version hid its own failure for weeks.
        setUsageState("error");
      }
    }

    void fetchUsage();
    return () => {
      cancelled = true;
    };
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
   * Gap 132 + popup UX: create PayU checkout session and POST the classic
   * hash form into a dedicated popup. Same-tab navigation left users stuck on
   * PayU with no clean cancel path; closing the popup returns them here.
   * PayU cannot be iframed (X-Frame-Options), so a popup is the workable
   * "side window".
   */
  const handleUpgrade = async () => {
    if (isCheckoutLoading) return;
    setIsCheckoutLoading(true);
    setCheckoutError(null);
    setCheckoutHint(null);

    // Open synchronously on the click gesture so the browser doesn't block it
    // after the await. Named window so the form can target it.
    const popupName = "payu_checkout";
    const payuWin = window.open(
      "about:blank",
      popupName,
      "popup=yes,width=520,height=780,scrollbars=yes,resizable=yes"
    );
    if (!payuWin) {
      setCheckoutError(
        "Pop-up was blocked. Allow pop-ups for this site to open PayU, then try again."
      );
      setIsCheckoutLoading(false);
      return;
    }
    try {
      payuWin.document.write(
        "<!doctype html><title>PayU</title><body style='font-family:sans-serif;padding:24px;color:#334155'>Opening PayU checkout…</body>"
      );
      payuWin.document.close();
    } catch {
      // Cross-origin write can fail after navigation; ignore.
    }

    try {
      const res = await fetch("/api/billing/create-checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: selectedPlan }),
      });

      const data = await res.json();
      if (!res.ok) {
        try {
          payuWin.close();
        } catch {
          /* ignore */
        }
        setCheckoutError(data?.error || data?.detail || "Could not start checkout. Please try again.");
        setIsCheckoutLoading(false);
        return;
      }

      const form = document.createElement("form");
      form.method = "POST";
      form.action = data.action_url;
      form.target = popupName;

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
      form.remove();

      setCheckoutHint("PayU opened in a new window. Close that window to cancel without paying.");
      setIsCheckoutLoading(false);

      const poll = window.setInterval(() => {
        if (payuWin.closed) {
          window.clearInterval(poll);
          setCheckoutHint(null);
        }
      }, 500);
    } catch {
      try {
        payuWin.close();
      } catch {
        /* ignore */
      }
      setCheckoutError("Failed to connect to checkout gateway. Please check network connection.");
      setIsCheckoutLoading(false);
    }
  };

  /**
   * Gap 264: PayU has no auto-charge to stop (see routers/billing.py's module
   * docstring), so this doesn't call PayU at all — it records the choice
   * server-side and refetches usage so the "Cancels on <date>" state renders
   * immediately, no page reload needed.
   */
  const handleCancelSubscription = async () => {
    setCancelLoading(true);
    setCancelError(null);
    try {
      const res = await fetch("/api/billing/cancel", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || "Failed to cancel subscription.");
      }
      setUsage((prev) => (prev ? { ...prev, ...data } : data));
      setShowCancelConfirm(false);
    } catch (err: any) {
      setCancelError(err?.message || "Failed to cancel subscription. Please try again.");
    } finally {
      setCancelLoading(false);
    }
  };

  const handleReactivateSubscription = async () => {
    setCancelLoading(true);
    setCancelError(null);
    try {
      const res = await fetch("/api/billing/reactivate", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || "Failed to reactivate subscription.");
      }
      setUsage((prev) => (prev ? { ...prev, ...data } : data));
    } catch (err: any) {
      setCancelError(err?.message || "Failed to reactivate subscription. Please try again.");
    } finally {
      setCancelLoading(false);
    }
  };

  // Gap 143: every number below comes from the backend. A plan the backend
  // reports as unmetered gets no invented ceiling to draw a bar against — that
  // substitution is exactly what produced the "25 invoices" the free tier never
  // had. Null-checked field by field so the numbers are typed as present from
  // here on rather than asserted.
  const meteredUsage =
    usage && usage.metered && usage.used !== null && usage.limit !== null && usage.remaining !== null
      ? { used: usage.used, limit: usage.limit, remaining: usage.remaining }
      : null;
  const usagePercentage =
    meteredUsage && meteredUsage.limit > 0
      ? Math.min(100, Math.round((meteredUsage.used / meteredUsage.limit) * 100))
      : 0;
  const resetsAt = usage?.resets_at ? new Date(usage.resets_at) : null;
  const resetsLabel =
    resetsAt && !Number.isNaN(resetsAt.getTime())
      ? resetsAt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
      : null;

  // Gap 264: when access actually ends if a cancellation is pending.
  const paidThroughAt = usage?.paid_through ? new Date(usage.paid_through) : null;
  const paidThroughLabel =
    paidThroughAt && !Number.isNaN(paidThroughAt.getTime())
      ? paidThroughAt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
      : null;
  const isCancellationPending = !!usage?.cancel_requested_at;

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

          {/* Gap 143: usage indicator, rendered entirely from GET /billing/usage.
              Four distinct states — loading, unreachable, metered, not metered —
              because the old version collapsed all four into "0 processed",
              which is why a broken fetch looked like a working empty account. */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Invoice Allowance</span>
              <span className="font-semibold text-slate-200 font-mono">
                {usageState === "loading" && "Loading…"}
                {usageState === "error" && (
                  <span className="text-amber-400">Usage unavailable</span>
                )}
                {usageState === "ready" &&
                  (meteredUsage
                    ? `${meteredUsage.used} / ${meteredUsage.limit} invoices used`
                    : "Not metered on this plan")}
              </span>
            </div>

            {/* No bar when there is no allowance to draw one against. */}
            {usageState === "ready" && meteredUsage && (
              <div className="h-2 bg-slate-900 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    usagePercentage >= 100
                      ? "bg-rose-500"
                      : usagePercentage >= 80
                        ? "bg-amber-500"
                        : "bg-blue-500"
                  }`}
                  style={{ width: `${usagePercentage}%` }}
                />
              </div>
            )}

            <p className="text-[10px] text-slate-500">
              {usageState === "error"
                ? "Couldn't reach the billing service — this figure is not a zero, it's unknown."
                : usageState === "ready" && meteredUsage
                  ? `${meteredUsage.remaining} remaining${resetsLabel ? ` · renews ${resetsLabel}` : ""}`
                  : usageState === "ready"
                    ? "This plan has no invoice allowance enforced on it."
                    : ""}
            </p>
          </div>

          {/* Gap 264: cancel / pending-cancellation state. Only meaningful on
              a paid plan — nothing to cancel on Free. Admin-only, matching
              every other billing-plan-affecting control on this page. */}
          {isAdmin && !isFree && (
            <div className="mt-4 pt-4 border-t border-[#222D3D]">
              {isCancellationPending ? (
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
                  <p className="text-[11px] text-amber-300">
                    Subscription set to cancel
                    {paidThroughLabel ? ` — access continues until ${paidThroughLabel}.` : "."}
                  </p>
                  <button
                    type="button"
                    onClick={handleReactivateSubscription}
                    disabled={cancelLoading}
                    className="shrink-0 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 text-[11px] font-semibold disabled:opacity-50 transition-all"
                  >
                    {cancelLoading ? "Working…" : "Keep My Subscription"}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowCancelConfirm(true)}
                  className="text-[11px] text-slate-500 hover:text-rose-400 underline decoration-dotted transition-colors"
                >
                  Cancel subscription
                </button>
              )}
              {cancelError && (
                <p className="mt-2 text-[10px] text-rose-400">{cancelError}</p>
              )}
            </div>
          )}
        </section>

        {/* Gap 264: confirmation modal — cancellation ends real paid access,
            worth an explicit confirm rather than a one-click destructive
            action. */}
        {showCancelConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="w-full max-w-sm bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-xl">
              <h3 className="text-sm font-semibold text-white">Cancel subscription?</h3>
              <p className="text-xs text-slate-400">
                {paidThroughLabel
                  ? `Your workspace keeps full access until ${paidThroughLabel}, then switches to the Free plan. You can change your mind any time before then.`
                  : "Your workspace will switch to the Free plan at the end of the current billing period. You can change your mind any time before then."}
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowCancelConfirm(false)}
                  disabled={cancelLoading}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:bg-slate-800 transition-colors"
                >
                  Keep subscription
                </button>
                <button
                  type="button"
                  onClick={handleCancelSubscription}
                  disabled={cancelLoading}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/40 text-rose-300 disabled:opacity-50 transition-all"
                >
                  {cancelLoading ? "Cancelling…" : "Yes, cancel"}
                </button>
              </div>
            </div>
          </div>
        )}

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

            {checkoutHint && !checkoutError && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-300 text-xs">
                <CreditCard className="w-4 h-4 shrink-0" />
                <span>{checkoutHint}</span>
              </div>
            )}

            <div className="bg-slate-900/40 border border-[#222D3D] rounded-2xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="space-y-0.5 text-center sm:text-left">
                <p className="text-xs font-semibold text-white">
                  {selectedPlan === "pro" ? "Upgrade to Pro" : "Upgrade to Pro Combined"}
                </p>
                <p className="text-[11px] text-slate-400">
                  PayU opens in a new window — close it anytime to cancel
                </p>
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
