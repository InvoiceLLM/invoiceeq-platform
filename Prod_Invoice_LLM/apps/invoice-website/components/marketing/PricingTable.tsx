"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { Check, Sparkles, Loader2 } from "lucide-react";

/**
 * Feature 3 / 3.1: Pricing Table & PayU Checkout Integration.
 *
 * PayU's classic API has no subscription/proration object -- unlike the
 * Stripe/Razorpay overlay models originally considered, "Upgrade" here is
 * just another one-time create_checkout_session() call for the full target
 * plan price (see feature_3.1_vendor_flow_pricing.md for why prorating a
 * mid-cycle delta isn't attempted). PayU Checkout is a full-page redirect
 * to a PayU-hosted payment page, not a client-side JS overlay -- this
 * component builds a hidden auto-submitting form from the backend's
 * hash-signed field set and submits it directly.
 */

type PlanId = "free" | "pro" | "pro_combined";

interface PlanDef {
  id: PlanId;
  name: string;
  price: string;
  cadence: string;
  description: string;
  features: string[];
  cta: string;
  highlight?: "popular" | "combined";
}

const PLANS: PlanDef[] = [
  {
    id: "free",
    name: "Free",
    price: "₹0",
    cadence: "/ month",
    description: "For evaluating the pipeline on real invoices.",
    features: [
      "50 invoices / month",
      "Full platform access — Dashboard, Chat, Auditor, Trainer, Connectors",
      "Inbound (Receiving) only",
      "1 user",
    ],
    cta: "Get Started Free",
  },
  {
    id: "pro",
    name: "Pro",
    price: "₹4,999",
    cadence: "/ month",
    description: "For teams processing invoices at volume.",
    features: [
      "Unlimited invoices",
      "Full platform access (same features as Free)",
      "Inbound (Receiving) only",
      "Up to 10 users",
    ],
    cta: "Start Pro Trial",
    highlight: "popular",
  },
  {
    id: "pro_combined",
    name: "Pro Combined",
    price: "₹8,999",
    cadence: "/ month",
    description: "For teams that also send invoices to their own customers.",
    features: [
      "Everything in Pro",
      "Inbound + Outbound (Receiving + Sending)",
      "Outbound auditor & standing rules",
      "Up to 10 users",
    ],
    cta: "Start Combined Pro Trial",
    highlight: "combined",
  },
];

function cardBorderClasses(highlight?: "popular" | "combined") {
  if (highlight === "popular") {
    return "border-indigo-600 shadow-[0_0_20px_rgba(99,102,241,0.3)]";
  }
  if (highlight === "combined") {
    return "border-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.3)]";
  }
  return "border-[#222D3D] hover:border-slate-700";
}

const PLAN_IDS = PLANS.map((p) => p.id);

export function PricingTable() {
  const { isSignedIn } = useUser();
  const router = useRouter();
  const [loadingPlan, setLoadingPlan] = useState<PlanId | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Gap 101: which plan the visitor was sent here *for*, via ?plan=<id>.
  // invoice-fe's Settings upgrade modal is the first caller (its "Upgrade Now"
  // sends ?plan=pro_combined#pricing), and the signup flow already uses the
  // same param shape in handleSelectPlan below.
  const [requestedPlan, setRequestedPlan] = useState<PlanId | null>(null);
  const cardRefs = useRef<Partial<Record<PlanId, HTMLDivElement | null>>>({});

  useEffect(() => {
    // Read from window.location rather than useSearchParams(): this component
    // renders inside the statically-rendered homepage, and useSearchParams()
    // there forces a Suspense boundary / dynamic rendering for what is purely a
    // presentational highlight. Same approach invoice-fe's /flows page already
    // uses for its own ?flow= deep link (website Gap 1).
    const param = new URLSearchParams(window.location.search).get("plan");
    if (!param || !PLAN_IDS.includes(param as PlanId)) return;

    const plan = param as PlanId;
    setRequestedPlan(plan);
    // The #pricing anchor already scrolls the section into view; this centres
    // the specific card, which matters on the 3-column desktop layout where the
    // requested plan can otherwise be the one furthest from where the eye lands.
    cardRefs.current[plan]?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  const handleSelectPlan = async (plan: PlanId) => {
    setError(null);

    if (plan === "free") {
      router.push("/signup");
      return;
    }

    if (!isSignedIn) {
      // Paid checkout requires an authenticated Admin tenant context on the
      // backend (create_checkout_session() checks role === "Admin") -- an
      // anonymous visitor has to create an account first. Matches this
      // site's existing "Get Started Free" -> /signup pattern.
      router.push(`/signup?plan=${plan}`);
      return;
    }

    setLoadingPlan(plan);
    try {
      const res = await fetch("/api/billing/create-checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan }),
      });

      const data = await res.json();
      if (!res.ok) {
        setError(data?.error || "Could not start checkout. Please try again.");
        setLoadingPlan(null);
        return;
      }

      // Build and submit the hidden form PayU's hosted page expects --
      // a full-page redirect, not a fetch/JSON response, so this can't be
      // handled by reading the response body alone.
      const form = document.createElement("form");
      form.method = "POST";
      form.action = data.action_url;

      const fields: Record<string, string> = {
        key: data.key,
        txnid: data.txnid,
        amount: data.amount,
        productinfo: data.productinfo,
        firstname: data.firstname,
        email: data.email,
        phone: data.phone,
        surl: data.surl,
        furl: data.furl,
        udf1: data.udf1,
        hash: data.hash,
        service_provider: data.service_provider,
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
      // Intentionally no setLoadingPlan(null) here -- the page is navigating
      // away to PayU's hosted checkout page.
    } catch (e) {
      setError("Could not reach the billing service. Please try again.");
      setLoadingPlan(null);
    }
  };

  return (
    <section
      id="pricing"
      className="py-20 relative border-t border-[rgba(255,255,255,0.08)] bg-[#050816]/60 backdrop-blur-md scroll-mt-[65px]"
    >
      <div className="glowing-divider-line mb-14" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.04] border border-[rgba(255,255,255,0.08)] text-xs font-semibold text-[#22D3EE] backdrop-blur-md shadow-[0_0_20px_rgba(34,211,238,0.15)]">
            <Sparkles className="w-4 h-4 text-[#22D3EE]" />
            <span>Simple, Transparent Pricing</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            Plans that scale with <span className="animated-hero-heading inline-block">your invoice volume</span>
          </h2>

          <p className="text-base sm:text-lg text-[#94A3B8] leading-relaxed max-w-2xl mx-auto">
            Start free, upgrade when you outgrow the trial limit. No credit card required for Free.
          </p>
        </div>

        {error && (
          <div className="max-w-lg mx-auto mb-8 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm text-center">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
          {PLANS.map((plan) => (
            <div
              key={plan.id}
              ref={(el) => {
                cardRefs.current[plan.id] = el;
              }}
              className={`relative flex flex-col rounded-2xl border bg-white/[0.03] backdrop-blur-md p-8 transition-all duration-300 ${cardBorderClasses(
                plan.highlight
              )} ${
                requestedPlan === plan.id
                  ? "ring-2 ring-violet-400 ring-offset-2 ring-offset-[#050816]"
                  : ""
              }`}
            >
              {requestedPlan === plan.id && (
                <span className="absolute -top-3 right-4 bg-violet-600 text-white rounded-full px-2 py-0.5 text-xs font-semibold">
                  The plan you need
                </span>
              )}
              {plan.highlight === "popular" && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-indigo-600 text-white rounded-full px-2 py-0.5 text-xs font-semibold">
                  Most Popular
                </span>
              )}
              {plan.highlight === "combined" && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-emerald-600 text-white rounded-full px-2 py-0.5 text-xs font-semibold">
                  Receiving + Sending
                </span>
              )}

              <h3 className="text-lg font-bold text-white">{plan.name}</h3>
              <p className="text-sm text-[#94A3B8] mt-1 mb-6">{plan.description}</p>

              <div className="flex items-baseline gap-1 mb-6">
                <span className="text-4xl font-extrabold text-white">{plan.price}</span>
                <span className="text-sm text-[#94A3B8]">{plan.cadence}</span>
              </div>

              <ul className="space-y-3 mb-8 flex-1">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2 text-sm text-[#CBD5E1]">
                    <Check className="w-4 h-4 text-[#22D3EE] shrink-0 mt-0.5" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>

              <button
                type="button"
                onClick={() => handleSelectPlan(plan.id)}
                disabled={loadingPlan !== null}
                className={`w-full flex items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-semibold transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                  plan.highlight
                    ? "btn-primary-gradient"
                    : "bg-white/[0.06] border border-[#222D3D] text-white hover:bg-white/[0.1]"
                }`}
              >
                {loadingPlan === plan.id ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Redirecting to PayU...</span>
                  </>
                ) : (
                  <span>{plan.cta}</span>
                )}
              </button>
            </div>
          ))}
        </div>

        <p className="text-center text-xs text-[#64748B] mt-10">
          Payments processed securely by PayU. Your card/UPI details are never seen or stored by Invoice.AI.
        </p>
      </div>
    </section>
  );
}
