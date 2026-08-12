"use client";

import React, { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  History,
  CheckCircle2,
  Sparkles,
  AlertCircle,
  X,
  Lock,
  ExternalLink,
} from "lucide-react";

import {
  TrainerScope,
  TrainerSession,
  VendorOption,
  ExtractedVariable,
  RuleVersion,
  trainerService,
} from "@/lib/trainer-service";

import { useAuth, refreshAuth } from "@/hooks/useAuth";
import {
  PageHeaderActions,
  usePageHeader,
} from "@/components/layout/PageHeaderContext";
import TrainerControlBar from "@/components/trainer/TrainerControlBar";
import PdfViewerPanel from "@/components/trainer/PdfViewerPanel";
import ExtractedFieldsPanel from "@/components/trainer/ExtractedFieldsPanel";
import QnAPanel from "@/components/trainer/QnAPanel";
import RulesRail from "@/components/trainer/RulesRail";
import CommitModal from "@/components/trainer/CommitModal";
import RuleHistoryDrawer from "@/components/trainer/RuleHistoryDrawer";

const WEBSITE_URL = process.env.NEXT_PUBLIC_WEBSITE_URL || "http://localhost:3000";

/**
 * FE Gap 115 — the plans that include the AI Trainer, mirroring the backend's
 * `routers/trainer.py::TRAINER_ALLOWED_PLANS`. The backend is the enforcement
 * (a FE-only gate is bypassable by calling the API directly); this exists so a
 * Free-tier tenant gets a real explanation instead of a raw 403 on page load.
 *
 * `"active"` is included for the same reason it is on the backend: it is the
 * mock/dev billing plan (`dependencies.MOCK_BILLING_PLAN`), not a real one, and
 * `app/settings/subscriptions/page.tsx` already treats it as Pro Combined.
 */
const TRAINER_PLANS = ["pro", "pro_combined", "active"];

/**
 * FE Gap 115: what a tenant without a Trainer plan sees instead of the sandbox.
 *
 * Modelled on `components/settings/ServiceFlowToggles.tsx`'s UpgradeModal --
 * same copy structure, same feature list treatment, same absolute
 * NEXT_PUBLIC_WEBSITE_URL link (see that file for why absolute rather than
 * same-origin). It is a full-page state rather than that file's modal, because
 * there is no underlying screen to return to here: the entire route is gated,
 * so a dismissable overlay would just reveal a sandbox that 403s on every call.
 */
function TrainerUpgradePrompt() {
  return (
    <div className="h-full flex items-center justify-center p-6 bg-[#0B0F19] text-slate-100 font-sans">
      <div className="w-full max-w-md bg-[#0F172A] border border-[#222D3D] rounded-2xl shadow-2xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center shrink-0">
            <Lock className="w-5 h-5 text-violet-400" />
          </div>
          <div className="min-w-0">
            <h2 className="text-white font-semibold text-sm">Upgrade Required</h2>
            <p className="text-slate-400 text-xs">AI Trainer &mdash; Pro &amp; Pro Combined</p>
          </div>
        </div>

        <p className="text-slate-300 text-xs leading-relaxed mb-4">
          The <span className="text-violet-300 font-semibold">AI Trainer</span> lets
          you teach extraction rules in plain language and commit them to your
          template registry. It is included on the{" "}
          <span className="text-white font-semibold">Pro</span> and{" "}
          <span className="text-white font-semibold">Pro Combined</span> plans.
        </p>

        <div className="bg-[#1E293B] border border-[#2D3F55] rounded-xl p-3 mb-5 space-y-1.5">
          {[
            "Teach tenant-wide and per-vendor extraction rules",
            "Cold-start a brand new vendor from one sample invoice",
            "Versioned rule history with rollback and re-audit",
          ].map((feat) => (
            <div key={feat} className="flex items-center gap-2 text-xs text-slate-300">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              {feat}
            </div>
          ))}
        </div>

        <div className="flex gap-3">
          <Link
            href="/settings/subscriptions"
            className="flex-1 py-2 rounded-lg border border-[#2D3F55] text-slate-400 text-xs hover:text-slate-200 hover:border-slate-500 transition-colors flex items-center justify-center"
          >
            View Plan
          </Link>
          <Link
            href="/settings/subscriptions"
            className="flex-1 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium flex items-center justify-center gap-1.5 transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5" />
            Upgrade Now
          </Link>
        </div>
      </div>
    </div>
  );
}

/**
 * Feature 6 Main Page: AI Trainer Interactive Sandbox (app/trainer/page.tsx)
 * 
 * FOR MANAGERS & DEVELOPERS:
 * This component acts as the main application page and state management orchestrator for Feature 6.
 * It manages:
 *   1. Active Rule Scope State ('global' | 'existing_vendor' | 'new_vendor')
 *   2. Active Sandbox Session State & Variables Inspector updates
 *   3. Conversational Chat History & AI Response Synthesis
 *   4. Scope-Aware Registry Commit Modal & Background Re-Audit Notifications
 *   5. Rule History Drawer & Version Rollback (Task 6.7)
 *   6. Auditor Deep-Link Handoff parsing from URL search params (?from=audit&...) (Task 6.8)
 */

function TrainerContent() {
  const searchParams = useSearchParams();

  // FE Gap 110 (closing out Gaps 76/88): this page used to draw its own full
  // h-16 header bar directly below Shell's global Header -- two stacked header
  // bars on one screen. The title/EVOLVE badge now go up to the shared header,
  // and the Rule History / Commit buttons follow them through its actions
  // portal, so nothing is orphaned into a row of its own down here.
  usePageHeader({
    title: "AI Trainer",
    agentIcon: "🧬",
    agentName: "EVOLVE",
    agentRole: "Rules Trainer",
  });

  // FE Gap 115: the Trainer is a paid-tier capability. Read the plan here so
  // the whole screen can be gated below -- the backend already 403s every
  // session-create/commit call for a free tenant (routers/trainer.py::
  // require_paid_plan), so without this the screen would render fully and then
  // fail on its own initialisation with no explanation.
  const { billingPlan, loading: authLoading } = useAuth();
  const hasTrainerPlan = TRAINER_PLANS.includes(billingPlan);

  // Gap 138: if the gate is up, re-fetch identity once — covers the live case
  // where a plan was granted server-side but the tab still has a stale cache.
  const triedStalePlanRefresh = useRef(false);
  useEffect(() => {
    if (authLoading || hasTrainerPlan || triedStalePlanRefresh.current) return;
    triedStalePlanRefresh.current = true;
    void refreshAuth();
  }, [authLoading, hasTrainerPlan]);

  // Core Session State Management
  const [activeScope, setActiveScope] = useState<TrainerScope>("global");
  const [vendors, setVendors] = useState<VendorOption[]>([]);
  const [selectedVendorName, setSelectedVendorName] = useState<string>("");
  const [session, setSession] = useState<TrainerSession | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [selectedVariable, setSelectedVariable] = useState<ExtractedVariable | null>(null);

  /**
   * FE Gap 139: the session-loading handlers below (`handleSelectVendor`,
   * `handleUploadFile`, `handleClearFile`) used to `await` their backend call
   * with no state around it at all. That call runs OCR plus an LLM extraction
   * synchronously, so for its whole duration the screen kept showing whatever
   * was there before the click — a slow-but-working load and a genuinely stuck
   * one looked identical, which is exactly what was reported. This flag is set
   * around all three awaits and drives `PdfViewerPanel`'s loading mode;
   * `loadingFileName` names the file when the pending load is an upload.
   *
   * Scoped to those three handlers deliberately: the initial mount already has
   * its own skeleton, and this is a loading-indicator fix — OCR/extraction
   * itself stays synchronous.
   */
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [loadingFileName, setLoadingFileName] = useState<string | undefined>(undefined);

  // Overlay Component States (Commit Modal & History Drawer)
  const [isCommitModalOpen, setIsCommitModalOpen] = useState(false);
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [ruleHistory, setRuleHistory] = useState<RuleVersion[]>([]);
  const [isSubmittingCommit, setIsSubmittingCommit] = useState(false);

  // Gap 111: the Rules rail starts collapsed -- there is nothing in it until
  // the user teaches something, and the chat beside it uses the space better.
  const [isRulesRailExpanded, setIsRulesRailExpanded] = useState(false);

  // Toast Notification State
  const [toastMessage, setToastMessage] = useState<{ text: string; type: "success" | "info" | "error" } | null>(null);

  const showToast = (text: string, type: "success" | "info" | "error" = "success") => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 5000);
  };

  /**
   * INITIALIZATION EFFECT:
   * 1. Fetches available tenant vendors for Scope 2 dropdown.
   * 2. Checks URL query parameters for deep-links coming from Auditor Console (Task 6.8).
   *    If present (?from=audit&scope=...&vendor_name=...&correction=...), it pre-seeds 
   *    the sandbox session with the suggested scope and correction prompt!
   */
  useEffect(() => {
    // Gap 115: don't initialise a sandbox we're about to hide. Waiting for
    // `authLoading` matters as much as the plan check -- `billingPlan` is ""
    // until GET /api/auth/me resolves, so firing on the first render would
    // start a session for every tenant regardless of plan and only then find
    // out it wasn't allowed (a guaranteed 403 in the console on every free
    // tenant's page load).
    if (authLoading || !hasTrainerPlan) return;

    const init = async () => {
      try {
        const vendorList = await trainerService.getTenantVendors();
        setVendors(vendorList);

        // Task 6.8: Deep-link handling from Auditor Console resolution prompt
        const fromAudit = searchParams.get("from") === "audit";
        const paramScope = (searchParams.get("scope") as TrainerScope) || "existing_vendor";
        const paramVendor = searchParams.get("vendor_name") || vendorList[0]?.name;
        const paramCorrection = searchParams.get("correction");

        if (fromAudit) {
          setActiveScope(paramScope);
          if (paramVendor) setSelectedVendorName(paramVendor);

          const newSession = await trainerService.startSession(paramScope, paramVendor);

          if (paramCorrection) {
            const { updatedSession } = await trainerService.sendChatMessage(
              newSession,
              `Audit Correction: ${paramCorrection}`
            );
            setSession(updatedSession);
          } else {
            setSession(newSession);
          }

          showToast("Session pre-seeded from Auditor correction prompt", "info");
          return;
        }

        // Default Global Scope Initialization
        const defaultSess = await trainerService.startSession("global");
        setSession(defaultSess);
      } catch (err) {
        console.error("Trainer initialization failed", err);
        showToast("Failed to initialize the Trainer session.", "error");
      }
    };

    init();
  }, [searchParams, authLoading, hasTrainerPlan]);

  /**
   * HANDLER: Scope Switching (Task 6.1)
   * Resets active session state and switches between Global, Existing Vendor, and New Vendor modes.
   */
  const handleScopeChange = async (newScope: TrainerScope) => {
    setActiveScope(newScope);
    setSelectedVariable(null);

    let vendor = selectedVendorName;
    // FE Gap 170: `selectedVendorName` can now hold a vendor detected from a New
    // Vendor upload, which by definition has no production invoices yet -- so
    // Existing Vendor must fall back to a known vendor rather than trying to
    // start a production session for one that isn't in the list.
    if (newScope === "existing_vendor" && !vendors.some((v) => v.name === vendor)) {
      vendor = vendors[0]?.name || "";
      setSelectedVendorName(vendor);
    }

    // New Vendor needs an uploaded PDF first; Existing Vendor needs a known vendor.
    if (newScope === "new_vendor") {
      setSession(null);
      return;
    }
    if (newScope === "existing_vendor" && !vendor) {
      setSession(null);
      showToast("No production vendors available to train yet.", "info");
      return;
    }

    // Gap 139: switching *into* Existing Vendor auto-selects a vendor and runs
    // the identical production-invoice load `handleSelectVendor` does — same
    // OCR + extraction wait, same frozen-looking screen — so it gets the same
    // treatment even though the gap's write-up only named the three handlers
    // below. The old session is dropped first so the loading panel isn't
    // sitting on top of the scope the user just navigated away from.
    setSession(null);
    setIsLoadingSession(true);
    try {
      const newSess = await trainerService.startSession(newScope, vendor);
      setSession(newSess);
    } catch (err) {
      console.error("Failed to start session", err);
      showToast("Failed to start the training session.", "error");
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * HANDLER: Production Vendor Selection (Task 6.3)
   * Loads an existing production invoice for the chosen vendor into the sandbox.
   */
  const handleSelectVendor = async (vendorName: string) => {
    setSelectedVendorName(vendorName);
    // Gap 139: clear the outgoing session first, so the panel can't keep
    // showing the previous vendor's invoice underneath the loading state.
    setSelectedVariable(null);
    setSession(null);
    setIsLoadingSession(true);
    try {
      const newSess = await trainerService.startSession("existing_vendor", vendorName);
      setSession(newSess);
    } catch (err) {
      console.error("Failed to load vendor session", err);
      showToast("Failed to load the vendor's production sample.", "error");
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * HANDLER: PDF Upload (Tasks 6.2 & 6.4)
   * Uploads a sample PDF for cold-starting rules (New Vendor) or grounding (Global).
   */
  const handleUploadFile = async (file: File) => {
    // Gap 139: name the file being processed while the upload is in flight.
    setLoadingFileName(file.name);
    setIsLoadingSession(true);
    try {
      const newSess = await trainerService.startSession(activeScope, selectedVendorName, file);
      setSession(newSess);

      /**
       * FE Gap 170: a New Vendor session's vendor is discovered by the backend,
       * not chosen by the user -- `routers/trainer.py::upload_transient_file`
       * reads `vendor_name` out of the extraction result and returns it on the
       * session (`_serialize_session`). Nothing here ever read it, so
       * `selectedVendorName` stayed "" for the whole New Vendor flow: Rule
       * History called `getRuleHistory("new_vendor", "")`, and an empty
       * vendor_name resolves, per `GET /templates/history`, to the tenant's
       * *Global* template -- the drawer confidently showed the wrong timeline.
       * CommitModal and RuleHistoryDrawer read the same value, so all three are
       * fixed by capturing it here, exactly as `handleSelectVendor` does for
       * the Existing Vendor flow.
       *
       * Scoped to new_vendor deliberately: a Global session may also carry a
       * vendor name from its grounding PDF, but Global rules are tenant-wide
       * and must not start keying off whichever sample was uploaded.
       */
      if (activeScope === "new_vendor" && newSess.vendorName) {
        setSelectedVendorName(newSess.vendorName);
      }

      showToast(
        activeScope === "new_vendor" && newSess.vendorName
          ? `Loaded sample file ${file.name} — vendor detected: ${newSess.vendorName}`
          : `Loaded sample file ${file.name}`,
        "info"
      );
    } catch (err) {
      console.error("Failed to load sample file", err);
      showToast("Failed to process the uploaded sample.", "error");
    } finally {
      setIsLoadingSession(false);
      setLoadingFileName(undefined);
    }
  };

  const handleClearFile = async () => {
    setIsLoadingSession(true);
    try {
      const newSess = await trainerService.startSession(activeScope, selectedVendorName);
      setSession(newSess);
      showToast("Cleared grounding document", "info");
    } catch (err) {
      console.error("Failed to clear sample file", err);
      showToast("Failed to clear the sample file.", "error");
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * FE Gap 171: why the chat is unusable right now, or null when it is usable.
   *
   * `session` is null in two ordinary situations -- New Vendor before a PDF is
   * uploaded, and Existing Vendor with no vendor selected -- and the chat panel
   * gave no hint of it: the input accepted text, cleared it on submit, and the
   * message was dropped. Naming the reason here keeps the panel's disabled
   * state, its placeholder and the backstop toast in `handleSendMessage`
   * saying the same thing.
   */
  const chatDisabledReason: string | null = session
    ? null
    : // Gap 139: while a session is loading, the two "nothing selected yet"
      // reasons below are wrong — something *is* in flight, and the vendor
      // handler now clears `session` up front so the stale document can't sit
      // under the loading panel. Say so rather than telling the user to pick a
      // vendor they just picked.
      isLoadingSession
    ? "Loading the sandbox session — one moment."
    : activeScope === "new_vendor"
    ? "Upload a sample invoice PDF to start a New Vendor session before teaching rules."
    : activeScope === "existing_vendor"
    ? "Select a vendor to start a training session before teaching rules."
    : "Starting a training session — one moment.";

  /**
   * HANDLER: Natural Language Chat Correction (Task 6.5)
   * Sends user instruction to LLM trainer agent, updating active rules & variables.
   */
  const handleSendMessage = async (text: string) => {
    // FE Gap 171: this was a bare `if (!session || isSending) return;` -- the
    // panel had already cleared the input by then, so a typed correction with
    // no active session vanished with no feedback at all. The primary fix is in
    // QnAPanel (the input is disabled and explains itself while `chatDisabledReason`
    // is set, so the text is never lost); this stays as the backstop for the
    // suggestion chips and any future caller, and now says why nothing happened.
    if (!session) {
      showToast(chatDisabledReason || "No active training session.", "error");
      return;
    }
    if (isSending) return;
    setIsSending(true);

    try {
      const { updatedSession, newRuleCreated } = await trainerService.sendChatMessage(session, text);
      setSession(updatedSession);

      if (newRuleCreated) {
        showToast(`Rule Candidate Created: "${newRuleCreated}"`, "success");
      }
    } catch (err) {
      console.error("Failed to send chat correction", err);
      showToast("Failed to process your correction. Please try again.", "error");
    } finally {
      setIsSending(false);
    }
  };

  /**
   * HANDLER: Open Rule History Drawer (Task 6.7)
   */
  const handleOpenHistory = async () => {
    setIsHistoryDrawerOpen(true);
    // FE Gap 170: a vendor-scoped history request with an empty vendor_name is
    // resolved by the backend to the tenant's Global template, so this used to
    // present Global's timeline as if it were the new vendor's. With no vendor
    // identified yet there is genuinely nothing to show -- say so.
    if (activeScope !== "global" && !selectedVendorName) {
      setRuleHistory([]);
      showToast(
        activeScope === "new_vendor"
          ? "Upload a sample invoice first — a new vendor has no rule history yet."
          : "Select a vendor to see its rule history.",
        "info"
      );
      return;
    }
    try {
      const history = await trainerService.getRuleHistory(activeScope, selectedVendorName);
      setRuleHistory(history);
    } catch (err) {
      console.error("Failed to load rule history", err);
      setRuleHistory([]);
      showToast("Failed to load rule history.", "error");
    }
  };

  /**
   * HANDLER: Rollback Rule Version (Task 6.7)
   */
  const handleRollback = async (version: RuleVersion) => {
    if (!version.templateId) {
      showToast("Cannot roll back: template reference is missing.", "error");
      return;
    }
    try {
      const result = await trainerService.rollbackTemplate(version.templateId, version.version);
      showToast(
        result.reauditQueued
          ? `Rolled back to rule v${version.version} (now v${result.version}). Background re-audit queued.`
          : `Rolled back to rule v${version.version} (now v${result.version}).`,
        "success"
      );
      // Refresh so the drawer reflects the new current version.
      const history = await trainerService.getRuleHistory(activeScope, selectedVendorName);
      setRuleHistory(history);
      setIsHistoryDrawerOpen(false);
    } catch (err) {
      console.error("Rollback failed", err);
      showToast("Failed to roll back the rule version.", "error");
    }
  };

  /**
   * HANDLER: Scope-Aware Registry Commit (Task 6.6)
   * Commits session rules to database registry and displays scope-aware background re-audit toast.
   */
  const handleConfirmCommit = async () => {
    if (!session) return;
    setIsSubmittingCommit(true);

    try {
      const result = await trainerService.commitSession(session);
      setIsCommitModalOpen(false);

      const versionNote = `v${result.version}`;
      if (result.scope === "global") {
        showToast(
          result.reauditQueued
            ? `Global template committed (${versionNote}). Queued background re-audit across ALL tenant vendors.`
            : `Global template committed (${versionNote}).`,
          "success"
        );
      } else if (result.scope === "existing_vendor") {
        const vendorLabel = result.vendorName || selectedVendorName || "vendor";
        showToast(
          result.reauditQueued
            ? `Vendor template committed (${versionNote}). Queued background re-audit for ${vendorLabel}.`
            : `Vendor template committed (${versionNote}) for ${vendorLabel}.`,
          "success"
        );
      } else {
        showToast(`New vendor template registered (${versionNote}).`, "success");
      }

      // The backend deletes the committed session immediately (routers/trainer.py::
      // trainer_commit()), so it can never be chatted into or re-committed again —
      // leaving it on screen would silently reference a session_id that no longer
      // exists. Clear the workspace back to a clean starting point per scope.
      setSelectedVariable(null);
      if (result.scope === "global") {
        // Global always has an active session (same as the initial page-mount
        // behavior), so start a fresh one immediately rather than showing nothing.
        const freshSession = await trainerService.startSession("global");
        setSession(freshSession);
      } else if (result.scope === "existing_vendor") {
        setSession(null);
        setSelectedVendorName("");
      } else {
        setSession(null);
      }
    } catch (err) {
      console.error("Commit failed", err);
      showToast("Failed to commit rules to the registry.", "error");
    } finally {
      setIsSubmittingCommit(false);
    }
  };

  // FE Gap 115: gate the whole route. Both returns are below every hook,
  // including usePageHeader() above -- the shared header must still name the
  // screen while identity is resolving and on the upgrade prompt, or the top
  // bar would go blank on exactly the screens that most need explaining.
  if (authLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0B0F19]">
        <div className="h-6 w-40 rounded-lg bg-[#1E293B] animate-pulse" />
      </div>
    );
  }

  if (!hasTrainerPlan) {
    return <TrainerUpgradePrompt />;
  }

  return (
    // FE Gap 76: h-full, not h-screen. This page renders inside Shell.tsx's
    // <main className="flex-1 overflow-y-auto p-8">, which has already spent
    // the global Header's 64px plus 32px of padding top and bottom. h-screen
    // (100vh) here made the page ~128px taller than the space it actually has,
    // pushing its own header row -- Rule History / Commit to Template Registry
    // -- out of view. h-full sizes to the container instead of the viewport.
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-hidden font-sans">
      {/* Toast Notification Bar */}
      {toastMessage && (
        <div className="fixed top-5 right-5 z-50 animate-in slide-in-from-top duration-300">
          <div
            className={`flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl border text-xs font-medium ${
              toastMessage.type === "success"
                ? "bg-[#10B981]/15 text-emerald-300 border-[#10B981]/40"
                : toastMessage.type === "error"
                ? "bg-[#EF4444]/15 text-red-300 border-[#EF4444]/40"
                : "bg-[#3B82F6]/15 text-blue-300 border-[#3B82F6]/40"
            }`}
          >
            {toastMessage.type === "error" ? (
              <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
            ) : (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            )}
            <span>{toastMessage.text}</span>
            <button
              onClick={() => setToastMessage(null)}
              className="p-1 hover:bg-white/10 rounded ml-2"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* FE Gap 110: Rule History / Commit to Template Registry render into
          Shell's shared header row. They stay `shrink-0` there for the same
          reason Gap 76 gave them that: they must never be the thing that gets
          squeezed off the row when the title beside them grows. */}
      <PageHeaderActions>
        <button
          type="button"
          onClick={handleOpenHistory}
          aria-label="Rule History"
          title="Rule History"
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-[#1E293B] hover:bg-[#283548] text-slate-200 text-xs font-medium border border-[#222D3D] transition-colors cursor-pointer shrink-0"
        >
          <History className="w-4 h-4 text-[#3B82F6]" />
          {/* Label collapses to the icon on narrow rows; the aria-label keeps
              the button named either way. */}
          <span className="hidden lg:inline">Rule History</span>
        </button>

        <button
          type="button"
          onClick={() => setIsCommitModalOpen(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#10B981] hover:bg-[#059669] text-white text-xs font-medium shadow-md transition-all cursor-pointer shrink-0"
        >
          <Sparkles className="w-4 h-4" />
          <span>Commit to Template Registry</span>
        </button>
      </PageHeaderActions>

      {/* FE Gap 77: one control bar, not a scope block and a grounding block
          the user has to connect for themselves. See TrainerControlBar. */}
      <TrainerControlBar
        activeScope={activeScope}
        onScopeChange={handleScopeChange}
        vendors={vendors}
        selectedVendorName={selectedVendorName}
        onSelectVendor={handleSelectVendor}
        onUploadFile={handleUploadFile}
        onClearFile={handleClearFile}
        activeFileName={session?.fileName}
      />

      {/*
        FE Gap 111 — the agreed workspace: PDF → Extracted Fields → Chat, with
        a collapsed Rules rail on the far right.

        A flex row rather than the old `grid-cols-2`, because the four panels
        have deliberately different sizing rules: the first two are fixed-width
        columns (a document preview and a field list have a natural width and
        gain nothing from more), chat takes everything left over, and the rail
        sizes itself from its own collapsed/expanded state. Expressing that as
        grid template columns would have meant recomputing the template string
        every time the rail toggles.

        Every panel is `min-h-0` inside a `min-h-0` row, which is what lets each
        one scroll internally instead of growing the page -- Gap 76's geometry
        (Shell's <main> must not become scrollable on this route) still holds,
        and a long PDF no longer moves anything beside it (Gap 111.2).

        Below `xl` this stacks into a normal scrolling column: three fixed
        columns plus a rail do not fit a laptop width, and squeezing them would
        undo the readability this gap is about.
      */}
      <main className="flex-1 p-3 min-h-0 overflow-y-auto xl:overflow-hidden flex flex-col xl:flex-row gap-3">
        {/* 1. Document preview — fixed ~300px, own internal scroll */}
        <div className="h-[420px] xl:h-full min-h-0 xl:w-[300px] xl:shrink-0">
          <PdfViewerPanel
            fileName={session?.fileName}
            pdfUrl={session?.pdfUrl}
            isGlobalScopeNoPdf={!session?.pdfUrl}
            selectedVariable={selectedVariable}
            scope={activeScope}
            vendorName={selectedVendorName}
            isLoadingSession={isLoadingSession}
            loadingFileName={loadingFileName}
          />
        </div>

        {/* 2. Extracted fields — its own column, no longer buried under the PDF */}
        <div className="h-[280px] xl:h-full min-h-0 xl:w-[220px] xl:shrink-0">
          <ExtractedFieldsPanel
            variables={session?.variables || []}
            selectedVariableId={selectedVariable?.id}
            onSelectVariable={(v) => setSelectedVariable(v)}
          />
        </div>

        {/* 3. Chat — everything left over */}
        <div className="h-[480px] xl:h-full min-h-0 xl:flex-1 xl:min-w-0">
          <QnAPanel
            chatHistory={session?.chatHistory || []}
            onSendMessage={handleSendMessage}
            isSending={isSending}
            disabledReason={chatDisabledReason}
          />
        </div>

        {/* 4. Rule candidates — slim rail, count badge only until expanded.
               Below xl there is no fourth column, so the same component
               renders as a plain always-open panel at the end of the stack
               rather than disappearing (see RulesRail's `stacked` prop). */}
        <div className="hidden xl:block h-full min-h-0">
          <RulesRail
            activeRules={session?.activeRules || []}
            isExpanded={isRulesRailExpanded}
            onToggle={() => setIsRulesRailExpanded((v) => !v)}
          />
        </div>
        <div className="xl:hidden h-[220px] min-h-0">
          <RulesRail
            activeRules={session?.activeRules || []}
            isExpanded
            onToggle={() => undefined}
            stacked
          />
        </div>
      </main>

      {/* Commit Confirmation Overlay Modal */}
      <CommitModal
        isOpen={isCommitModalOpen}
        onClose={() => setIsCommitModalOpen(false)}
        onConfirm={handleConfirmCommit}
        scope={activeScope}
        vendorName={selectedVendorName}
        activeRules={session?.activeRules || []}
        isSubmitting={isSubmittingCommit}
      />

      {/* Rule Version History & Rollback Drawer */}
      <RuleHistoryDrawer
        isOpen={isHistoryDrawerOpen}
        onClose={() => setIsHistoryDrawerOpen(false)}
        history={ruleHistory}
        scope={activeScope}
        vendorName={selectedVendorName}
        onRollback={handleRollback}
      />
    </div>
  );
}

export default function TrainerPage() {
  return (
    <Suspense fallback={<div className="p-8 text-white text-xs">Loading AI Trainer...</div>}>
      <TrainerContent />
    </Suspense>
  );
}
