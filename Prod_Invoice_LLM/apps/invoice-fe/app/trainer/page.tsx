"use client";

import React, { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  GraduationCap,
  History,
  CheckCircle2,
  Sparkles,
  AlertCircle,
  X,
} from "lucide-react";

import {
  TrainerScope,
  TrainerSession,
  VendorOption,
  ExtractedVariable,
  RuleVersion,
  trainerService,
} from "@/lib/trainer-service";

import ScopeSelector from "@/components/trainer/ScopeSelector";
import TrainerUploader from "@/components/trainer/TrainerUploader";
import PdfViewerPanel from "@/components/trainer/PdfViewerPanel";
import QnAPanel from "@/components/trainer/QnAPanel";
import CommitModal from "@/components/trainer/CommitModal";
import RuleHistoryDrawer from "@/components/trainer/RuleHistoryDrawer";

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

  // Core Session State Management
  const [activeScope, setActiveScope] = useState<TrainerScope>("global");
  const [vendors, setVendors] = useState<VendorOption[]>([]);
  const [selectedVendorName, setSelectedVendorName] = useState<string>("");
  const [session, setSession] = useState<TrainerSession | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [selectedVariable, setSelectedVariable] = useState<ExtractedVariable | null>(null);

  // Overlay Component States (Commit Modal & History Drawer)
  const [isCommitModalOpen, setIsCommitModalOpen] = useState(false);
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [ruleHistory, setRuleHistory] = useState<RuleVersion[]>([]);
  const [isSubmittingCommit, setIsSubmittingCommit] = useState(false);

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
  }, [searchParams]);

  /**
   * HANDLER: Scope Switching (Task 6.1)
   * Resets active session state and switches between Global, Existing Vendor, and New Vendor modes.
   */
  const handleScopeChange = async (newScope: TrainerScope) => {
    setActiveScope(newScope);
    setSelectedVariable(null);

    let vendor = selectedVendorName;
    if (newScope === "existing_vendor" && !vendor && vendors.length > 0) {
      vendor = vendors[0].name;
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

    try {
      const newSess = await trainerService.startSession(newScope, vendor);
      setSession(newSess);
    } catch (err) {
      console.error("Failed to start session", err);
      showToast("Failed to start the training session.", "error");
    }
  };

  /**
   * HANDLER: Production Vendor Selection (Task 6.3)
   * Loads an existing production invoice for the chosen vendor into the sandbox.
   */
  const handleSelectVendor = async (vendorName: string) => {
    setSelectedVendorName(vendorName);
    try {
      const newSess = await trainerService.startSession("existing_vendor", vendorName);
      setSession(newSess);
    } catch (err) {
      console.error("Failed to load vendor session", err);
      showToast("Failed to load the vendor's production sample.", "error");
    }
  };

  /**
   * HANDLER: PDF Upload (Tasks 6.2 & 6.4)
   * Uploads a sample PDF for cold-starting rules (New Vendor) or grounding (Global).
   */
  const handleUploadFile = async (file: File) => {
    try {
      const newSess = await trainerService.startSession(activeScope, selectedVendorName, file);
      setSession(newSess);
      showToast(`Loaded sample file ${file.name}`, "info");
    } catch (err) {
      console.error("Failed to load sample file", err);
      showToast("Failed to process the uploaded sample.", "error");
    }
  };

  /**
   * HANDLER: Natural Language Chat Correction (Task 6.5)
   * Sends user instruction to LLM trainer agent, updating active rules & variables.
   */
  const handleSendMessage = async (text: string) => {
    if (!session || isSending) return;
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

  return (
    <div className="h-screen flex flex-col bg-[#0B0F19] text-slate-100 overflow-hidden font-sans">
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

      {/* Top Application Page Header */}
      <header className="h-16 border-b border-[#222D3D] bg-[#0F172A]/70 backdrop-blur-md px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-[#3B82F6]">
            <GraduationCap className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-white tracking-wide flex items-center gap-2">
              <span>AI Trainer Interactive Sandbox</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                Interactive Fine-Tuning
              </span>
            </h1>
            <p className="text-xs text-slate-400">
              Refine extraction rules & constraints through natural language chat.
            </p>
          </div>
        </div>

        {/* Header Action Buttons (Rule History & Commit to Registry) */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleOpenHistory}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-[#1E293B] hover:bg-[#283548] text-slate-200 text-xs font-medium border border-[#222D3D] transition-colors cursor-pointer"
          >
            <History className="w-4 h-4 text-[#3B82F6]" />
            <span>Rule History</span>
          </button>

          <button
            type="button"
            onClick={() => setIsCommitModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#10B981] hover:bg-[#059669] text-white text-xs font-medium shadow-md transition-all cursor-pointer"
          >
            <Sparkles className="w-4 h-4" />
            <span>Commit to Template Registry</span>
          </button>
        </div>
      </header>

      {/* Secondary Controls Bar: Scope Selector & Document Uploader */}
      <div className="p-4 border-b border-[#222D3D] bg-[#0D131F]/90 space-y-3 shrink-0">
        {/* Task 6.1: 3-Way Scope Selector */}
        <ScopeSelector activeScope={activeScope} onScopeChange={handleScopeChange} />

        {/* Tasks 6.2 - 6.4: Scope-Aware Document Uploader / Vendor Picker */}
        <TrainerUploader
          scope={activeScope}
          vendors={vendors}
          selectedVendorName={selectedVendorName}
          onSelectVendor={handleSelectVendor}
          onUploadFile={handleUploadFile}
          activeFileName={session?.fileName}
        />
      </div>

      {/* Main 50/50 Split-Screen Workspace Layout */}
      <main className="flex-1 p-4 grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-0 overflow-hidden">
        {/* Left 50% Panel: PDF Viewer Canvas / Global Empty State */}
        <div className="h-full min-h-0">
          <PdfViewerPanel
            fileName={session?.fileName}
            pdfUrl={session?.pdfUrl}
            isGlobalScopeNoPdf={activeScope === "global" && !session?.pdfUrl}
            selectedVariable={selectedVariable}
            variables={session?.variables}
          />
        </div>

        {/* Right 50% Panel: Interactive Chat & Variables Inspector */}
        <div className="h-full min-h-0">
          <QnAPanel
            chatHistory={session?.chatHistory || []}
            variables={session?.variables || []}
            activeRules={session?.activeRules || []}
            onSendMessage={handleSendMessage}
            isSending={isSending}
            selectedVariableId={selectedVariable?.id}
            onSelectVariable={(v) => setSelectedVariable(v)}
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
