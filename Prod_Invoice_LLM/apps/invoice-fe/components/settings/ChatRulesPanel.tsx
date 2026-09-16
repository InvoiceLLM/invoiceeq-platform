"use client";

/**
 * FE Gap 478 — the tenant's committed chat rules, made visible.
 *
 * A chat rule is taught from a thumbs-down on an answer (`ThumbsDownTriage`),
 * committed through `POST /chat/rules/commit`, and from that moment rewrites how
 * every later question is scoped for the whole workspace. Until this panel there
 * was no surface that read them back: the only way to see one was to open
 * `/api/chat/rules` in a browser tab, and a rule that over-fires was effectively
 * permanent from the UI. The Trainer's `RuleHistoryDrawer` never listed them and
 * never will — `TenantChatRule` is a separate store from
 * `ExtractionTemplate.rules` on purpose.
 *
 * This component is deliberately presentational: it receives the rules, the
 * category vocabulary and the caller's permission, and reports a delete upwards.
 * The page owns fetching. That split is what lets the render rules (empty state,
 * permission gating, label fallback) be asserted in a unit test without a
 * network or an auth session.
 *
 * NO DOMAIN DATA LIVES HERE. Category labels come from the backend's own closed
 * vocabulary (`GET /chat/rules/categories`); an unknown key degrades to a
 * humanised form of the key itself, so a category added backend-side renders
 * correctly with no edit to this file.
 */

import React from "react";
import { AlertTriangle, Loader2, MessageSquareQuote, Trash2 } from "lucide-react";
import type { ChatRule } from "@/lib/chat-training-service";

export interface ChatRulesPanelProps {
  rules: ChatRule[];
  /** `key -> label` from the backend's category vocabulary. May be partial. */
  categoryLabels?: Record<string, string>;
  /** `can_train` — the same permission the commit and DELETE paths require. */
  canTrain: boolean;
  /** Id of the rule whose delete is currently in flight, if any. */
  deletingId?: string | null;
  /** Called only after the user confirms. Absent ⇒ the panel is read-only. */
  onDelete?: (rule: ChatRule) => void;
}

/**
 * The label for a rule's category. Backend vocabulary first; otherwise the key
 * itself, humanised — never a hardcoded mapping of category keys (FE Gap 478).
 */
export function chatRuleCategoryLabel(
  category: string,
  labels?: Record<string, string>
): string {
  const fromBackend = labels?.[category];
  if (fromBackend && fromBackend.trim()) return fromBackend.trim();
  const humanised = (category || "").replace(/[_-]+/g, " ").trim();
  if (!humanised) return "Uncategorised";
  return humanised.charAt(0).toUpperCase() + humanised.slice(1);
}

/**
 * When the rule was added, in the viewer's locale. An absent or unparseable
 * timestamp renders as "Date unknown" rather than "Invalid Date" — the backend
 * types `createdAt` as nullable (`routers/chat.py::list_chat_rules`).
 */
export function formatChatRuleAddedAt(createdAt?: string | null): string {
  if (!createdAt) return "Date unknown";
  const parsed = new Date(createdAt);
  if (Number.isNaN(parsed.getTime())) return "Date unknown";
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ChatRulesPanel({
  rules,
  categoryLabels,
  canTrain,
  deletingId,
  onDelete,
}: ChatRulesPanelProps) {
  const canDelete = canTrain && typeof onDelete === "function";

  /**
   * Confirm lives with the affordance, not with the caller: deleting a rule
   * silently changes every future answer for the whole workspace, and there is
   * no undo (the backend hard-deletes the row and flushes the answer cache).
   */
  const handleDelete = (rule: ChatRule) => {
    if (!onDelete) return;
    const confirmed =
      typeof window === "undefined" ||
      window.confirm(
        "Delete this chat rule? Future answers will stop applying it. This cannot be undone."
      );
    if (!confirmed) return;
    onDelete(rule);
  };

  if (rules.length === 0) {
    return (
      <div
        data-testid="chat-rules-empty"
        className="rounded-xl border border-[#1E293B] bg-[#111827] px-6 py-10 text-center"
      >
        <div className="w-10 h-10 rounded-lg border border-blue-500/20 bg-blue-500/10 flex items-center justify-center mx-auto mb-3">
          <MessageSquareQuote className="w-5 h-5 text-blue-400" />
        </div>
        <p className="text-sm font-medium text-white">No chat rules yet</p>
        <p className="text-[11px] text-slate-500 mt-1.5 leading-relaxed max-w-md mx-auto">
          Rules are taught from a thumbs-down on a chat answer: pick what was
          wrong, review the exact rule text, and save it. Anything saved that way
          appears here, and applies to every later question in this workspace.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!canTrain && (
        <div
          data-testid="chat-rules-readonly"
          className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-200"
        >
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span className="leading-relaxed">
            You can review these rules, but changing them needs training
            permission. Ask an admin to grant it.
          </span>
        </div>
      )}

      <ul data-testid="chat-rules-list" className="space-y-3">
        {rules.map((rule) => {
          const busy = deletingId === rule.id;
          return (
            <li
              key={rule.id}
              data-testid="chat-rule-row"
              data-rule-id={rule.id}
              className="rounded-xl bg-[#111827] border border-[#1E293B] px-4 py-3.5"
            >
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p
                    data-testid="chat-rule-text"
                    className="text-sm text-slate-100 leading-relaxed"
                  >
                    {rule.ruleText}
                  </p>
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <span
                      data-testid="chat-rule-category"
                      className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md border border-blue-500/20 bg-blue-500/10 text-blue-300"
                    >
                      {chatRuleCategoryLabel(rule.category, categoryLabels)}
                    </span>
                    <span
                      data-testid="chat-rule-added-at"
                      className="text-[11px] text-slate-500"
                    >
                      Added {formatChatRuleAddedAt(rule.createdAt)}
                    </span>
                    {/* Author only when the API carries one — the column is
                        nullable for rules committed before it existed. */}
                    {rule.createdBy ? (
                      <span
                        data-testid="chat-rule-author"
                        className="text-[11px] text-slate-500"
                      >
                        by {rule.createdBy}
                      </span>
                    ) : null}
                    {/* FE Feature 22 Task 22.27: rules ATLAS wrote from an accepted convention. */}
                    {rule.source === "atlas" && (
                      <span
                        data-testid="chat-rule-source-atlas"
                        className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md border border-violet-500/20 bg-violet-500/10 text-violet-300"
                      >
                        Written by ATLAS
                      </span>
                    )}
                    {!rule.enabled && (
                      <span
                        data-testid="chat-rule-disabled"
                        className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md border border-slate-600/40 bg-slate-600/10 text-slate-400"
                      >
                        Inactive
                      </span>
                    )}
                  </div>
                </div>

                {canDelete && (
                  <button
                    type="button"
                    data-testid="chat-rule-delete"
                    onClick={() => handleDelete(rule)}
                    disabled={busy}
                    title="Delete this rule"
                    aria-label="Delete this rule"
                    className="shrink-0 w-8 h-8 rounded-lg border border-[#1E293B] flex items-center justify-center text-slate-500 hover:text-rose-300 hover:border-rose-500/30 hover:bg-rose-500/10 transition-colors disabled:opacity-50"
                  >
                    {busy ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
