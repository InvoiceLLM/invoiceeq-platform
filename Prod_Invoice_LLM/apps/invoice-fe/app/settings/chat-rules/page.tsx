"use client";

/**
 * FE Gap 478 — Settings › Chat Rules.
 *
 * The read-and-delete half of the chat-correction lane (Feature 14). Rules are
 * *taught* from a thumbs-down in chat; this is the only place they can be read
 * back, audited and removed. Placed in Settings rather than inside the Trainer's
 * rule-history drawer because a chat rule is tenant-wide behaviour, like the
 * other settings around it, and because the Trainer drawer is scoped to
 * extraction rules (`ExtractionTemplate.rules`), a different store entirely.
 *
 * Permissions: the list is readable by anyone who can open Settings; delete is
 * gated on `can_train` — the same permission `DELETE /chat/rules/{rule_id}`
 * enforces backend-side (`routers/chat.py::delete_chat_rule`, `require_can_train`).
 * The gate here is discoverability, not security; the backend is the control.
 */

import React, { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2, RotateCw } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import ChatRulesPanel from "@/components/settings/ChatRulesPanel";
import { chatTrainingService, type ChatRule } from "@/lib/chat-training-service";
import RoutineAnswersPanel from "@/components/settings/RoutineAnswersPanel";

const GENERIC_ERRORS = {
  load: "Failed to load chat rules. Please try again.",
  delete: "Failed to delete the rule. Please try again.",
};

export default function ChatRulesSettingsPage() {
  usePageHeader({
    title: "Chat Rules",
    subtitle: "Answering rules taught from chat feedback, applied workspace-wide",
    backHref: "/settings",
  });

  const { canTrain, loading: authLoading } = useAuth();

  const [rules, setRules] = useState<ChatRule[]>([]);
  const [categoryLabels, setCategoryLabels] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // The category vocabulary is the backend's own closed list; a failure to
      // fetch it must not hide the rules, so it degrades to "no labels" and the
      // panel falls back to the humanised key.
      const [loadedRules, categories] = await Promise.all([
        chatTrainingService.listRules(),
        chatTrainingService.getCategories().catch(() => []),
      ]);
      setRules(loadedRules);
      setCategoryLabels(
        Object.fromEntries(categories.map((category) => [category.key, category.label]))
      );
    } catch {
      setError(GENERIC_ERRORS.load);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (rule: ChatRule) => {
    setDeletingId(rule.id);
    setError(null);
    try {
      await chatTrainingService.deleteRule(rule.id);
      // Hard delete backend-side (the row goes, the answer cache is flushed), so
      // the row goes here too — no disabled-but-present state.
      setRules((current) => current.filter((item) => item.id !== rule.id));
    } catch {
      setError(GENERIC_ERRORS.delete);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      <main className="flex-1 px-6 py-6 max-w-3xl w-full mx-auto space-y-4">
        <div className="flex items-start justify-between gap-3">
          <p className="text-[11px] text-slate-500 leading-relaxed max-w-xl">
            Each rule below is injected into every later question this workspace
            asks. Deleting one stops it applying from the next question onwards.
          </p>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="shrink-0 inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg border border-[#1E293B] bg-[#111827] text-slate-400 hover:text-slate-200 hover:border-[#334155] transition-colors disabled:opacity-50"
          >
            {/* hardcode-ok: a Tailwind class toggle, no value or figure is
                rendered — the guard matches the template literal, not data. */}
            <RotateCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {error && (
          <div
            data-testid="chat-rules-error"
            className="flex items-start gap-2 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-[11px] text-rose-200"
          >
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-relaxed">{error}</span>
          </div>
        )}

        {loading || authLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          </div>
        ) : (
          <ChatRulesPanel
            rules={rules}
            categoryLabels={categoryLabels}
            canTrain={canTrain}
            deletingId={deletingId}
            onDelete={(rule) => void handleDelete(rule)}
          />
        )}

        {/* FE Feature 22 Task 22.27: the routine-questionnaire answers live here too —
            one home for how answers are shaped, not a Records tab. */}
        {!authLoading && <RoutineAnswersPanel canTrain={canTrain} />}
      </main>
    </div>
  );
}
