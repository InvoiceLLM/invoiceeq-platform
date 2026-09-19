// =============================================================================
// FILE: components/atlas/MemoryPanel.tsx
// FEATURE: FE Feature 23 — BE Feature 34 task 34.10 (§7.2, D31, D40, D12).
//          FE Gap 700.
//
// THIS IS §7.2'S PROMISE, KEPT ON A SCREEN. D31: "everything ATLAS learns
// becomes a visible, editable rule in plain language ... nothing is remembered
// invisibly, so a wrong lesson can be found and removed rather than haunting the
// system forever." The backend has served all four verbs since Slice C and the
// only way to exercise them was `curl`. A promise kept by a developer's terminal
// is not kept.
//
// D40 IS THE BOUND, AND IT IS WHY THIS LIST IS SHORTER THAN IT LOOKS LIKE IT
// SHOULD BE. A derived observation — a vendor's usual range, a claim checked
// against a witness — is recomputed at check time and thrown away (D39), and it
// is NOT a memory rule. It shows its working on the line instead. Listing one
// here would invite a user to "edit" a figure computed from their own invoices,
// which is a category error: fixing the invoices fixes it, and editing it fixes
// nothing. This component therefore renders `rules` from the server and has no
// other source of rows at all — there is no merge here, no second fetch and no
// derived list, and `tests/unit/atlas-memory.test.tsx` asserts that a baseline
// arriving from any other surface cannot reach this list.
//
// DELETE MEANS DELETE (founder rule, and §7.2's own argument). The control says
// so in words, the backend removes the row, and this component RE-READS rather
// than splicing: what the list shows afterwards is what Postgres has. Nothing
// here hides a row the server still holds, and there is no undo — because an
// undo implies a copy kept somewhere, which is the soft delete under a different
// name.
//
// SWITCHING A RULE OFF IS A DIFFERENT ACT FROM DELETING IT, and both are
// offered, because they answer different questions: "this is wrong" and "this is
// right but not now".
//
// D12'S SUGGESTIONS NEVER WRITE THEMSELVES. They are rendered in their own list,
// visually separate from the rules, and accepting one is a POST the user asked
// for. A suggestion that quietly became a rule would be the silent write §5.3
// forbids, arriving through the door marked "learning".
//
// NO ARITHMETIC (spec §2). `count` is the server's number and is printed as
// sent; nothing here totals, compares or thresholds it.
// =============================================================================

"use client";

import { ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  addMemoryRule,
  deleteMemoryRule,
  editMemoryRule,
  fetchAtlasMemory,
  type AtlasMemoryResponse,
  type AtlasMemoryRule,
} from "@/lib/atlas";

/** The heading. "Memory" is a system word; this is the user's sentence for it. */
export const MEMORY_TITLE = "What I remember";

/**
 * D40, said out loud on the screen rather than only in this file's header.
 *
 * A user who knows ATLAS spotted "4× their usual range" and cannot find that
 * range in this list will reasonably conclude the list is incomplete. It is not
 * — that observation is not a lesson, and this sentence is the difference.
 */
export const MEMORY_SCOPE_NOTE =
  "Only what you told me, or agreed I should remember. What I work out from your own invoices — a vendor's usual range, for instance — is not kept here; I show that working on the line itself, and fixing the invoices fixes it.";

/** The delete control's own words. It is a hard delete and it says so. */
export const DELETE_TITLE = "Delete this. The record goes — there is no undo.";

export default function MemoryPanel() {
  const [payload, setPayload] = useState<AtlasMemoryResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [newRule, setNewRule] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setPayload(await fetchAtlasMemory());
    } catch (err: any) {
      // Said out loud. A memory list that renders empty because a read failed
      // looks exactly like a system that has learned nothing, which is the one
      // lie this panel must not tell — a user would conclude their correction
      // never landed.
      setError(
        err?.response?.data?.detail ??
          "I could not read back what I remember, so this list is not what I hold."
      );
      setPayload(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Every write ends in a re-read: the list shows the server's rows, not this app's guess. */
  const run = useCallback(
    async (id: string, work: () => Promise<unknown>, failure: string) => {
      setBusyId(id);
      setError(null);
      try {
        await work();
        await load();
      } catch (err: any) {
        setError(err?.response?.data?.detail ?? failure);
      } finally {
        setBusyId(null);
      }
    },
    [load]
  );

  const rules: AtlasMemoryRule[] = payload?.rules ?? [];
  const suggestions = payload?.noise_suggestions ?? [];

  return (
    <section data-testid="atlas-memory" className="space-y-2">
      <button
        type="button"
        data-testid="atlas-memory-toggle"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center gap-2 rounded border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-left text-[13px] text-slate-200 hover:bg-slate-800/60"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-500" />
        )}
        <span>{MEMORY_TITLE}</span>
        {suggestions.length > 0 && (
          <span data-testid="atlas-memory-suggestion-flag" className="text-[11px] text-amber-300">
            I have something to ask you
          </span>
        )}
      </button>

      {open && (
        <div data-testid="atlas-memory-body" className="space-y-3 pl-5">
          <p data-testid="atlas-memory-scope" className="text-[11px] text-slate-500">
            {MEMORY_SCOPE_NOTE}
          </p>

          {error && (
            <p data-testid="atlas-memory-error" className="text-[12px] text-amber-300">
              {error}
            </p>
          )}

          {/* D12 — offered, never applied. Rendered above the rules because it
              is a question waiting on the user, and below it is where questions
              go to be forgotten. Accepting one is `addMemoryRule()` with the
              server's own sentence: the user agreeing is what turns an offer
              into a rule. */}
          {suggestions.length > 0 && (
            <ul data-testid="atlas-memory-suggestions" className="space-y-1">
              {suggestions.map((suggestion) => (
                <li
                  key={suggestion.family}
                  data-testid="atlas-memory-suggestion"
                  className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5"
                >
                  {/* The server's sentence and the server's count, printed as
                      sent. Nothing here composes either. */}
                  <p className="text-[12px] text-slate-200">{suggestion.text}</p>
                  <p className="text-[11px] text-slate-500">
                    <span data-testid="atlas-memory-suggestion-description">
                      {suggestion.description}
                    </span>
                    <span data-testid="atlas-memory-suggestion-count"> · {suggestion.count}</span>
                  </p>
                  <button
                    type="button"
                    data-testid="atlas-memory-suggestion-accept"
                    disabled={busyId === suggestion.family}
                    onClick={() =>
                      void run(
                        suggestion.family,
                        () => addMemoryRule(suggestion.text),
                        "I could not write that down, so I have not remembered it."
                      )
                    }
                    className="mt-1 rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Yes, remember that
                  </button>
                </li>
              ))}
            </ul>
          )}

          {payload && rules.length === 0 && (
            <p data-testid="atlas-memory-empty" className="text-[12px] text-slate-400">
              You have told me nothing yet, and I have agreed nothing with you.
            </p>
          )}

          <ul data-testid="atlas-memory-rules" className="space-y-1">
            {rules.map((rule) => (
              <li
                key={rule.id}
                data-testid="atlas-memory-rule"
                data-rule-id={rule.id}
                data-active={rule.active}
                className="rounded border border-slate-700/60 bg-slate-900/40 px-2 py-1.5"
              >
                {editingId === rule.id ? (
                  <div className="space-y-1">
                    <textarea
                      data-testid="atlas-memory-edit-text"
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      rows={2}
                      className="w-full rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-[12px] text-slate-200"
                    />
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        data-testid="atlas-memory-edit-save"
                        disabled={busyId === rule.id || !draft.trim()}
                        onClick={() =>
                          void run(
                            rule.id,
                            async () => {
                              await editMemoryRule(rule.id, { text: draft });
                              setEditingId(null);
                            },
                            "That change did not reach me, so the rule still says what it said."
                          )
                        }
                        className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        data-testid="atlas-memory-edit-cancel"
                        onClick={() => setEditingId(null)}
                        className="text-[11px] text-slate-500 hover:text-slate-300"
                      >
                        Never mind
                      </button>
                    </div>
                  </div>
                ) : (
                  <p
                    data-testid="atlas-memory-rule-text"
                    className={
                      rule.active
                        ? "text-[12px] text-slate-200"
                        : "text-[12px] text-slate-500 line-through"
                    }
                  >
                    {rule.text}
                  </p>
                )}

                {/* Provenance, read-only: where this lesson came from and who
                    put it there is what makes a wrong one judgeable. */}
                <p data-testid="atlas-memory-rule-meta" className="text-[11px] text-slate-500">
                  <span data-testid="atlas-memory-rule-source">{rule.source}</span>
                  <span> · {rule.created_by}</span>
                  <span> · {rule.created_at}</span>
                </p>

                <div className="mt-1 flex items-center gap-2">
                  <button
                    type="button"
                    data-testid="atlas-memory-rule-edit"
                    onClick={() => {
                      setEditingId(rule.id);
                      setDraft(rule.text);
                    }}
                    className="text-[11px] text-slate-400 hover:text-slate-200"
                  >
                    Change the wording
                  </button>
                  <button
                    type="button"
                    data-testid="atlas-memory-rule-toggle"
                    disabled={busyId === rule.id}
                    onClick={() =>
                      void run(
                        rule.id,
                        () => editMemoryRule(rule.id, { active: !rule.active }),
                        "That did not reach me, so nothing has changed."
                      )
                    }
                    className="text-[11px] text-slate-400 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {rule.active ? "Stop using this" : "Use this again"}
                  </button>
                  <button
                    type="button"
                    data-testid="atlas-memory-rule-delete"
                    title={DELETE_TITLE}
                    disabled={busyId === rule.id}
                    onClick={() =>
                      void run(
                        rule.id,
                        () => deleteMemoryRule(rule.id),
                        "I could not delete that, so I still hold it."
                      )
                    }
                    className="inline-flex items-center gap-1 text-[11px] text-rose-400 hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2 className="h-3 w-3" />
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>

          {/* Telling ATLAS something directly (§7.2, source `told`). The
              sentence is sent exactly as typed — this is the user's language,
              and a template here would make it the product's. */}
          <div className="space-y-1">
            <textarea
              data-testid="atlas-memory-new-text"
              value={newRule}
              onChange={(event) => setNewRule(event.target.value)}
              rows={2}
              placeholder="Tell me something to remember, in your own words"
              className="w-full rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-[12px] text-slate-200"
            />
            <button
              type="button"
              data-testid="atlas-memory-new-save"
              disabled={busyId === MEMORY_TITLE || !newRule.trim()}
              onClick={() =>
                void run(
                  MEMORY_TITLE,
                  async () => {
                    await addMemoryRule(newRule);
                    setNewRule("");
                  },
                  "I could not write that down, so I have not remembered it."
                )
              }
              className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Remember this
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
