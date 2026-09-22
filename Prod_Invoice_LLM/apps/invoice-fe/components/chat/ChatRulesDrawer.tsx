"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ScrollText, X, RotateCw, Loader2, AlertCircle } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import ChatRulesPanel from "@/components/settings/ChatRulesPanel";
import { chatTrainingService, type ChatRule } from "@/lib/chat-training-service";

interface ChatRulesDrawerProps {
  /** Controls drawer visibility */
  isOpen: boolean;
  /** Callback fired to dismiss drawer */
  onClose: () => void;
}

export default function ChatRulesDrawer({ isOpen, onClose }: ChatRulesDrawerProps) {
  const { canTrain } = useAuth();

  const [rules, setRules] = useState<ChatRule[]>([]);
  const [categoryLabels, setCategoryLabels] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [loadedRules, categories] = await Promise.all([
        chatTrainingService.listRules(),
        chatTrainingService.getCategories().catch(() => []),
      ]);
      setRules(loadedRules);
      setCategoryLabels(
        Object.fromEntries(categories.map((category) => [category.key, category.label]))
      );
    } catch {
      setError("Failed to load chat rules. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch rules when drawer opens
  useEffect(() => {
    if (isOpen) {
      void loadRules();
    }
  }, [isOpen, loadRules]);

  // Close on Escape key press
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleDelete = async (rule: ChatRule) => {
    setDeletingId(rule.id);
    setError(null);
    try {
      await chatTrainingService.deleteRule(rule.id);
      setRules((current) => current.filter((item) => item.id !== rule.id));
    } catch {
      setError("Failed to delete the rule. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Chat Rules & Directives"
      className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
    >
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-lg bg-[#151B26] border-l border-[#222D3D] shadow-2xl flex flex-col h-full">
          {/* Drawer Header */}
          <div className="px-6 py-4 bg-[#0F172A] border-b border-[#222D3D] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <ScrollText className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Chat Rules &amp; Directives</h3>
                <p className="text-[11px] text-slate-400">
                  Workspace-wide rules taught from feedback, injected into chat
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void loadRules()}
                disabled={loading}
                title="Refresh chat rules"
                aria-label="Refresh chat rules"
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1E293B] transition-colors disabled:opacity-50 cursor-pointer"
              >
                <RotateCw className={`w-4 h-4 ${loading ? "animate-spin text-blue-400" : ""}`} />
              </button>

              <button
                type="button"
                onClick={onClose}
                title="Close drawer"
                aria-label="Close drawer"
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1E293B] transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {error && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-300">
                <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
                <span className="flex-1">{error}</span>
                <button
                  type="button"
                  onClick={() => void loadRules()}
                  className="underline hover:text-white shrink-0 cursor-pointer"
                >
                  Retry
                </button>
              </div>
            )}

            {loading && rules.length === 0 ? (
              <div className="py-16 text-center text-xs text-slate-400 flex flex-col items-center gap-2">
                <Loader2 className="w-5 h-5 border-blue-500 animate-spin text-blue-400" />
                <span>Loading chat rules...</span>
              </div>
            ) : (
              <ChatRulesPanel
                rules={rules}
                categoryLabels={categoryLabels}
                canTrain={canTrain}
                deletingId={deletingId}
                onDelete={handleDelete}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
