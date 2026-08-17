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
  ShieldAlert,
} from "lucide-react";

import {
  TrainerScope,
  TrainerSession,
  TrainerAlert,
  VendorOption,
  ExtractedVariable,
  PreviewResult,
  RuleVersion,
  trainerService,
} from "@/lib/trainer-service";

import { useAuth, refreshAuth } from "@/hooks/useAuth";
import {
  PageHeaderActions,
  usePageHeader,
} from "@/components/layout/PageHeaderContext";
import TrainerControlBar, {
  TrainerSessionMode,
  VendorPanelTab,
} from "@/components/trainer/TrainerControlBar";
import ChatResponseStylePanel from "@/components/trainer/ChatResponseStylePanel";
import PdfViewerPanel from "@/components/trainer/PdfViewerPanel";
import ExtractedFieldsPanel from "@/components/trainer/ExtractedFieldsPanel";
import TrainerEntryPanel from "@/components/trainer/TrainerEntryPanel";
import AlertListPanel from "@/components/trainer/AlertListPanel";
import AlertCorrectionModal from "@/components/trainer/AlertCorrectionModal";
import FlagMissedAlertModal from "@/components/trainer/FlagMissedAlertModal";
import QaChatPanel from "@/components/trainer/QaChatPanel";
import RulesRail from "@/components/trainer/RulesRail";
import CommitModal from "@/components/trainer/CommitModal";
import RuleHistoryDrawer from "@/components/trainer/RuleHistoryDrawer";

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
          you correct the alerts on a real invoice and turn those corrections into
          rules. It is included on the{" "}
          <span className="text-white font-semibold">Pro</span> and{" "}
          <span className="text-white font-semibold">Pro Combined</span> plans.
        </p>

        <div className="bg-[#1E293B] border border-[#2D3F55] rounded-xl p-3 mb-5 space-y-1.5">
          {[
            "Correct a real alert on a real invoice",
            "See a rule's effect on your history before saving it",
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
 * FE Gap 232: what a user *without* the training permission sees.
 *
 * The route previously gated on billing plan alone. `can_train` was never
 * checked here, so anyone in a Pro tenant could navigate to /trainer directly,
 * see the whole sandbox render, pick an invoice, fill in a correction — and only
 * then hit a 403 from the first write call. The backend was always the real
 * enforcement (`require_can_train` on commit), so nothing could actually be
 * written; but presenting a fully interactive rule-authoring screen to someone
 * who cannot save anything is a permission boundary that exists only in the API.
 *
 * Deliberately the same full-page-state pattern as `TrainerUpgradePrompt` above
 * rather than a new one: both are "this entire route is not for you", and a
 * dismissable overlay would just reveal a screen that fails on first use.
 */
function TrainerPermissionPrompt() {
  return (
    <div className="h-full flex items-center justify-center p-6 bg-[#0B0F19] text-slate-100 font-sans">
      <div className="w-full max-w-md bg-[#0F172A] border border-[#222D3D] rounded-2xl shadow-2xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center shrink-0">
            <ShieldAlert className="w-5 h-5 text-amber-400" />
          </div>
          <div className="min-w-0">
            <h2 className="text-white font-semibold text-sm">Training Permission Required</h2>
            <p className="text-slate-400 text-xs">AI Trainer</p>
          </div>
        </div>

        <p className="text-slate-300 text-xs leading-relaxed mb-4">
          The AI Trainer changes how invoices are read for your whole workspace, so
          it needs the <span className="text-amber-300 font-semibold">Train</span>{" "}
          permission. Your account doesn&apos;t have it yet.
        </p>

        <div className="bg-[#1E293B] border border-[#2D3F55] rounded-xl p-3 mb-5">
          <p className="text-xs text-slate-400 leading-relaxed">
            An Admin can grant it from the Admin console. You can still review
            invoices and use Chat in the meantime.
          </p>
        </div>

        <div className="flex gap-3">
          <Link
            href="/dashboard"
            className="flex-1 py-2 rounded-lg border border-[#2D3F55] text-slate-400 text-xs hover:text-slate-200 hover:border-slate-500 transition-colors flex items-center justify-center"
          >
            Back to Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}

/**
 * Feature 14 Main Page: AI Trainer — alert-anchored rule creation
 * (app/trainer/page.tsx)
 *
 * FOR MANAGERS & DEVELOPERS:
 * The orchestrator for the redesigned Trainer. What it manages:
 *   1. The route's two gates — billing plan (Gap 115) and `can_train` (Gap 232).
 *   2. Session entry: pick a vendor invoice, or upload a PDF. Both land on the
 *      same state — that invoice's alerts, beside that invoice's PDF.
 *   3. The four correction flows, all of which only *stage* a rule.
 *   4. The preview-before-commit gate, which every correction must clear.
 *   5. The QA chat lane, structurally separate from rule creation.
 *   6. Rule history & rollback.
 *
 * WHAT IS DELIBERATELY ABSENT: a Global rule-creation destination. It was
 * removed from the backend (410 on session create, 400 on commit) because a
 * rule with no document and no vendor behind it is anchored to nothing. Rules
 * already committed to a Global template still apply and are still readable in
 * Rule History — only authoring new ones is gone.
 */
function TrainerContent() {
  const searchParams = useSearchParams();

  usePageHeader({
    title: "AI Trainer",
    agentIcon: "🧬",
    agentName: "EVOLVE",
    agentRole: "Rules Trainer",
  });

  // Two independent gates, read together. `canTrain` is FE Gap 232 — see
  // TrainerPermissionPrompt above for why the plan check alone was not enough.
  const { billingPlan, canTrain, loading: authLoading } = useAuth();
  const hasTrainerPlan = TRAINER_PLANS.includes(billingPlan);
  const isGated = !hasTrainerPlan || !canTrain;

  // Gap 138: if a gate is up, re-fetch identity once — covers the live case
  // where a plan or permission was granted server-side but the tab still has a
  // stale cache.
  const triedStaleRefresh = useRef(false);
  useEffect(() => {
    if (authLoading || !isGated || triedStaleRefresh.current) return;
    triedStaleRefresh.current = true;
    void refreshAuth();
  }, [authLoading, isGated]);

  // ── Session state ──────────────────────────────────────────────────────
  const [vendors, setVendors] = useState<VendorOption[]>([]);
  const [selectedVendorName, setSelectedVendorName] = useState<string>("");
  const [session, setSession] = useState<TrainerSession | null>(null);
  const [panelTab, setPanelTab] = useState<VendorPanelTab>("rules");
  const [sessionMode, setSessionMode] = useState<TrainerSessionMode>("rule_creation");
  const [selectedVariable, setSelectedVariable] = useState<ExtractedVariable | null>(null);
  const [isSending, setIsSending] = useState(false);

  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [loadingFileName, setLoadingFileName] = useState<string | undefined>(undefined);

  // ── Correction modals ──────────────────────────────────────────────────
  const [correctionAlert, setCorrectionAlert] = useState<TrainerAlert | null>(null);
  const [isFlagMissedOpen, setIsFlagMissedOpen] = useState(false);
  const [prefillField, setPrefillField] = useState<string | null>(null);
  const [isStaging, setIsStaging] = useState(false);
  const [stagingError, setStagingError] = useState<string | null>(null);

  // ── Preview / commit ───────────────────────────────────────────────────
  const [isCommitModalOpen, setIsCommitModalOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isSubmittingCommit, setIsSubmittingCommit] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);

  // ── History drawer ─────────────────────────────────────────────────────
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [ruleHistory, setRuleHistory] = useState<RuleVersion[]>([]);

  const [isRulesRailExpanded, setIsRulesRailExpanded] = useState(false);

  const [toastMessage, setToastMessage] = useState<{
    text: string;
    type: "success" | "info" | "error";
  } | null>(null);

  const showToast = (text: string, type: "success" | "info" | "error" = "success") => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 5000);
  };

  /** Pulls a usable message out of an axios error, including the structured
   *  400 bodies the correction endpoints return. */
  const errorMessage = (err: any, fallback: string): string => {
    const detail = err?.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      if (typeof detail.detail === "string") return detail.detail;
      if (detail.flagged_rule) return `Rule rejected. Flagged: "${detail.flagged_rule}"`;
    }
    return fallback;
  };

  /**
   * INITIALISATION.
   *
   * Only the vendor list is fetched — no session is started. That is a real
   * change: the page used to open a Global session on mount, which is now a 410,
   * and more importantly the redesign has no "default" session. Every session is
   * anchored to a document the user chose, so the landing state is the picker.
   *
   * Deep links are honoured here, including the chat lane's handoff
   * (`?invoice_id=…&field=…&flag_missed=1`), which arrives when a chat complaint
   * turned out to be an extraction problem.
   */
  useEffect(() => {
    if (authLoading || isGated) return;

    const init = async () => {
      try {
        const vendorList = await trainerService.getTenantVendors();
        setVendors(vendorList);

        const panelParam = searchParams.get("panel");
        if (panelParam === "chat-style") setPanelTab("style");

        const invoiceId = searchParams.get("invoice_id");
        if (invoiceId) {
          setIsLoadingSession(true);
          try {
            const newSess = await trainerService.startSessionFromInvoice(invoiceId);
            setSession(newSess);
            if (newSess.vendorName) setSelectedVendorName(newSess.vendorName);

            // Handoff from the chat lane's "the PDF disagrees" verdict: open the
            // missed-alert form straight away, pre-filled with the field the
            // backend named, so the user doesn't have to re-find it.
            if (searchParams.get("flag_missed") === "1") {
              setPrefillField(searchParams.get("field"));
              setIsFlagMissedOpen(true);
              showToast("Opened from Chat — tell us which check should have caught this.", "info");
            }
          } finally {
            setIsLoadingSession(false);
          }
          return;
        }

        // Otherwise pre-select the first vendor so the invoice picker has
        // something in it, but do NOT open a session — choosing the document is
        // the user's decision, and auto-opening one would re-introduce the
        // "latest invoice only" behaviour this redesign removed.
        if (vendorList.length > 0) setSelectedVendorName(vendorList[0].name);
      } catch (err) {
        console.error("Trainer initialization failed", err);
        showToast("Failed to load your vendors.", "error");
      }
    };

    init();
  }, [searchParams, authLoading, isGated]);

  // ── Session entry ──────────────────────────────────────────────────────

  const handlePickInvoice = async (invoiceId: string) => {
    setSelectedVariable(null);
    setSession(null);
    setIsLoadingSession(true);
    try {
      const newSess = await trainerService.startSessionFromInvoice(invoiceId, sessionMode);
      setSession(newSess);
      if (newSess.vendorName) setSelectedVendorName(newSess.vendorName);
    } catch (err: any) {
      console.error("Failed to open invoice session", err);
      showToast(errorMessage(err, "Failed to open that invoice for training."), "error");
    } finally {
      setIsLoadingSession(false);
    }
  };

  const handleUploadFile = async (file: File) => {
    setSelectedVariable(null);
    setSession(null);
    setLoadingFileName(file.name);
    setIsLoadingSession(true);
    try {
      const newSess = await trainerService.startSessionFromUpload(file);
      setSession(newSess);
      // FE Gap 170: an upload's vendor is discovered by the backend, not chosen
      // by the user. Capturing it here is what keeps Rule History and the commit
      // dialog pointed at the right template.
      if (newSess.vendorName) setSelectedVendorName(newSess.vendorName);
      showToast(
        newSess.vendorName
          ? `Loaded ${file.name} — vendor detected: ${newSess.vendorName}`
          : `Loaded ${file.name}`,
        "info"
      );
    } catch (err: any) {
      console.error("Failed to process upload", err);
      showToast(errorMessage(err, "Failed to process the uploaded sample."), "error");
    } finally {
      setIsLoadingSession(false);
      setLoadingFileName(undefined);
    }
  };

  const handleChangeDocument = () => {
    setSession(null);
    setSelectedVariable(null);
    setPreview(null);
  };

  const handleSessionModeChange = async (mode: TrainerSessionMode) => {
    setSessionMode(mode);
    if (!session) return;
    try {
      const updated = await trainerService.setSessionMode(session.sessionId, mode);
      setSession({ ...session, ...updated });
    } catch (err) {
      console.error("Failed to set session mode", err);
      showToast("Failed to switch trainer mode.", "error");
    }
  };

  // ── Corrections (all four only stage) ──────────────────────────────────

  const afterStage = (updatedSession: TrainerSession, label: string) => {
    setSession(updatedSession);
    // Any staged change invalidates a previous preview server-side, so drop the
    // local copy too rather than letting a stale impact estimate be re-opened.
    setPreview(null);
    setCorrectionAlert(null);
    setIsFlagMissedOpen(false);
    setPrefillField(null);
    showToast(`${label} staged. Review it before committing.`, "success");
  };

  const handleSubmitTolerance = async (payload: { absTol: number; relTol: number }) => {
    if (!session || !correctionAlert?.type) return;
    setIsStaging(true);
    setStagingError(null);
    try {
      const { updatedSession } = await trainerService.correctTolerance(session.sessionId, {
        alertType: correctionAlert.type,
        field: correctionAlert.field,
        absTol: payload.absTol,
        relTol: payload.relTol,
      });
      afterStage(updatedSession, "Tolerance change");
    } catch (err: any) {
      setStagingError(errorMessage(err, "Couldn't stage that tolerance change."));
    } finally {
      setIsStaging(false);
    }
  };

  const handleSubmitThreshold = async (payload: { threshold: number }) => {
    if (!session) return;
    setIsStaging(true);
    setStagingError(null);
    try {
      const { updatedSession } = await trainerService.correctConfidenceThreshold(
        session.sessionId,
        { threshold: payload.threshold, field: correctionAlert?.field }
      );
      afterStage(updatedSession, "Confidence threshold change");
    } catch (err: any) {
      setStagingError(errorMessage(err, "Couldn't stage that threshold change."));
    } finally {
      setIsStaging(false);
    }
  };

  const handleSubmitOverride = async (payload: { severity?: string; message?: string }) => {
    if (!session || !correctionAlert?.type) return;
    setIsStaging(true);
    setStagingError(null);
    try {
      const { updatedSession } = await trainerService.correctAlertOverride(session.sessionId, {
        alertType: correctionAlert.type,
        field: correctionAlert.field,
        severity: payload.severity,
        message: payload.message,
      });
      afterStage(updatedSession, "Severity / message change");
    } catch (err: any) {
      setStagingError(errorMessage(err, "Couldn't stage that change."));
    } finally {
      setIsStaging(false);
    }
  };

  const handleFlagMissed = async (payload: {
    alertType: string;
    field: string;
    context: string;
  }) => {
    if (!session) return;
    setIsStaging(true);
    setStagingError(null);
    try {
      const { updatedSession } = await trainerService.flagMissedAlert(session.sessionId, payload);
      afterStage(updatedSession, "Missed-alert rule");
    } catch (err: any) {
      // The backend fails closed here on an LLM failure (502) — nothing is
      // staged, and saying so plainly matters more than a generic error.
      setStagingError(
        errorMessage(err, "Couldn't turn that into a rule right now — nothing was changed.")
      );
    } finally {
      setIsStaging(false);
    }
  };

  // ── Preview → commit ───────────────────────────────────────────────────

  /**
   * Opening the commit dialog *runs the preview*. There is no path to the
   * confirm button that skips it: the token it returns is what the commit is
   * sent with, and the backend 409s if the rules moved since.
   */
  const handleOpenCommit = async () => {
    if (!session) return;
    setIsCommitModalOpen(true);
    setCommitError(null);
    setPreview(null);
    setIsLoadingPreview(true);
    try {
      const result = await trainerService.previewSession(session.sessionId);
      setPreview(result);
    } catch (err: any) {
      // Gap 217's guardrail now runs at preview time, so a rejected rule is
      // surfaced here — while the user is still editing — rather than at commit.
      setCommitError(errorMessage(err, "Couldn't build a preview for these rules."));
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const handleConfirmCommit = async () => {
    if (!session || !preview) return;
    setIsSubmittingCommit(true);
    setCommitError(null);

    try {
      const result = await trainerService.commitSession(session, preview.previewToken);
      setIsCommitModalOpen(false);

      const versionNote = `v${result.version}`;
      const vendorLabel = result.vendorName || selectedVendorName || "this vendor";
      showToast(
        result.reauditQueued
          ? `Committed (${versionNote}). Background re-audit queued for ${vendorLabel}.`
          : `Committed (${versionNote}) for ${vendorLabel}.`,
        "success"
      );

      // The backend deletes the committed session immediately, so it can never
      // be corrected into or re-committed — leaving it on screen would reference
      // a session_id that no longer exists.
      setSelectedVariable(null);
      setPreview(null);
      setSession(null);
    } catch (err: any) {
      console.error("Commit failed", err);
      setCommitError(
        errorMessage(err, "Failed to commit these rules. Nothing was changed.")
      );
    } finally {
      setIsSubmittingCommit(false);
    }
  };

  // ── QA chat ────────────────────────────────────────────────────────────

  const chatDisabledReason: string | null = session
    ? null
    : isLoadingSession
    ? "Loading the session — one moment."
    : "Pick an invoice or upload a PDF first.";

  const handleSendMessage = async (text: string) => {
    if (!session) {
      showToast(chatDisabledReason || "No active session.", "error");
      return;
    }
    if (isSending) return;
    setIsSending(true);
    try {
      const { updatedSession } = await trainerService.sendChatMessage(session, text);
      setSession(updatedSession);
    } catch (err: any) {
      console.error("Failed to send message", err);
      showToast(errorMessage(err, "Failed to answer that question. Please try again."), "error");
    } finally {
      setIsSending(false);
    }
  };

  // ── Rule history ───────────────────────────────────────────────────────

  const historyScope: TrainerScope = session?.scope ?? "existing_vendor";

  const handleOpenHistory = async () => {
    setIsHistoryDrawerOpen(true);
    if (!selectedVendorName) {
      setRuleHistory([]);
      showToast("Open an invoice first — rule history is per vendor.", "info");
      return;
    }
    try {
      setRuleHistory(await trainerService.getRuleHistory(historyScope, selectedVendorName));
    } catch (err) {
      console.error("Failed to load rule history", err);
      setRuleHistory([]);
      showToast("Failed to load rule history.", "error");
    }
  };

  const handleRollback = async (version: RuleVersion) => {
    if (!version.templateId) {
      showToast("Cannot roll back: template reference is missing.", "error");
      return;
    }
    try {
      const result = await trainerService.rollbackTemplate(version.templateId, version.version);
      showToast(
        result.reauditQueued
          ? `Rolled back to v${version.version} (now v${result.version}). Re-audit queued.`
          : `Rolled back to v${version.version} (now v${result.version}).`,
        "success"
      );
      setRuleHistory(await trainerService.getRuleHistory(historyScope, selectedVendorName));
      setIsHistoryDrawerOpen(false);
    } catch (err) {
      console.error("Rollback failed", err);
      showToast("Failed to roll back the rule version.", "error");
    }
  };

  // ── Gates. Both returns sit below every hook, including usePageHeader(),
  //    so the shared header still names the screen on the gated states. ────
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

  // FE Gap 232: the permission gate. Checked after the plan gate so a Free-tier
  // tenant still gets the upgrade explanation rather than a permissions one.
  if (!canTrain) {
    return <TrainerPermissionPrompt />;
  }

  const isStyleTab = panelTab === "style";
  const showQa = sessionMode === "qa_test";
  const stagedRuleCount = Math.max(
    0,
    (session?.activeRulesDetailed?.length ?? 0) -
      (session?.activeRulesDetailed?.filter((r) => r.origin === "legacy_text").length ?? 0)
  );

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-hidden font-sans">
      {/* Toast */}
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

      {/* FE Gap 110: these render into Shell's shared header row. */}
      <PageHeaderActions>
        <button
          type="button"
          onClick={handleOpenHistory}
          aria-label="Rule History"
          title="Rule History"
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-[#1E293B] hover:bg-[#283548] text-slate-200 text-xs font-medium border border-[#222D3D] transition-colors cursor-pointer shrink-0"
        >
          <History className="w-4 h-4 text-[#3B82F6]" />
          <span className="hidden lg:inline">Rule History</span>
        </button>

        <button
          type="button"
          data-testid="trainer-review-commit"
          onClick={handleOpenCommit}
          disabled={!session}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#10B981] hover:bg-[#059669] disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium shadow-md transition-all cursor-pointer shrink-0"
        >
          <Sparkles className="w-4 h-4" />
          <span>Review &amp; Commit</span>
        </button>
      </PageHeaderActions>

      <TrainerControlBar
        panelTab={panelTab}
        onPanelTabChange={setPanelTab}
        sessionMode={sessionMode}
        onSessionModeChange={handleSessionModeChange}
        vendorName={session?.vendorName || selectedVendorName}
        activeFileName={session?.fileName}
        onChangeDocument={handleChangeDocument}
        hasSession={!!session}
        disabled={isLoadingSession}
      />

      {/*
        The workspace. Same flex-row geometry FE Gap 111 established (each panel
        `min-h-0` inside a `min-h-0` row so every one scrolls internally rather
        than growing the page, per Gap 76), with the alert list taking the slot
        the old free-text chat used to occupy.

        Before any document is chosen the whole row is the entry picker — there
        is no half-populated workspace to look at, because with no invoice there
        are no alerts and no fields.
      */}
      <main className="flex-1 p-3 min-h-0 overflow-y-auto xl:overflow-hidden flex flex-col xl:flex-row gap-3">
        {!session && !isLoadingSession ? (
          <div className="flex-1 min-h-0 rounded-2xl border border-[#1E2D45] bg-[#070D1A]/90">
            <TrainerEntryPanel
              vendors={vendors}
              selectedVendorName={selectedVendorName}
              onSelectVendor={setSelectedVendorName}
              onPickInvoice={handlePickInvoice}
              onUploadFile={handleUploadFile}
              isBusy={isLoadingSession}
            />
          </div>
        ) : (
          <>
            {/* 1. The document — always beside whatever is being corrected. */}
            <div className="h-[420px] xl:h-full min-h-0 xl:w-[300px] xl:shrink-0">
              <PdfViewerPanel
                fileName={session?.fileName}
                pdfUrl={session?.pdfUrl}
                isGlobalScopeNoPdf={!session?.pdfUrl}
                selectedVariable={selectedVariable}
                scope={session?.scope}
                vendorName={session?.vendorName || selectedVendorName}
                isLoadingSession={isLoadingSession}
                loadingFileName={loadingFileName}
              />
            </div>

            {/* 2. Extracted fields — hidden on the chat-style tab, which is
                   about answering behaviour and has nothing to do with them. */}
            {!isStyleTab && (
              <div className="h-[280px] xl:h-full min-h-0 xl:w-[220px] xl:shrink-0">
                <ExtractedFieldsPanel
                  variables={session?.variables || []}
                  selectedVariableId={selectedVariable?.id}
                  onSelectVariable={(v) => setSelectedVariable(v)}
                />
              </div>
            )}

            {/* 3. The main work surface. */}
            {isStyleTab ? (
              <div className="h-[480px] xl:h-full min-h-0 xl:flex-1 overflow-y-auto rounded-xl border border-[#1E2D45] bg-[#0D131F]">
                {session && (
                  <ChatResponseStylePanel
                    sessionId={session.sessionId}
                    onSaved={() => showToast("Chat response style saved.", "success")}
                  />
                )}
              </div>
            ) : showQa ? (
              <div className="h-[480px] xl:h-full min-h-0 xl:flex-1 xl:min-w-[350px]">
                <QaChatPanel
                  chatHistory={session?.chatHistory || []}
                  onSendMessage={handleSendMessage}
                  isSending={isSending}
                  disabledReason={chatDisabledReason}
                  canTrain={canTrain}
                  vendorName={session?.vendorName}
                />
              </div>
            ) : (
              <div className="h-[480px] xl:h-full min-h-0 xl:flex-1 xl:min-w-[320px]">
                <AlertListPanel
                  alerts={session?.alerts || []}
                  onTrainOnAlert={(alert) => {
                    setStagingError(null);
                    setCorrectionAlert(alert);
                  }}
                  onFlagMissed={() => {
                    setStagingError(null);
                    setPrefillField(null);
                    setIsFlagMissedOpen(true);
                  }}
                  stagedRuleCount={stagedRuleCount}
                  disabled={isLoadingSession}
                />
              </div>
            )}

            {/* 4. Rules rail — what this template already carries. */}
            {!isStyleTab && (
              <>
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
              </>
            )}
          </>
        )}
      </main>

      {/* ── Correction modals ─────────────────────────────────────────── */}
      <AlertCorrectionModal
        isOpen={correctionAlert !== null}
        alert={correctionAlert}
        onClose={() => {
          setCorrectionAlert(null);
          setStagingError(null);
        }}
        onSubmitTolerance={handleSubmitTolerance}
        onSubmitThreshold={handleSubmitThreshold}
        onSubmitOverride={handleSubmitOverride}
        isSubmitting={isStaging}
        errorText={stagingError}
      />

      <FlagMissedAlertModal
        isOpen={isFlagMissedOpen}
        onClose={() => {
          setIsFlagMissedOpen(false);
          setPrefillField(null);
          setStagingError(null);
        }}
        onSubmit={handleFlagMissed}
        variables={session?.variables || []}
        isSubmitting={isStaging}
        errorText={stagingError}
        prefillField={prefillField}
      />

      {/* ── The gate everything funnels through ───────────────────────── */}
      <CommitModal
        isOpen={isCommitModalOpen}
        onClose={() => setIsCommitModalOpen(false)}
        onConfirm={handleConfirmCommit}
        scope={session?.scope ?? "existing_vendor"}
        vendorName={session?.vendorName || selectedVendorName}
        preview={preview}
        isLoadingPreview={isLoadingPreview}
        isSubmitting={isSubmittingCommit}
        errorText={commitError}
      />

      <RuleHistoryDrawer
        isOpen={isHistoryDrawerOpen}
        onClose={() => setIsHistoryDrawerOpen(false)}
        history={ruleHistory}
        scope={historyScope}
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
