import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Sparkles } from "lucide-react";
import { Header } from "@/components/marketing/Header";
import { PLAN_COPY, appHref, firstParam } from "@/lib/billingPlans";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Payment successful — Invoice AI",
  robots: { index: false, follow: false },
};

/**
 * PayU return page — success (`surl` path).
 *
 * Reached as a plain browser GET after `routers/billing.py`'s 303, relayed
 * through `app/api/v1/billing/payu/success/route.ts`.
 *
 * PUBLIC BY DESIGN — no Clerk gate. A user coming back from PayU's hosted
 * page may land in a tab with no live session, and blocking or bouncing them
 * here would make a successful payment look broken.
 *
 * PURELY INFORMATIONAL — deliberately makes no API call of its own.
 * `_handle_payu_callback` has already committed `tenant.billing_plan` and
 * `tenant.payu_subscription_id` before issuing the redirect that lands here,
 * so there is nothing left to fetch, and a fetch that failed would make a
 * successful payment *look* failed. Keep it that way.
 */
export default function BillingSuccessPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const planId = firstParam(searchParams.plan);
  const txnid = firstParam(searchParams.txnid);
  const plan = planId ? PLAN_COPY[planId] : undefined;

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-1 relative z-10 flex items-start justify-center px-4 sm:px-6 lg:px-8 py-20">
        <div className="w-full max-w-2xl">
          <div className="glass-card-enterprise p-8 sm:p-10 text-center">
            <div className="mx-auto mb-6 h-16 w-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shadow-[0_0_30px_rgba(16,185,129,0.25)]">
              <CheckCircle2 className="h-8 w-8 text-emerald-400" />
            </div>

            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 mb-5 rounded-full bg-white/[0.04] border border-[rgba(255,255,255,0.08)] text-xs font-semibold text-emerald-300 backdrop-blur-md">
              <Sparkles className="w-4 h-4" />
              <span>Payment confirmed</span>
            </div>

            <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
              {plan ? (
                <>
                  You&apos;re on{" "}
                  <span className="animated-hero-heading inline-block">
                    {plan.name}
                  </span>
                </>
              ) : (
                <span className="animated-hero-heading inline-block">
                  Your upgrade is live
                </span>
              )}
            </h1>

            <p className="mt-4 text-base text-[#94A3B8] leading-relaxed max-w-lg mx-auto">
              {plan ? (
                <>
                  PayU confirmed your payment and your workspace has already
                  been upgraded — nothing else to do. {plan.blurb}
                </>
              ) : (
                <>
                  PayU confirmed your payment and your workspace has already
                  been upgraded — nothing else to do. Your new plan is visible
                  in Settings.
                </>
              )}
            </p>

            {(plan || txnid) && (
              <dl className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
                {plan && (
                  <div className="rounded-xl border border-[#222D3D] bg-white/[0.03] px-4 py-3">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#64748B]">
                      Plan
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-white">
                      {plan.name}{" "}
                      <span className="font-normal text-[#94A3B8]">
                        · {plan.price}
                      </span>
                    </dd>
                  </div>
                )}
                {txnid && (
                  <div className="rounded-xl border border-[#222D3D] bg-white/[0.03] px-4 py-3">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#64748B]">
                      Transaction reference
                    </dt>
                    <dd className="mt-1 text-sm font-mono text-[#CBD5E1] break-all">
                      {txnid}
                    </dd>
                  </div>
                )}
              </dl>
            )}

            <div className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3">
              <a
                href={appHref("/dashboard")}
                className="btn-primary-gradient w-full sm:w-auto flex items-center justify-center gap-2 text-sm"
              >
                <span>Go to your dashboard</span>
                <ArrowRight className="w-4 h-4" />
              </a>
              <a
                href={appHref("/settings")}
                className="btn-secondary-glass w-full sm:w-auto flex items-center justify-center gap-2 text-sm"
              >
                <span>Review plan settings</span>
              </a>
            </div>

            <p className="mt-8 text-xs text-[#64748B]">
              Billing renews monthly and is charged as a fresh PayU checkout
              each cycle — PayU&apos;s classic flow has no auto-debit, so
              you&apos;ll be prompted in-app before the cycle ends. Need
              something changed?{" "}
              <Link href="/" className="text-[#22D3EE] hover:underline">
                Back to Invoice.AI
              </Link>
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
