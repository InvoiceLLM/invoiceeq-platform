"use client";

// =============================================================================
// FILE: components/settings/RoutineAnswersPanel.tsx
// FEATURE: FE Feature 22 Task 22.27 — the Trainer lists the routine-questionnaire
//          answers, on the Chat Rules settings page (spec §3.3: Settings is the
//          home — not a Records tab, not a second list of chat rules).
//
// Contract (routers/today.py, verified 2026-09-17):
//   GET   /today/routine-answers        -> {answers: {key: value}, contradictions: [key]}
//   PATCH /today/routine-answers/{key}  {value} -> {ok, key, value}
//
// The answers endpoint returns keys and values only — no question text, no source
// — so a row is labelled from its key (the same relabelling as the questionnaire's
// chips). A skipped question is stored as an empty answer (22.22) and shown as
// "Skipped", editable like any other. A key the backend lists in `contradictions`
// is flagged: the tenant's own documents disagree with the answer.
//
// Editing needs `can_train`, the same permission the rest of this page uses.
// =============================================================================

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ClipboardList, Loader2, Pencil } from "lucide-react";
import { chipLabel, getRoutineAnswers, todayErrorOf, updateRoutineAnswer } from "@/lib/today";

export default function RoutineAnswersPanel({ canTrain }: { canTrain: boolean }) {
  const [answers, setAnswers] = useState<Record<string, string> | null>(null);
  const [contradictions, setContradictions] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await getRoutineAnswers();
      setAnswers(result.answers ?? {});
      setContradictions(result.contradictions ?? []);
    } catch {
      setError("Could not load your routine answers.");
      setAnswers((current) => current ?? {});
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (key: string) => {
    if (savingKey) return;
    setSavingKey(key);
    setError(null);
    try {
      const result = await updateRoutineAnswer(key, draft.trim());
      setAnswers((current) => ({ ...(current ?? {}), [result.key]: result.value }));
      setEditingKey(null);
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not save this answer.");
    } finally {
      setSavingKey(null);
    }
  };

  const keys = answers ? Object.keys(answers) : [];

  return (
    <section data-testid="routine-answers" aria-labelledby="routine-answers-heading" className="space-y-3 pt-4">
      <div>
        <h2 id="routine-answers-heading" className="inline-flex items-center gap-1.5 text-sm font-semibold text-white">
          <ClipboardList className="h-4 w-4 text-sky-400" aria-hidden="true" />
          Your routine answers
        </h2>
        <p className="mt-0.5 text-[11px] text-slate-500">
          What you told ATLAS about how the business runs. Today uses these to group payments and flag sign-offs.
        </p>
      </div>

      {error && (
        <p role="alert" className="text-[11px] text-rose-300">
          {error}
        </p>
      )}

      {answers === null ? (
        <div className="flex justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-label="Loading routine answers" />
        </div>
      ) : keys.length === 0 ? (
        !error && (
          <p data-testid="routine-answers-empty" className="rounded-xl border border-[#1E293B] bg-[#111827] px-4 py-3.5 text-[11px] text-slate-500">
            No routine answers yet. ATLAS asks these questions on Today once your first documents are in.
          </p>
        )
      ) : (
        <ul className="space-y-2">
          {keys.map((key) => {
            const value = answers[key] ?? "";
            const contradicted = contradictions.includes(key);
            const editing = editingKey === key;
            return (
              <li
                key={key}
                data-testid="routine-answer-row"
                data-key={key}
                className="rounded-xl border border-[#1E293B] bg-[#111827] px-4 py-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[11px] uppercase tracking-wider text-slate-500">{chipLabel(key)}</p>
                    {!editing && (
                      <p data-testid="routine-answer-value" className="text-sm text-slate-100">
                        {value === "" ? <span className="text-slate-500">Skipped</span> : chipLabel(value)}
                      </p>
                    )}
                  </div>
                  {canTrain && !editing && (
                    <button
                      type="button"
                      onClick={() => {
                        setEditingKey(key);
                        setDraft(value);
                      }}
                      aria-label={`Edit ${chipLabel(key)}`}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 hover:text-white"
                    >
                      <Pencil className="h-3 w-3" aria-hidden="true" />
                      Edit
                    </button>
                  )}
                </div>

                {editing && (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void save(key);
                    }}
                    className="mt-2 flex flex-wrap items-center gap-2"
                  >
                    <label htmlFor={`routine-${key}`} className="sr-only">
                      {chipLabel(key)}
                    </label>
                    <input
                      id={`routine-${key}`}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      disabled={savingKey === key}
                      className="min-w-[12rem] flex-1 rounded-lg border border-[#222D3D] bg-[#0B0F19] px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500/60"
                    />
                    <button
                      type="submit"
                      disabled={savingKey === key || draft.trim() === ""}
                      className="rounded-lg bg-[#3B82F6] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2563EB] disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingKey(null)}
                      className="rounded-lg px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-white"
                    >
                      Cancel
                    </button>
                  </form>
                )}

                {contradicted && (
                  <p data-testid="routine-answer-contradicted" className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-amber-300">
                    <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                    Your recent documents don&apos;t match this answer — worth checking.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
