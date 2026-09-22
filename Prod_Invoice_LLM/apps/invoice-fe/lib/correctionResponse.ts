import { isAxiosError } from "axios";

/** One field's change as the server recorded it (`corrections_applied` in a resolve response). */
export interface CorrectionChange {
  old: unknown;
  new: unknown;
}

interface InvalidCorrection {
  field: string;
  reason: string;
}

/** FE Gap 499: the values the server actually saved, keyed by field — never the values that were sent. */
export function savedValues<T>(correctionsApplied: Record<string, CorrectionChange> | null | undefined): Partial<T> {
  const saved: Record<string, unknown> = {};
  for (const [field, change] of Object.entries(correctionsApplied ?? {})) {
    saved[field] = change?.new;
  }
  return saved as Partial<T>;
}

/** An alert as stored in `sa_alerts`. `id` is present only on alerts that carry one. */
export interface AuditAlert {
  id?: string;
  type: string;
  message: string;
  field?: string;
  /** BE Gap 535: "correction" when a correction's arithmetic re-check raised this alert. */
  raised_by?: string;
}

/** BE Gap 537: what identifies ONE alert in a dismissal — its id, else type + field + message. Never the message alone. */
export function alertRef(alert: AuditAlert): { id: string } | { type: string; field?: string; message: string } {
  return alert.id ? { id: alert.id } : { type: alert.type, field: alert.field, message: alert.message };
}

/** BE Gaps 535/538: what a successful resolve needs the auditor to know, or null when there is nothing. */
export function resolveNotice(
  data: { raised_alerts?: unknown[]; unmatched_dismissals?: unknown[] } | null | undefined
): string | null {
  const notes: string[] = [];
  const raised = data?.raised_alerts?.length ?? 0;
  if (raised > 0) {
    notes.push(
      `Saved — but the corrected figures no longer add up, so ${raised === 1 ? "a new alert was" : `${raised} new alerts were`} raised.`
    );
  }
  const unmatched = data?.unmatched_dismissals?.length ?? 0;
  if (unmatched > 0) {
    notes.push(
      `${unmatched === 1 ? "One alert was" : `${unmatched} alerts were`} already cleared (for example in another tab), so nothing was dismissed for ${unmatched === 1 ? "it" : "them"}.`
    );
  }
  return notes.length > 0 ? notes.join(" ") : null;
}

/** FE Gap 499: a plain "Not saved" message for a failed resolve, naming each field the server refused. */
export function correctionErrorMessage(err: unknown): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    const invalid: InvalidCorrection[] | undefined = detail?.invalid_corrections;
    if (Array.isArray(invalid) && invalid.length > 0) {
      return `Not saved — ${invalid.map((c) => `${c.field}: ${c.reason}`).join("; ")}`;
    }
    if (typeof detail === "string" && detail) {
      return `Not saved — ${detail}`;
    }
    // FE Gap 717 (Finding F-12): a slow rule save outliving the proxy is not a refusal.
    // Differentiate an unconfirmed network timeout / socket drop from a server rejection
    // to prevent destructive repeated retries creating duplicate rule versions.
    if (
      err.code === "ECONNABORTED" ||
      err.code === "ETIMEDOUT" ||
      err.code === "ERR_NETWORK" ||
      !err.response
    ) {
      return "Save request timed out waiting for server confirmation. The change may still have saved — please check Rule History before retrying to avoid duplicate rules.";
    }
  }
  return "Not saved — the server did not accept this change. Please try again.";
}
