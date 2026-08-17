"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  X,
  ThumbsDown,
  AlertTriangle,
  Loader2,
  FileText,
  Sliders,
  ArrowRight,
  CheckCircle2,
  HelpCircle,
  ExternalLink,
  Calculator,
} from "lucide-react";
import {
  chatTrainingService,
  ChatRuleCategory,
  ChatRulePreview,
  TriageEntryPoint,
  TriageInvoice,
  TriageReason,
} from "@/lib/chat-training-service";

/**
 * Feature 14 Component: ThumbsDownTriage
 *
 * FOR MANAGERS & DEVELOPERS:
 * The one triage flow behind every thumbs-down in the product — the main Chat
 * screen (`MessageBubble::FeedbackVote`) and the Trainer's QA panel both open
 * this same component, because they are the same complaint about the same kind
 * of answer and splitting them would guarantee they drifted.
 *
 * The shape of the flow, and why each step exists:
 *
 *   1. **Reason picker** — wrong data / wrong interpretation / bad tone. Sent
 *      with the vote, so the backend can hand back the right next step in one
 *      round-trip instead of making the UI guess.
 *
 *   2. **wrong data** → the backend knows which invoices fed the reply
 *      (`ChatMessage.result_invoice_ids`). If several did, the user is asked the
 *      only question that actually disambiguates: *is this about one specific
 *      invoice, or about the overall answer/total?*
 *        - one invoice  → picked from the **real set the backend returns**, never
 *          typed → the backend auto-diffs what chat said against what is stored.
 *          The UI never asks "was the number right?", which is the question the
 *          user came here unable to answer.
 *            · mismatch → provably a chat bug → straight to the rule step.
 *            · match    → chat reported the stored value faithfully, so only the
 *              document can settle it. **The PDF is shown right here, beside the
 *              stored value**, so the user doesn't go hunting for the file.
 *              If the PDF disagrees, this stops being a chat correction at all
 *              and hands off to the Trainer's extraction flow, pre-filled.
 *        - overall/total → skip the PDF entirely; the backend's structured
 *          follow-up categories are the right question there.
 *
 *   3. **Category pick** — a closed vocabulary from the backend, never free
 *      text. The optional note is secondary context, stored for a human reading
 *      the rule later, and deliberately never spliced into the prompt.
 *
 *   4. **bad tone** → this is not a rule at all. Tone and length are already
 *      first-class tenant settings, so the flow points at those instead of
 *      inventing a rule object to carry them.
 *
 *   5. **Preview then confirm** — a chat rule is never saved straight off a
 *      thumbs-down. The backend requires the preview token (a commit without one
 *      is a 400), and the preview text is the literal final rule, not an LLM
 *      paraphrase of it.
 */

type Step =
  | "reason"
  | "scope_choice"
  | "pick_invoice"
  | "pick_field"
  | "diffing"
  | "confirm_pdf"
  | "category"
  | "preview"
  | "extraction_redirect"
  | "chat_settings"
  | "done";

interface ThumbsDownTriageProps {
  isOpen: boolean;
  messageId: string;
  /** The assistant reply's text, used to offer what it claimed for the diff. */
  onClose: () => void;
  /** Fired once something was actually saved / the flow ended successfully. */
  onResolved?: (summary: string) => void;
  /** Whether this user may commit a chat rule (`can_train`). */
  canTrain: boolean;
}

const REASONS: { key: TriageReason; label: string; hint: string }[] = [
  {
    key: "wrong_data",
    label: "Wrong data",
    hint: "A number, date or name in the answer doesn't match reality.",
  },
  {
    key: "wrong_interpretation",
    label: "Wrong interpretation",
    hint: "It had the right data but answered the wrong question.",
  },
  {
    key: "bad_tone",
    label: "Bad tone or length",
    hint: "The content was fine; the way it was written wasn't.",
  },
];

export default function ThumbsDownTriage({
  isOpen,
  messageId,
  onClose,
  onResolved,
  canTrain,
}: ThumbsDownTriageProps) {
  const [step, setStep] = useState<Step>("reason");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [triage, setTriage] = useState<TriageEntryPoint | null>(null);
  const [categories, setCategories] = useState<ChatRuleCategory[]>([]);
  const [invoices, setInvoices] = useState<TriageInvoice[]>([]);
  const [diffableFields, setDiffableFields] = useState<string[]>([]);

  const [selectedInvoice, setSelectedInvoice] = useState<TriageInvoice | null>(null);
  const [selectedField, setSelectedField] = useState("");
  const [claimedValue, setClaimedValue] = useState("");
  const [storedValue, setStoredValue] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [explanation, setExplanation] = useState("");

  const [category, setCategory] = useState("");
  const [pattern, setPattern] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<ChatRulePreview | null>(null);
  const [redirect, setRedirect] = useState<{
    invoiceId: string;
    field: string;
    vendorName: string | null;
  } | null>(null);

  // Reset everything whenever the dialog is (re-)opened, so a second
  // thumbs-down can't inherit the previous one's picked invoice or category.
  React.useEffect(() => {
    if (!isOpen) return;
    setStep("reason");
    setBusy(false);
    setError(null);
    setTriage(null);
    setCategories([]);
    setInvoices([]);
    setDiffableFields([]);
    setSelectedInvoice(null);
    setSelectedField("");
    setClaimedValue("");
    setStoredValue(null);
    setPdfUrl(null);
    setExplanation("");
    setCategory("");
    setPattern("");
    setNote("");
    setPreview(null);
    setRedirect(null);
  }, [isOpen]);

  if (!isOpen) return null;

  const selectedCategorySpec = categories.find((c) => c.key === category);

  /** Applies whichever next-step the backend named. One place, so every
   *  transition in this flow is the backend's decision rather than the UI's. */
  const applyNext = (
    next: string,
    payload: {
      explanation?: string;
      invoices?: TriageInvoice[];
      diffableFields?: string[];
      categories?: ChatRuleCategory[];
    }
  ) => {
    if (payload.explanation) setExplanation(payload.explanation);
    if (payload.categories) setCategories(payload.categories);
    if (payload.invoices) setInvoices(payload.invoices);
    if (payload.diffableFields) setDiffableFields(payload.diffableFields);

    if (next === "chat_settings") {
      setStep("chat_settings");
      return;
    }
    if (next === "diff_invoice") {
      const only = payload.invoices?.[0] ?? null;
      setSelectedInvoice(only);
      setStep("pick_field");
      return;
    }
    if (next === "pick_invoice") {
      setStep("scope_choice");
      return;
    }
    if (next === "extraction_flag_missed") {
      setStep("extraction_redirect");
      return;
    }
    // "category_pick" and anything unrecognised land on the safe, always-valid
    // step — a structured category pick works regardless of how we got here.
    setStep("category");
  };

  const handleReason = async (reason: TriageReason) => {
    setBusy(true);
    setError(null);
    try {
      const res = await chatTrainingService.submitFeedback(messageId, "down", reason);
      const t = res.triage;
      setTriage(t ?? null);
      if (!t) {
        // The vote is recorded either way; without a triage block there is
        // nothing further to ask, so end cleanly rather than showing a dead step.
        onResolved?.("Thanks — your feedback was recorded.");
        onClose();
        return;
      }
      applyNext(t.next, {
        explanation: t.explanation,
        invoices: t.invoices,
        diffableFields: t.diffableFields,
        categories: t.categories,
      });
    } catch {
      setError("Couldn't record that feedback. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const handleDiff = async () => {
    if (!selectedInvoice || !selectedField) return;
    setBusy(true);
    setError(null);
    setStep("diffing");
    try {
      const res = await chatTrainingService.triageMessage(messageId, {
        invoiceId: selectedInvoice.invoiceId,
        field: selectedField,
        claimedValue: claimedValue.trim() || undefined,
      });
      setStoredValue(res.diff?.storedValue ?? null);
      setExplanation(res.explanation || "");
      if (res.next === "confirm_against_pdf") {
        setPdfUrl(res.pdfUrl || selectedInvoice.pdfUrl);
        setStep("confirm_pdf");
      } else {
        applyNext(res.next, { explanation: res.explanation, categories: res.categories });
      }
    } catch {
      setError("Couldn't check that against your stored data. Please try again.");
      setStep("pick_field");
    } finally {
      setBusy(false);
    }
  };

  const handleVerdict = async (pdfAgrees: boolean) => {
    if (!selectedInvoice || !selectedField) return;
    setBusy(true);
    setError(null);
    try {
      const res = await chatTrainingService.submitSourceVerdict(messageId, {
        invoiceId: selectedInvoice.invoiceId,
        field: selectedField,
        pdfAgrees,
      });
      if (res.redirect) {
        setRedirect({
          invoiceId: res.redirect.invoiceId,
          field: res.redirect.field,
          vendorName: res.redirect.vendorName,
        });
      }
      applyNext(res.next, { explanation: res.explanation, categories: res.categories });
    } catch {
      setError("Couldn't record that answer. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  /** Lazily loads the category vocabulary if we reached this step without it. */
  const ensureCategories = async () => {
    if (categories.length > 0) return;
    try {
      setCategories(await chatTrainingService.getCategories());
    } catch {
      setError("Couldn't load the correction categories.");
    }
  };

  React.useEffect(() => {
    if (step === "category") void ensureCategories();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const handlePreview = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await chatTrainingService.previewRule({
        category,
        pattern,
        contextText: note,
      });
      setPreview(res);
      setStep("preview");
    } catch (err: any) {
      setError(
        typeof err?.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Couldn't build a preview for that correction."
      );
    } finally {
      setBusy(false);
    }
  };

  const handleCommit = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      await chatTrainingService.commitRule({
        category,
        pattern,
        contextText: note,
        previewToken: preview.previewToken,
      });
      setStep("done");
      onResolved?.("Answering rule saved. Future answers will follow it.");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : "Couldn't save that rule. Nothing was changed."
      );
    } finally {
      setBusy(false);
    }
  };

  const patternRequired = selectedCategorySpec?.requiresPattern ?? false;
  const canPreview = !!category && (!patternRequired || pattern.trim().length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      <div
        data-testid="thumbs-down-triage"
        className={`w-full bg-[#070D1A]/95 border border-rose-500/40 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col max-h-[92vh] ${
          step === "confirm_pdf" ? "max-w-4xl" : "max-w-lg"
        }`}
      >
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="px-5 py-3.5 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-xl border bg-rose-500/10 text-rose-400 border-rose-500/25 shrink-0">
              <ThumbsDown className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white leading-tight">
                What went wrong?
              </h3>
              <span className="text-[11px] text-slate-400 truncate block">
                Helps the assistant answer better next time
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-[#111827] transition-colors cursor-pointer shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* ── Body ────────────────────────────────────────────────────── */}
        <div className="p-5 space-y-4 text-xs overflow-y-auto">
          {explanation && step !== "reason" && step !== "done" && (
            <p className="text-slate-400 leading-relaxed">{explanation}</p>
          )}

          {/* 1. Reason */}
          {step === "reason" && (
            <div className="space-y-2">
              {REASONS.map((r) => (
                <button
                  key={r.key}
                  type="button"
                  data-testid={`triage-reason-${r.key}`}
                  disabled={busy}
                  onClick={() => handleReason(r.key)}
                  className="w-full text-left rounded-xl border border-[#1E2D45] bg-[#0B1120]/70 hover:border-rose-500/40 hover:bg-[#111827] p-3.5 transition-all cursor-pointer disabled:opacity-50"
                >
                  <span className="text-xs font-semibold text-slate-100 block mb-0.5">
                    {r.label}
                  </span>
                  <span className="text-[11px] text-slate-500 leading-relaxed">{r.hint}</span>
                </button>
              ))}
            </div>
          )}

          {/* 2a. One invoice, or the overall answer? */}
          {step === "scope_choice" && (
            <div className="space-y-2">
              <button
                type="button"
                data-testid="triage-scope-invoice"
                onClick={() => setStep("pick_invoice")}
                className="w-full text-left rounded-xl border border-[#1E2D45] bg-[#0B1120]/70 hover:border-rose-500/40 hover:bg-[#111827] p-3.5 transition-all cursor-pointer"
              >
                <span className="text-xs font-semibold text-slate-100 flex items-center gap-2 mb-0.5">
                  <FileText className="w-3.5 h-3.5 text-blue-400" />
                  One specific invoice is wrong
                </span>
                <span className="text-[11px] text-slate-500 leading-relaxed">
                  We&apos;ll check that invoice&apos;s stored value against what the answer
                  said.
                </span>
              </button>
              <button
                type="button"
                data-testid="triage-scope-aggregate"
                onClick={() => setStep("category")}
                className="w-full text-left rounded-xl border border-[#1E2D45] bg-[#0B1120]/70 hover:border-rose-500/40 hover:bg-[#111827] p-3.5 transition-all cursor-pointer"
              >
                <span className="text-xs font-semibold text-slate-100 flex items-center gap-2 mb-0.5">
                  <Calculator className="w-3.5 h-3.5 text-violet-400" />
                  The overall answer or total is wrong
                </span>
                <span className="text-[11px] text-slate-500 leading-relaxed">
                  Something should have been included or excluded, or it was totalled the
                  wrong way.
                </span>
              </button>
            </div>
          )}

          {/* 2b. Which invoice — from the real set, never typed */}
          {step === "pick_invoice" && (
            <div className="space-y-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block">
                Which invoice?
              </span>
              <div className="rounded-xl border border-[#1E2D45] bg-[#070D1A] max-h-56 overflow-y-auto divide-y divide-[#131E2E]">
                {invoices.map((inv) => (
                  <button
                    key={inv.invoiceId}
                    type="button"
                    data-testid="triage-invoice-option"
                    onClick={() => {
                      setSelectedInvoice(inv);
                      setStep("pick_field");
                    }}
                    className="w-full text-left px-3.5 py-2.5 hover:bg-[#111827] transition-colors flex items-center gap-2.5 cursor-pointer"
                  >
                    <FileText className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                    <span className="text-xs text-slate-200 truncate flex-1">
                      {inv.invoiceNumber || inv.invoiceId.slice(0, 8)}
                      {inv.vendorName ? ` · ${inv.vendorName}` : ""}
                    </span>
                    {inv.grandTotal !== null && inv.grandTotal !== undefined && (
                      <span className="text-[10px] font-mono text-slate-500 shrink-0">
                        {inv.currency ? `${inv.currency} ` : ""}
                        {Number(inv.grandTotal).toFixed(2)}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 2c. Which field, and what did the answer claim? */}
          {step === "pick_field" && selectedInvoice && (
            <div className="space-y-3">
              <div className="rounded-lg border border-[#1E2D45] bg-[#0B1120] px-3 py-2 text-[11px] text-slate-300">
                {selectedInvoice.invoiceNumber || selectedInvoice.invoiceId.slice(0, 8)}
                {selectedInvoice.vendorName ? ` · ${selectedInvoice.vendorName}` : ""}
              </div>
              <div>
                <label
                  htmlFor="triage-field"
                  className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
                >
                  Which value was wrong?
                </label>
                <select
                  id="triage-field"
                  data-testid="triage-field"
                  value={selectedField}
                  onChange={(e) => setSelectedField(e.target.value)}
                  className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-rose-500/50 cursor-pointer"
                >
                  <option value="">— Choose a field —</option>
                  {diffableFields.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label
                  htmlFor="triage-claimed"
                  className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
                >
                  What did the answer say it was?{" "}
                  <span className="text-slate-600 normal-case font-normal tracking-normal">
                    (optional)
                  </span>
                </label>
                <input
                  id="triage-claimed"
                  data-testid="triage-claimed"
                  type="text"
                  value={claimedValue}
                  onChange={(e) => setClaimedValue(e.target.value)}
                  placeholder="e.g. 110.00"
                  className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-rose-500/50"
                />
                <span className="text-[10px] text-slate-600 block mt-1 leading-relaxed">
                  Giving this makes the check exact. Without it we can only look for the
                  stored value somewhere in the reply, which is a weaker signal.
                </span>
              </div>
            </div>
          )}

          {step === "diffing" && (
            <div className="flex items-center gap-2.5 py-8 justify-center text-slate-400">
              <Loader2 className="w-4 h-4 animate-spin text-rose-400" />
              <span>Checking that against what&apos;s stored…</span>
            </div>
          )}

          {/* 2d. Chat matched the DB — only the document can settle it. */}
          {step === "confirm_pdf" && selectedInvoice && (
            <div className="space-y-3" data-testid="triage-confirm-pdf">
              <div className="rounded-xl border border-blue-500/25 bg-blue-500/5 p-3.5 flex items-start gap-2.5">
                <HelpCircle className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <span className="font-semibold text-blue-200 block mb-1">
                    We store <span className="font-mono">{storedValue ?? "—"}</span> for{" "}
                    <span className="font-mono">{selectedField}</span>
                  </span>
                  <p className="text-slate-400 leading-relaxed text-[11px]">
                    The assistant reported that faithfully. Does the document agree?
                  </p>
                </div>
              </div>

              {/* The PDF, right here — the same viewer treatment the Trainer
                  uses. Hunting for the file in another tab is exactly the
                  friction that makes this question go unanswered. */}
              {pdfUrl && (
                <div className="rounded-xl border border-[#1E2D45] bg-[#070D1A] overflow-hidden h-[46vh]">
                  <iframe
                    src={pdfUrl}
                    title="Source document"
                    className="w-full h-full"
                    data-testid="triage-pdf-frame"
                  />
                </div>
              )}

              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  type="button"
                  data-testid="triage-pdf-agrees"
                  disabled={busy}
                  onClick={() => handleVerdict(true)}
                  className="flex-1 px-3.5 py-2.5 rounded-xl border border-[#1E2D45] bg-[#0B1120] hover:bg-[#111827] text-xs font-semibold text-slate-200 transition-colors cursor-pointer disabled:opacity-50"
                >
                  The document matches — the answer was still wrong
                </button>
                <button
                  type="button"
                  data-testid="triage-pdf-disagrees"
                  disabled={busy}
                  onClick={() => handleVerdict(false)}
                  className="flex-1 px-3.5 py-2.5 rounded-xl border border-amber-500/40 bg-amber-600/15 hover:bg-amber-600/25 text-xs font-semibold text-amber-200 transition-colors cursor-pointer disabled:opacity-50"
                >
                  The document says something different
                </button>
              </div>
            </div>
          )}

          {/* 3. Structured category pick */}
          {step === "category" && (
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="triage-category"
                  className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
                >
                  What did it get wrong?
                </label>
                <select
                  id="triage-category"
                  data-testid="triage-category"
                  value={category}
                  onChange={(e) => {
                    setCategory(e.target.value);
                    setPattern("");
                  }}
                  className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-rose-500/50 cursor-pointer"
                >
                  <option value="">— Choose —</option>
                  {categories.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>

              {selectedCategorySpec && (
                <div>
                  <label
                    htmlFor="triage-pattern"
                    className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
                  >
                    {selectedCategorySpec.patternLabel}
                    {patternRequired && <span className="text-rose-400"> *</span>}
                  </label>
                  <input
                    id="triage-pattern"
                    data-testid="triage-pattern"
                    type="text"
                    value={pattern}
                    onChange={(e) => setPattern(e.target.value)}
                    className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-rose-500/50"
                  />
                </div>
              )}

              <div>
                <label
                  htmlFor="triage-note"
                  className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
                >
                  Extra context{" "}
                  <span className="text-slate-600 normal-case font-normal tracking-normal">
                    (optional)
                  </span>
                </label>
                <textarea
                  id="triage-note"
                  rows={2}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-rose-500/50"
                />
                <span className="text-[10px] text-slate-600 block mt-1 leading-relaxed">
                  Kept alongside the rule for whoever reads it later. It is never fed to
                  the assistant as an instruction.
                </span>
              </div>
            </div>
          )}

          {/* 4. Preview the literal rule text */}
          {step === "preview" && preview && (
            <div className="space-y-3" data-testid="chat-rule-preview">
              <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-3.5">
                <span className="text-[10px] uppercase tracking-wider text-emerald-300/80 block mb-1.5">
                  The rule that will be saved
                </span>
                <p className="text-[11px] text-emerald-200 leading-relaxed">
                  {preview.ruleText}
                </p>
              </div>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                {preview.explanation}
              </p>
              {!canTrain && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-200">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span className="leading-relaxed">
                    Your feedback is recorded, but saving an answering rule needs
                    training permission. Ask an admin to grant it.
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Handoff: this was never a chat problem */}
          {step === "extraction_redirect" && (
            <div className="space-y-3" data-testid="triage-extraction-redirect">
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3.5 flex items-start gap-2.5">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-amber-200 block mb-1">
                    This is an extraction problem, not an answering one
                  </span>
                  <p className="text-slate-400 leading-relaxed text-[11px]">
                    Teaching the assistant here would only change how it talks about a
                    value that was read wrongly in the first place. Train it on the
                    invoice instead.
                  </p>
                </div>
              </div>
              {redirect && (
                <Link
                  href={`/trainer?invoice_id=${encodeURIComponent(
                    redirect.invoiceId
                  )}&field=${encodeURIComponent(redirect.field)}&flag_missed=1`}
                  onClick={onClose}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold transition-colors cursor-pointer"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Open this invoice in the Trainer
                </Link>
              )}
            </div>
          )}

          {/* Bad tone -> settings, not a rule */}
          {step === "chat_settings" && (
            <div className="space-y-3" data-testid="triage-chat-settings">
              <div className="rounded-xl border border-violet-500/25 bg-violet-500/5 p-3.5 flex items-start gap-2.5">
                <Sliders className="w-4 h-4 text-violet-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-violet-200 block mb-1">
                    Tone and length are settings, not rules
                  </span>
                  <p className="text-slate-400 leading-relaxed text-[11px]">
                    There&apos;s nothing to teach here — adjust how the assistant writes
                    directly, and it applies to every future answer.
                  </p>
                </div>
              </div>
              <Link
                href="/trainer?panel=chat-style"
                onClick={onClose}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold transition-colors cursor-pointer"
              >
                <Sliders className="w-3.5 h-3.5" />
                Adjust response style
              </Link>
            </div>
          )}

          {step === "done" && (
            <div className="flex flex-col items-center gap-2.5 py-8 text-center">
              <CheckCircle2 className="w-8 h-8 text-emerald-400" />
              <span className="text-sm font-medium text-slate-200">Rule saved</span>
              <p className="text-[11px] text-slate-500 max-w-xs leading-relaxed">
                Future answers for this workspace will follow it. You can review or remove
                it from the Trainer at any time.
              </p>
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-[11px] text-red-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span className="leading-relaxed">{error}</span>
            </div>
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────────────── */}
        {(step === "pick_field" || step === "category" || step === "preview" || step === "done") && (
          <div className="px-5 py-3.5 bg-[#0B1120]/90 border-t border-[#1E2D45] flex items-center justify-end gap-2 shrink-0">
            {step !== "done" && (
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="px-3.5 py-2 rounded-xl border border-[#1E2D45] text-slate-300 hover:text-white hover:bg-[#111827] text-xs font-medium transition-colors cursor-pointer"
              >
                Cancel
              </button>
            )}

            {step === "pick_field" && (
              <button
                type="button"
                data-testid="triage-run-diff"
                onClick={handleDiff}
                disabled={busy || !selectedField}
                className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold transition-all flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span>Check it</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}

            {step === "category" && (
              <button
                type="button"
                data-testid="triage-preview-rule"
                onClick={handlePreview}
                disabled={busy || !canPreview}
                className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold transition-all flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy ? (
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>
                    <span>Preview the rule</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
            )}

            {step === "preview" && (
              <button
                type="button"
                data-testid="triage-commit-rule"
                onClick={handleCommit}
                disabled={busy || !canTrain}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-all flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy ? (
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4" />
                    <span>Confirm &amp; Save</span>
                  </>
                )}
              </button>
            )}

            {step === "done" && (
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl bg-[#111827] hover:bg-[#1E293B] border border-[#1E2D45] text-slate-200 text-xs font-semibold transition-colors cursor-pointer"
              >
                Close
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
