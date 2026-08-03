import type { Metadata } from "next";
import Link from "next/link";
import { AlertTriangle, ArrowRight, LifeBuoy, XCircle } from "lucide-react";
import { Header } from "@/components/marketing/Header";
import { SUPPORT_EMAIL, appHref, firstParam } from "@/lib/billingPlans";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Payment not completed — Invoice AI",
  robots: { index: false, follow: false },
};

/**
 * PayU return page — failure (`furl` path, and every non-success branch of
 * `surl` too).
 *
 * PUBLIC BY DESIGN — no Clerk gate, same reason as the success page: a user
 * returning from PayU's hosted page may have no live session in that tab.
 *
 * The `reason` values below are not invented — they are exactly the ones
 * `invoice-be/routers/billing.py::_handle_payu_callback` emits:
 *   ?reason=malformed        — callback arrived with no txnid at all
 *   ?reason=hash_mismatch    — PayU's response hash didn't verify
 *   ?reason=unverifiable     — verify_payment couldn't be reached
 *   ?reason=unknown_plan     — verified success, productinfo didn't map
 *   ?reason=unknown_tenant   — verified success, udf1 didn't resolve
 *   ?txnid=...  (no reason)  — a plain decline PayU itself confirmed
 *   (no params)              — nothing to go on
 * All five `reason=` branches also carry `&txnid=` (added alongside these
 * pages) so a possibly-charged user always has a reference to quote.
 *
 * The three severities matter and must not be flattened into one "payment
 * failed" message: `hash_mismatch`/`unverifiable`/`malformed` mean *we could
 * not verify*, not that the money stayed put, and `unknown_plan`/
 * `unknown_tenant` mean the payment demonstrably DID succeed at PayU and we
 * failed to apply it. Telling either group to "try again" would invite a
 * second charge.
 */

type Severity = "declined" | "unconfirmed" | "charged_not_applied";

interface Outcome {
  severity: Severity;
  title: string;
  detail: string;
  nextStep: string;
}

const OUTCOMES: Record<string, Outcome> = {
  malformed: {
    severity: "unconfirmed",
    title: "We couldn't read the payment response",
    detail:
      "PayU sent us a result we couldn't match to a checkout — it arrived without a transaction reference, so we can't tell whether the payment went through. Your plan has not been changed.",
    nextStep:
      "Check your bank or UPI app before paying again. If a charge was taken, contact support with your PayU receipt rather than starting a second payment.",
  },
  hash_mismatch: {
    severity: "unconfirmed",
    title: "We couldn't confirm this payment was genuine",
    detail:
      "The response we received didn't carry a valid PayU signature, so we refused to act on it. That check exists because this address is public and a result can be faked — but it also means we can't confirm what happened to a real payment. Your plan has not been changed.",
    nextStep:
      "Do not pay again yet. Contact support with the transaction reference below so we can check the payment against PayU's own records first.",
  },
  unverifiable: {
    severity: "unconfirmed",
    title: "We couldn't reach PayU to confirm this payment",
    detail:
      "We never trust a payment result on its own — we ask PayU's servers directly to confirm it. That confirmation call didn't get through, so we couldn't safely upgrade your workspace. Your plan has not been changed.",
    nextStep:
      "Do not pay again yet. If money has left your account, the payment may well have succeeded — contact support with the transaction reference below and we'll reconcile it.",
  },
  unknown_plan: {
    severity: "charged_not_applied",
    title: "Your payment succeeded, but we couldn't apply it",
    detail:
      "PayU confirmed this payment, but the plan it referenced isn't one we recognise, so we stopped rather than guess which plan to give you. You have been charged and your workspace has not been upgraded.",
    nextStep:
      "Please don't pay again. Contact support with the transaction reference below — we can apply the plan manually or refund it.",
  },
  unknown_tenant: {
    severity: "charged_not_applied",
    title: "Your payment succeeded, but we couldn't apply it",
    detail:
      "PayU confirmed this payment, but we couldn't match it to a workspace, so there was nothing to upgrade. You have been charged and your workspace has not been upgraded.",
    nextStep:
      "Please don't pay again. Contact support with the transaction reference below — we can apply the plan manually or refund it.",
  },
};

const DECLINED: Outcome = {
  severity: "declined",
  title: "Your payment didn't go through",
  detail:
    "PayU's own records confirm this transaction wasn't completed — it may have been cancelled, declined by your bank, or timed out. Your plan is unchanged and you have not been charged.",
  nextStep:
    "You can safely start the checkout again. If your bank shows a temporary hold, it's an authorisation that's normally released on its own.",
};

const UNKNOWN: Outcome = {
  severity: "declined",
  title: "Your payment wasn't completed",
  detail:
    "We didn't receive any details about this payment attempt, so there's nothing to apply. Your plan is unchanged.",
  nextStep: "You can start the checkout again from the pricing page.",
};

const SEVERITY_STYLE: Record<
  Severity,
  { ring: string; iconColor: string; badge: string; label: string }
> = {
  declined: {
    ring: "bg-slate-500/10 border-slate-500/30 shadow-[0_0_30px_rgba(100,116,139,0.2)]",
    iconColor: "text-slate-300",
    badge: "text-slate-300",
    label: "Payment not completed",
  },
  unconfirmed: {
    ring: "bg-amber-500/10 border-amber-500/30 shadow-[0_0_30px_rgba(245,158,11,0.25)]",
    iconColor: "text-amber-400",
    badge: "text-amber-300",
    label: "Payment could not be verified",
  },
  charged_not_applied: {
    ring: "bg-red-500/10 border-red-500/30 shadow-[0_0_30px_rgba(239,68,68,0.25)]",
    iconColor: "text-red-400",
    badge: "text-red-300",
    label: "Charged — plan not applied",
  },
};

function resolveOutcome(reason: string | null, txnid: string | null): Outcome {
  if (reason && OUTCOMES[reason]) return OUTCOMES[reason];
  if (!reason && txnid) return DECLINED;
  return UNKNOWN;
}

export default function BillingFailedPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const reason = firstParam(searchParams.reason);
  const txnid = firstParam(searchParams.txnid);
  const outcome = resolveOutcome(reason, txnid);
  const style = SEVERITY_STYLE[outcome.severity];
  const canRetry = outcome.severity === "declined";

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-1 relative z-10 flex items-start justify-center px-4 sm:px-6 lg:px-8 py-20">
        <div className="w-full max-w-2xl">
          <div className="glass-card-enterprise p-8 sm:p-10">
            <div
              className={`mx-auto mb-6 h-16 w-16 rounded-2xl border flex items-center justify-center ${style.ring}`}
            >
              {outcome.severity === "declined" ? (
                <XCircle className={`h-8 w-8 ${style.iconColor}`} />
              ) : (
                <AlertTriangle className={`h-8 w-8 ${style.iconColor}`} />
              )}
            </div>

            <div className="text-center">
              <div
                className={`inline-flex items-center gap-2 px-3.5 py-1.5 mb-5 rounded-full bg-white/[0.04] border border-[rgba(255,255,255,0.08)] text-xs font-semibold backdrop-blur-md ${style.badge}`}
              >
                <span>{style.label}</span>
              </div>

              <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                {outcome.title}
              </h1>

              <p className="mt-4 text-base text-[#94A3B8] leading-relaxed">
                {outcome.detail}
              </p>
            </div>

            <div className="mt-8 rounded-xl border border-[#222D3D] bg-white/[0.03] px-5 py-4">
              <div className="flex items-start gap-3">
                <LifeBuoy className="w-4 h-4 text-[#22D3EE] shrink-0 mt-0.5" />
                <p className="text-sm text-[#CBD5E1] leading-relaxed">
                  {outcome.nextStep}
                </p>
              </div>
            </div>

            {txnid && (
              <div className="mt-3 rounded-xl border border-[#222D3D] bg-white/[0.03] px-5 py-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-[#64748B]">
                  Transaction reference
                </div>
                <div className="mt-1 text-sm font-mono text-white break-all">
                  {txnid}
                </div>
                <p className="mt-2 text-xs text-[#64748B]">
                  Quote this when you contact us — it&apos;s how we look the
                  payment up with PayU.
                </p>
              </div>
            )}

            <div className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3">
              {canRetry ? (
                <Link
                  href="/#pricing"
                  className="btn-primary-gradient w-full sm:w-auto flex items-center justify-center gap-2 text-sm"
                >
                  <span>Try the checkout again</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>
              ) : SUPPORT_EMAIL ? (
                <a
                  href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
                    `Payment issue${txnid ? ` — ${txnid}` : ""}`
                  )}`}
                  className="btn-primary-gradient w-full sm:w-auto flex items-center justify-center gap-2 text-sm"
                >
                  <span>Contact support</span>
                  <ArrowRight className="w-4 h-4" />
                </a>
              ) : null}

              <a
                href={appHref("/dashboard")}
                className="btn-secondary-glass w-full sm:w-auto flex items-center justify-center gap-2 text-sm"
              >
                <span>Back to your dashboard</span>
              </a>
            </div>

            {!canRetry && !SUPPORT_EMAIL && (
              <p className="mt-6 text-center text-xs text-[#64748B]">
                Reach out through your usual support channel and quote the
                reference above.
              </p>
            )}

            <p className="mt-8 text-center text-xs text-[#64748B]">
              Payments are processed by PayU. Your card/UPI details are never
              seen or stored by Invoice.AI.{" "}
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
