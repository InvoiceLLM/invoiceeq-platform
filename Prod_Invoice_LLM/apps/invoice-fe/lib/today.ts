// =============================================================================
// FILE: lib/today.ts
// FEATURE: FE Feature 22 Task 22.0 — the Today surface's client, counterpart of
//          BE Feature 33 (apps/invoice-be/routers/today.py and the
//          /auth/me/preferences pair in routers/auth.py).
//
// WHY THIS FILE EXISTS: same reason `lib/chatInsights.ts` does — the shapes that
// mirror one backend module live in one place, and the pure helpers are
// importable by a component and a test without rendering anything.
// `lib/apiClient.ts` is a bare axios instance, not a method surface, so the
// Today methods cannot live there.
//
// SHAPES VERIFIED AGAINST THE LIVE BACKEND, NOT THE SPEC (2026-09-16). Where
// the two disagree the code follows `apps/invoice-be`:
//
//   1. `GET /today` emits `section` ∈ {"findings", "summary"} only
//      (today.py:137-138). The spec's six Today sections have no field to
//      come from — see implementation_plan_FE_feature_22_slices.md §1.5.
//   2. `RoutineQuestion.answer_kind` is "text" | "number" | "user" |
//      "currency_amount" (services/tenant_profile_rules.py:45).
//   3. `/auth/me/preferences` is UNPREFIXED — auth.router is mounted without
//      /api/v1 (main.py:180) — so its proxy cannot use `proxyJson`.
//   4. `POST /today/{id}/scenario` returns the recomputed forecast dicts, not a
//      rendered line (today.py:309).
//   5. `GET /today/questionnaire` returns `{completed, question}`, and the
//      answer route returns `{saved_key, has_next, next_question}` (today.py:426/449).
//   6. `routine-answers` is `{answers: {key: value}, contradictions: [key]}`.
//
// NARRATE, NEVER COMPUTE: nothing in this module sorts, filters, sums or
// blends anything the backend sent. Order is the server's (severity ASC,
// created_at DESC), clearance was applied server-side, and each currency
// stays its own line. A wrong number on Today is a backend bug.
// =============================================================================

import { isAxiosError } from "axios";
import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Shapes — routers/today.py::get_today
// -----------------------------------------------------------------------------

/** `fc.certain_summary` for one currency. `position` is the backend's figure. */
export interface TodayPositionLine {
  currency: string;
  text: string;
  position: number;
}

/** A `TodayItem` row with `section == "findings"`. */
export interface TodayFinding {
  id: string;
  section: string;
  text: string;
  seeded_question: string | null;
  severity: number;
  meta: Record<string, any> | null;
  clearance: string;
  created_at: string | null;
}

/** A `TodayItem` row with `section == "summary"` — carries fewer fields. */
export interface TodaySummaryLine {
  id: string;
  section: string;
  text: string;
  severity: number;
  created_at: string | null;
}

/** An unfulfilled `InputRequest` row — "attach X to unlock Y". */
export interface TodayInputRequest {
  id: string;
  kind: string;
  phrase: string;
  unlock_amount: number | null;
  unlock_currency: string | null;
  unlock_count: number | null;
}

/** `services/conventions.py::ConventionProposal`, minus `rule_target`, which `GET /today` omits. */
export interface ConventionProposal {
  id: string;
  kind: string;
  title: string;
  description: string;
  suggested_rule: string;
  evidence: Record<string, any>;
}

export type RoutineAnswerKind = "text" | "number" | "user" | "currency_amount";

/** `services/tenant_profile_rules.py::RoutineQuestion`. */
export interface RoutineQuestion {
  key: string;
  prompt: string;
  chips: string[];
  free_text: boolean;
  skippable: boolean;
  answer_kind: RoutineAnswerKind | string;
  default_value: string | null;
}

/** Fewer than `ANALYST_ONBOARD_MIN_DOCS` documents — ATLAS has not run. */
export interface TodayPreOnboarding {
  state: "pre_onboarding";
  docs_seen: number;
  docs_required: number;
}

export interface TodayActive {
  state: "active";
  docs_seen: number;
  docs_required: number;
  position_lines: TodayPositionLine[];
  findings: TodayFinding[];
  summary: TodaySummaryLine[];
  input_requests: TodayInputRequest[];
  proposals: ConventionProposal[];
  next_question: RoutineQuestion | null;
}

/**
 * Discriminated on `state` so a consumer that reads `findings` without first
 * handling `pre_onboarding` fails `tsc` — a fresh tenant must never be shown
 * an analysis that has not happened (task 22.25).
 */
export type TodayResponse = TodayPreOnboarding | TodayActive;

// -----------------------------------------------------------------------------
// Shapes — interaction routes
// -----------------------------------------------------------------------------

export interface OpenTodayItemResult {
  session_id: string;
  seeded_question: string;
  item_id: string;
}

export interface DismissTodayItemResult {
  ok: boolean;
  item_id: string;
  dismissed: boolean;
}

export interface ScenarioRequest {
  change: Record<string, any>;
  horizon_days?: number;
}

export interface ScenarioResult {
  ok: boolean;
  currencies: string[];
  cash_position_by_currency: Record<string, number>;
  runway_days_by_currency: Record<string, number | null>;
  certain_summary: Record<string, string>;
  tiers_summary: Record<string, Record<string, number>>;
}

export interface ConfirmActionResult {
  ok: boolean;
  result: Record<string, any>;
}

/** `accept_convention()` — also what `/edit` returns. `ok: false` carries `error`. */
export interface AcceptConventionResult {
  ok: boolean;
  rule_id?: string;
  rule_text?: string;
  error?: string;
}

export interface RejectConventionResult {
  ok: boolean;
  suppressed_kind?: string;
  error?: string;
}

export type QuestionnairePath = "setup" | "ingest";

export type QuestionnaireResult =
  | { completed: true; question: null }
  | { completed: false; question: RoutineQuestion };

export interface QuestionnaireAnswerResult {
  ok: boolean;
  saved_key: string;
  has_next: boolean;
  next_question: RoutineQuestion | null;
}

export interface RoutineAnswersResult {
  answers: Record<string, string>;
  /** Keys whose answer the tenant's own data now contradicts — to be re-asked. */
  contradictions: string[];
}

export interface RoutineAnswerUpdateResult {
  ok: boolean;
  key: string;
  value: string;
}

/**
 * `POST /today/run` has two expected outcomes, not one outcome and an error:
 * a 429 is the cooldown working, and task 22.23 renders its seconds inline on
 * the button. Anything else (403, 500) still throws.
 */
export type RunNowResult =
  | { kind: "enqueued"; job_id: string; status: string; cooldown_seconds: number }
  | { kind: "cooling_down"; retry_after_seconds: number; detail: string };

// -----------------------------------------------------------------------------
// Shapes — routers/auth.py::get_user_preferences (BE 33.39)
// -----------------------------------------------------------------------------

export type LayoutPreference = "surfaces" | "classic";

export interface UserPreferences {
  layout: LayoutPreference;
  first_run_seen: boolean;
  tour_seen: boolean;
  questionnaire_progress: Record<string, any> | null;
}

// -----------------------------------------------------------------------------
// Pure helpers
// -----------------------------------------------------------------------------

export function isPreOnboarding(response: TodayResponse): response is TodayPreOnboarding {
  return response.state === "pre_onboarding";
}

/**
 * The unlock value an input request states, as words: "₹220,000.00 across 5
 * invoices" (`formatCurrency`'s grouping). Formatting only — both figures are
 * the backend's. `null` when the request states neither, so no empty suffix is
 * drawn.
 */
export function formatUnlockValue(request: TodayInputRequest): string | null {
  const parts: string[] = [];
  if (request.unlock_amount !== null && request.unlock_amount !== undefined) {
    parts.push(formatCurrency(request.unlock_amount, request.unlock_currency));
  }
  if (request.unlock_count !== null && request.unlock_count !== undefined) {
    parts.push(`${request.unlock_count} ${request.unlock_count === 1 ? "invoice" : "invoices"}`);
  }
  return parts.length > 0 ? parts.join(" across ") : null;
}

/**
 * The backend's own words for a failed call, so a line can render the 403 on
 * itself (task 22.19) instead of a generic toast. `null` for a non-HTTP error.
 */
export function todayErrorOf(error: unknown): { status: number; detail: string } | null {
  if (!isAxiosError(error) || !error.response) return null;
  const data = error.response.data as { detail?: unknown } | undefined;
  const detail = typeof data?.detail === "string" ? data.detail : error.message;
  return { status: error.response.status, detail };
}

// -----------------------------------------------------------------------------
// Endpoints. Same-origin through app/api/today/** and app/api/auth/me/preferences.
// -----------------------------------------------------------------------------

const seg = encodeURIComponent;

export async function getToday(): Promise<TodayResponse> {
  const response = await apiClient.get<TodayResponse>("/today");
  return response.data;
}

/** Creates the seeded Ask session a Today line opens into. */
export async function openTodayItem(itemId: string): Promise<OpenTodayItemResult> {
  const response = await apiClient.post<OpenTodayItemResult>(`/today/${seg(itemId)}/open`);
  return response.data;
}

/** Clears the line and feeds ATLAS's `learn()`. */
export async function dismissTodayItem(itemId: string): Promise<DismissTodayItemResult> {
  const response = await apiClient.post<DismissTodayItemResult>(`/today/${seg(itemId)}/dismiss`);
  return response.data;
}

export async function runScenario(itemId: string, request: ScenarioRequest): Promise<ScenarioResult> {
  const response = await apiClient.post<ScenarioResult>(`/today/${seg(itemId)}/scenario`, {
    change: request.change,
    horizon_days: request.horizon_days ?? 90,
  });
  return response.data;
}

/** Role-gated. A 403 throws — read it with `todayErrorOf()`. */
export async function confirmAction(itemId: string): Promise<ConfirmActionResult> {
  const response = await apiClient.post<ConfirmActionResult>(`/today/${seg(itemId)}/confirm`);
  return response.data;
}

export async function acceptConvention(proposalId: string): Promise<AcceptConventionResult> {
  const response = await apiClient.post<AcceptConventionResult>(`/today/${seg(proposalId)}/accept`);
  return response.data;
}

export async function rejectConvention(proposalId: string): Promise<RejectConventionResult> {
  const response = await apiClient.post<RejectConventionResult>(`/today/${seg(proposalId)}/reject`);
  return response.data;
}

export async function editConvention(
  proposalId: string,
  ruleText: string,
  target = "tenant_chat_rule"
): Promise<AcceptConventionResult> {
  const response = await apiClient.post<AcceptConventionResult>(`/today/${seg(proposalId)}/edit`, {
    rule_text: ruleText,
    target,
  });
  return response.data;
}

export async function getQuestionnaire(path: QuestionnairePath = "setup"): Promise<QuestionnaireResult> {
  const response = await apiClient.get<QuestionnaireResult>("/today/questionnaire", {
    params: { path },
  });
  return response.data;
}

export async function answerQuestionnaire(payload: {
  key: string;
  value: string;
  path?: QuestionnairePath;
}): Promise<QuestionnaireAnswerResult> {
  const response = await apiClient.post<QuestionnaireAnswerResult>("/today/questionnaire/answer", {
    key: payload.key,
    value: payload.value,
    path: payload.path ?? "setup",
  });
  return response.data;
}

export async function getRoutineAnswers(): Promise<RoutineAnswersResult> {
  const response = await apiClient.get<RoutineAnswersResult>("/today/routine-answers");
  return response.data;
}

export async function updateRoutineAnswer(key: string, value: string): Promise<RoutineAnswerUpdateResult> {
  const response = await apiClient.patch<RoutineAnswerUpdateResult>(
    `/today/routine-answers/${seg(key)}`,
    { value }
  );
  return response.data;
}

export async function runNow(): Promise<RunNowResult> {
  try {
    const response = await apiClient.post<{
      job_id: string;
      status: string;
      cooldown_seconds: number;
    }>("/today/run");
    return { kind: "enqueued", ...response.data };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 429) {
      const data = (error.response.data || {}) as { retry_after_seconds?: number; detail?: string };
      return {
        kind: "cooling_down",
        retry_after_seconds: Number(data.retry_after_seconds ?? 0),
        detail: data.detail ?? "",
      };
    }
    throw error;
  }
}

export async function getPreferences(): Promise<UserPreferences> {
  const response = await apiClient.get<UserPreferences>("/auth/me/preferences");
  return response.data;
}

/** Unknown keys are a backend 400 — the type keeps them from being sent. */
export async function updatePreferences(updates: Partial<UserPreferences>): Promise<UserPreferences> {
  const response = await apiClient.patch<UserPreferences>("/auth/me/preferences", updates);
  return response.data;
}

// -----------------------------------------------------------------------------
// Getting documents in before ATLAS has run — FE Feature 22 Task 22.25.
// Both reuse EXISTING endpoints; nothing here is Today-specific on the backend.
// -----------------------------------------------------------------------------

/**
 * The tenant's forwarding address (`GET /email/settings/mailbox`). `null` when
 * it cannot be read — deliberately no hardcoded fallback address, because
 * showing a user an address their mail would not reach is worse than showing none.
 */
export async function getInboxAddress(): Promise<string | null> {
  try {
    const response = await apiClient.get<{ mailbox?: string | null }>("/email/settings/mailbox");
    const mailbox = response.data?.mailbox?.trim();
    return mailbox ? mailbox : null;
  } catch {
    return null;
  }
}

export interface UploadResult {
  batch_id: string;
  job_ids: string[];
}

/** The Ingest screen's own upload call (`POST /invoices/upload`, gated on `can_load`). */
export async function uploadDocuments(files: File[]): Promise<UploadResult> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await apiClient.post<UploadResult>("/invoices/upload", formData);
  return response.data;
}

/**
 * What a failed upload says, in one place for every Today upload control (22.24 /
 * 22.25): the billing limit gets its own sentence, otherwise the backend's words.
 */
export function uploadErrorMessage(error: unknown): string {
  const failure = todayErrorOf(error);
  if (failure?.status === 402) return "Billing limit reached. Upgrade your plan to process more documents.";
  if (failure && failure.detail && !failure.detail.startsWith("Request failed")) return failure.detail;
  return "The upload failed. Try again, or use Records › Ingest.";
}

// -----------------------------------------------------------------------------
// Today sections — FE Feature 22 Task 22.4
//
// FOUNDER RULING 2026-09-16 (Option B, closes plan §1.5): the FE renders the
// backend's payload lists directly, one section per list, instead of deriving
// the spec's six sections client-side:
//
//   position_lines -> Cash        input_requests -> Needs you
//   proposals      -> Decide      findings       -> Findings
//   summary        -> This week   (not named in the ruling; rendered last)
//
// Each section keeps the server's order and the server's filtering. A list the
// server sends empty (e.g. no Cash lines for a clerk) renders no section at all.
// Custom section headers beyond these are a backend task, not an FE mapping.
// -----------------------------------------------------------------------------

export type TodayLineKind = "position" | "input_request" | "proposal" | "finding" | "summary" | "action";

export interface TodayLineModel {
  key: string;
  kind: TodayLineKind;
  /** The server's sentence — rendered as-is. */
  text: string;
  /** A second line the server also sent (unlock value, proposal description). */
  detail: string | null;
  /**
   * The `TodayItem` id, on the lines `POST /today/{id}/open` accepts — findings and
   * summary rows only. Input requests and proposals carry ids of other tables, and
   * cash lines carry none (task 22.5).
   */
  itemId?: string;
  /** Task 22.18: full proposal object for Decide lines. */
  proposal?: ConventionProposal;
  /** Task 22.19: metadata carrying action and parameters. */
  meta?: Record<string, any> | null;
}

export type TodaySectionKey = "cash" | "needs_you" | "decide" | "findings" | "this_week";

export interface TodaySection {
  key: TodaySectionKey;
  title: string;
  lines: TodayLineModel[];
}

export function todaySections(today: TodayActive): TodaySection[] {
  const sections: TodaySection[] = [
    {
      key: "cash",
      title: "Cash",
      // One line per currency, never a blended total.
      lines: (today.position_lines ?? []).map((line) => ({
        key: `position-${line.currency}`,
        kind: "position",
        text: line.text,
        detail: null,
      })),
    },
    {
      key: "needs_you",
      title: "Needs you",
      lines: (today.input_requests ?? []).map((request) => ({
        key: `input-${request.id}`,
        kind: "input_request",
        text: request.phrase,
        detail: formatUnlockValue(request),
      })),
    },
    {
      key: "decide",
      title: "Decide",
      lines: (today.proposals ?? []).map((proposal) => ({
        key: `proposal-${proposal.id}`,
        kind: "proposal",
        text: proposal.title,
        detail: proposal.description || null,
        proposal,
      })),
    },
    {
      key: "findings",
      title: "Findings",
      lines: (today.findings ?? []).map((finding) => {
        const hasAction = Boolean(finding.meta?.action || finding.meta?.capability);
        return {
          key: `finding-${finding.id}`,
          kind: (hasAction ? "action" : "finding") as TodayLineKind,
          text: finding.text,
          detail: null,
          itemId: finding.id,
          meta: finding.meta,
        };
      }),
    },
    {
      key: "this_week",
      title: "This week",
      lines: (today.summary ?? []).map((line) => ({
        key: `summary-${line.id}`,
        kind: "summary",
        text: line.text,
        detail: null,
        itemId: line.id,
      })),
    },
  ];
  return sections.filter((section) => section.lines.length > 0);
}


// -----------------------------------------------------------------------------
// Where a Today line leads in Ask — FE Feature 22 Task 22.5
// -----------------------------------------------------------------------------

/**
 * `POST /today/{id}/open` creates the Ask session but does not post the question
 * into it; it returns `seeded_question`. The question therefore travels to Ask in
 * the URL, for the composer to pre-fill (task 22.6 reads `seed`).
 */
export function askUrlForOpenedItem(result: OpenTodayItemResult): string {
  const params = new URLSearchParams({ session: result.session_id });
  if (result.seeded_question) params.set("seed", result.seeded_question);
  return `/ask?${params.toString()}`;
}

/** An input request asks for a document: Ask opens with its attach control focused (22.6). */
export const ASK_ATTACH_URL = "/ask?attach=1";


// -----------------------------------------------------------------------------
// Routine questionnaire helpers — FE Feature 22 Task 22.22
// -----------------------------------------------------------------------------

/**
 * How "Skip" is recorded. The backend has no skip field: `next_routine_question()`
 * returns the first question with no saved answer, so the only way past a question
 * is to save one. Skip saves an EMPTY answer — "asked, not answered" — which is
 * also what an edit in Chat Rules (22.27) can later fill in.
 */
export const SKIPPED_ANSWER = "";

/** A chip is a backend key ("accounts_then_owner_above_threshold"); this is only its words. */
export function chipLabel(chip: string, answerKind?: string): string {
  if (answerKind === "currency_amount" && /^\d+$/.test(chip)) return Number(chip).toLocaleString("en-IN");
  const words = chip.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export interface AnswerableUser {
  id: string;
  label: string;
}

/**
 * People who could own collections, for `collections_owner` (answer_kind "user").
 * `GET /admin/users` is Admin-only; any failure returns [] and the card falls back
 * to free text, which the question always accepts.
 */
export async function listAnswerableUsers(): Promise<AnswerableUser[]> {
  try {
    const response = await apiClient.get<
      { id: string; email?: string | null; first_name?: string | null; last_name?: string | null }[]
    >("/admin/users");
    return (response.data ?? []).map((user) => {
      const name = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
      return { id: user.id, label: name || user.email || user.id };
    });
  } catch {
    return [];
  }
}
