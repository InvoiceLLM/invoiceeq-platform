/**
 * Shared bits for the two PayU return pages (/billing/success, /billing/failed).
 *
 * Plan ids mirror `invoice-be/routers/billing.py::PLAN_AMOUNTS` exactly -- the
 * backend redirects here with `?plan=<that key>`, so these two lists have to
 * stay in step. Prices mirror `components/marketing/PricingTable.tsx`.
 */

export interface PlanCopy {
  name: string;
  price: string;
  blurb: string;
}

export const PLAN_COPY: Record<string, PlanCopy> = {
  pro: {
    name: "Pro",
    price: "₹4,999 / month",
    blurb:
      "Unlimited invoices, full platform access, and up to 10 users on the Receiving flow.",
  },
  pro_combined: {
    name: "Pro Combined",
    price: "₹8,999 / month",
    blurb:
      "Everything in Pro, plus the Sending flow — outbound invoices, the outbound auditor, and standing rules.",
  },
};

/**
 * Next.js gives searchParams as `string | string[] | undefined`; the backend
 * only ever sends single values, so collapse to the first.
 */
export function firstParam(
  value: string | string[] | undefined
): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

/**
 * Where to send the user onward into the authenticated app.
 *
 * SERVER-ONLY: reads `ENABLE_FE_PROXY`, which is not a `NEXT_PUBLIC_*` var.
 * When the Multi-Zone proxy is on (Azure — `website_features_tracker.md`
 * Gap 12), invoice-fe is `ingress.external: false` and only reachable through
 * this origin, so app routes must be same-origin paths. In local dev, where
 * there is no proxy, invoice-fe serves itself on its own port and needs a
 * full cross-origin URL — the same split the login page's `FE_URL` handles.
 */
export function appHref(path: string): string {
  if (process.env.ENABLE_FE_PROXY === "true") return path;
  const feUrl = process.env.NEXT_PUBLIC_FE_URL || "http://localhost:3001";
  return `${feUrl.replace(/\/$/, "")}${path}`;
}

/**
 * Support address is deliberately not hardcoded — no support mailbox is
 * defined anywhere in this repo yet. When unset, the failure page shows the
 * instruction and the transaction reference without a dead mailto: link.
 */
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL || null;
