"use client";

/**
 * Feature 17 (FE Gap 323): the Plug & Play wizard's first-run trigger.
 *
 * Rendered once by `components/layout/Shell.tsx`, between the shared header and
 * the page body, so a tenant that has never configured a workflow is prompted
 * on first login instead of having to discover Settings → Workflows.
 *
 * Three deliberate properties:
 *
 * 1. **Admin only, checked before fetching.** `GET /api/settings/workflow` is
 *    Admin-gated on the backend (it reports the tenant's API key scope), so
 *    firing it for anyone else is a guaranteed 403 on every page load. The role
 *    check is the gate on the request, not just on the render.
 *
 * 2. **Fails closed to silence.** Any non-OK response, non-JSON body, or thrown
 *    fetch renders nothing at all. An ops problem must not turn into a banner
 *    on every screen in the app; the wizard is still reachable from Settings.
 *
 * 3. **Once per tab.** A module-level cache plus a shared in-flight promise,
 *    the same shape `hooks/useAuth.ts` uses, so client-side navigation between
 *    routes does not re-request this on every page.
 *
 * A hard redirect into the wizard was considered and rejected: it fights deep
 * links, is hostile to an Admin who signed in to do something else, and would
 * make several existing Playwright specs depend on whether a backend happened
 * to be running. Turning this into a redirect is a deliberate product decision,
 * not a refactor.
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Workflow, X, ArrowRight } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

const WORKFLOW_URL = "/api/settings/workflow";
const WIZARD_PATH = "/settings/workflows";
const DISMISS_KEY = "workflow_setup_banner_dismissed";

/** null = unknown/failed (render nothing); true/false = a real answer. */
let cachedNeedsSetup: boolean | null = null;
let inFlight: Promise<boolean | null> | null = null;

function fetchNeedsSetup(): Promise<boolean | null> {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const res = await fetch(WORKFLOW_URL, { cache: "no-store" });
      if (!res.ok) return null;
      const data = await res.json();
      // `completed_at` is set once, on the first successful save, and never
      // reset by a later edit — so null means "has never been through the
      // wizard", which is exactly the population this banner is for.
      return data?.completed_at == null;
    } catch {
      return null;
    }
  })()
    .then((result) => {
      cachedNeedsSetup = result;
      return result;
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

export default function WorkflowSetupBanner() {
  const { role, loading } = useAuth();
  const pathname = usePathname();
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(cachedNeedsSetup);
  const [dismissed, setDismissed] = useState(false);

  const isAdmin = role === "Admin";
  const onWizard = pathname === WIZARD_PATH || pathname?.startsWith(`${WIZARD_PATH}/`);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissed(window.sessionStorage.getItem(DISMISS_KEY) === "1");
  }, []);

  useEffect(() => {
    if (loading || !isAdmin || onWizard) return;
    if (cachedNeedsSetup !== null) {
      setNeedsSetup(cachedNeedsSetup);
      return;
    }
    let active = true;
    void fetchNeedsSetup().then((result) => {
      if (active) setNeedsSetup(result);
    });
    return () => {
      active = false;
    };
  }, [loading, isAdmin, onWizard]);

  if (loading || !isAdmin || onWizard || dismissed || needsSetup !== true) return null;

  const handleDismiss = () => {
    setDismissed(true);
    if (typeof window !== "undefined") window.sessionStorage.setItem(DISMISS_KEY, "1");
  };

  return (
    <div
      data-testid="workflow-setup-banner"
      className="shrink-0 flex items-center gap-3 px-6 py-2.5 bg-blue-500/10 border-b border-blue-500/25"
    >
      <div className="w-7 h-7 rounded-lg bg-blue-500/15 border border-blue-500/25 flex items-center justify-center text-blue-300 shrink-0">
        <Workflow className="w-3.5 h-3.5" />
      </div>
      <p className="text-xs text-slate-200 flex-1 min-w-0">
        <span className="font-semibold text-white">Finish setting up your workspace.</span>{" "}
        <span className="text-slate-400">
          Four questions: where invoices arrive, who finalises them, where results go, and how you
          use chat.
        </span>
      </p>
      <Link
        href={WIZARD_PATH}
        className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-[11px] font-semibold flex items-center gap-1.5 transition-all shrink-0"
      >
        Set up workflow <ArrowRight className="w-3 h-3" />
      </Link>
      <button
        onClick={handleDismiss}
        aria-label="Dismiss workflow setup prompt"
        className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 transition-all shrink-0"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
