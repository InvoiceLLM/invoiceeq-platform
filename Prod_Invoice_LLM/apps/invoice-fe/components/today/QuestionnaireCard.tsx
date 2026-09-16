"use client";

// =============================================================================
// FILE: components/today/QuestionnaireCard.tsx
// FEATURE: FE Feature 22 Task 22.22 — the routine questionnaire, one question at
//          a time (BE 33.28 / 33.29).
//
// Contract (routers/today.py, verified 2026-09-17):
//   GET  /today/questionnaire?path=setup|ingest  -> {completed, question}
//   POST /today/questionnaire/answer {key, value, path} -> {saved_key, has_next, next_question}
//
// Every question offers its chips AND a free-text field — a chip is a shortcut,
// never a cage — plus Skip. The posted value is always the backend's own chip key
// or the user's text; chips are only relabelled for reading (`chipLabel`).
//   - collections_owner (answer_kind "user"): a picker of the tenant's people,
//     with free text still available (the owner may not have an account).
//   - approval_threshold / month_close_day: pre-filled from the server's
//     `default_value` (₹1,00,000 / 30), never a hardcoded default.
// Skip saves an empty answer (`SKIPPED_ANSWER` — the API has no skip field).
//
// Progress is "Question N", counted from the answers already saved
// (`GET /today/routine-answers`). The API does not expose how many questions
// there are, so no "of 6" is invented (plan open item #23).
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, ClipboardList, Loader2 } from "lucide-react";
import {
  SKIPPED_ANSWER,
  answerQuestionnaire,
  chipLabel,
  getRoutineAnswers,
  listAnswerableUsers,
  todayErrorOf,
  type AnswerableUser,
  type QuestionnairePath,
  type RoutineQuestion,
} from "@/lib/today";

interface QuestionnaireCardProps {
  initialQuestion: RoutineQuestion;
  path: QuestionnairePath;
  /** Called once the last question is answered or skipped. */
  onComplete?: () => void;
}

export default function QuestionnaireCard({ initialQuestion, path, onComplete }: QuestionnaireCardProps) {
  const [question, setQuestion] = useState<RoutineQuestion | null>(initialQuestion);
  const [value, setValue] = useState(initialQuestion.default_value ?? "");
  const [answeredCount, setAnsweredCount] = useState<number | null>(null);
  const [users, setUsers] = useState<AnswerableUser[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    getRoutineAnswers()
      .then((result) => {
        if (!cancelled) setAnsweredCount(Object.keys(result.answers ?? {}).length);
      })
      .catch(() => {
        if (!cancelled) setAnsweredCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const needsUsers = question?.answer_kind === "user";
  useEffect(() => {
    if (!needsUsers) return;
    let cancelled = false;
    void listAnswerableUsers().then((list) => {
      if (!cancelled) setUsers(list);
    });
    return () => {
      cancelled = true;
    };
  }, [needsUsers]);

  if (!question) {
    return (
      <div data-testid="questionnaire-complete" className="flex items-center gap-2 rounded-xl border border-emerald-800/40 bg-emerald-950/20 px-5 py-3.5 text-xs text-emerald-200">
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
        Thanks — your routine is saved. Today will use it from the next run.
      </div>
    );
  }

  const submit = async (answer: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setError(null);
    try {
      const result = await answerQuestionnaire({ key: question.key, value: answer, path });
      setAnsweredCount((count) => (count === null ? null : count + 1));
      const next = result.has_next ? result.next_question : null;
      setQuestion(next);
      setValue(next?.default_value ?? "");
      if (!next) onComplete?.();
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not save this answer. Try again.");
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  };

  const numeric = question.answer_kind === "number" || question.answer_kind === "currency_amount";
  const trimmed = value.trim();

  return (
    <section
      data-testid="questionnaire-card"
      aria-labelledby="questionnaire-prompt"
      className="flex flex-col gap-3 rounded-xl border border-sky-900/50 bg-sky-950/10 px-5 py-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-sky-300">
          <ClipboardList className="h-3.5 w-3.5" aria-hidden="true" />
          Your routine
        </p>
        {answeredCount !== null && (
          <p data-testid="questionnaire-progress" className="text-[11px] text-slate-400">
            Question {answeredCount + 1}
          </p>
        )}
      </div>

      <h2 id="questionnaire-prompt" className="text-sm font-semibold text-white">
        {question.prompt}
      </h2>

      {question.chips.length > 0 && (
        <div role="group" aria-label="Suggested answers" className="flex flex-wrap gap-2">
          {question.chips.map((chip) => (
            <button
              key={chip}
              type="button"
              aria-pressed={value === chip}
              onClick={() => setValue(chip)}
              disabled={saving}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                value === chip
                  ? "border-sky-500 bg-sky-500/20 text-sky-100"
                  : "border-[#222D3D] text-slate-300 hover:border-slate-500 hover:text-white"
              }`}
            >
              {chipLabel(chip, question.answer_kind)}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (trimmed) void submit(trimmed);
        }}
        className="flex flex-wrap items-end gap-2"
      >
        {needsUsers && users.length > 0 && (
          <label className="flex flex-col gap-1 text-[11px] text-slate-400" htmlFor="questionnaire-user">
            Pick a person
            <select
              id="questionnaire-user"
              value={users.some((u) => u.label === value) ? value : ""}
              onChange={(e) => setValue(e.target.value)}
              disabled={saving}
              className="w-52 rounded-lg border border-[#222D3D] bg-[#0B0F19] px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500/60"
            >
              <option value="">Choose…</option>
              {users.map((user) => (
                <option key={user.id} value={user.label}>
                  {user.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {question.free_text && (
          <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[11px] text-slate-400" htmlFor="questionnaire-text">
            {needsUsers ? "Or type a name" : "Or in your own words"}
            <input
              id="questionnaire-text"
              type={numeric ? "number" : "text"}
              inputMode={numeric ? "numeric" : undefined}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              disabled={saving}
              className="rounded-lg border border-[#222D3D] bg-[#0B0F19] px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500/60"
            />
          </label>
        )}
        <button
          type="submit"
          disabled={!trimmed || saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#3B82F6] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#2563EB] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          Save
        </button>
        {question.skippable && (
          <button
            type="button"
            onClick={() => void submit(SKIPPED_ANSWER)}
            disabled={saving}
            className="rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white disabled:opacity-50"
          >
            Skip
          </button>
        )}
      </form>

      {error && (
        <p role="alert" className="text-xs text-rose-300">
          {error}
        </p>
      )}
    </section>
  );
}
