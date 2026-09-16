"use client";

// =============================================================================
// FILE: components/chat/cards/TeachCard.tsx
// FEATURE: FE Feature 22 Task 22.13 — "teach: …" in the Ask composer.
//
// The Trainer as a mode, on the Trainer's EXISTING endpoints (verified 2026-09-17,
// routers/trainer.py — every one needs `can_train` and a paid plan):
//   1. GET  /trainer/vendors                    -> the scope picker
//   2. POST /trainer/sessions/from-invoice      {invoice_id: vendor.sampleInvoiceId}
//   3. POST /trainer/sessions/{id}/chat         {content: rule}  -> newRuleCreated
//   4. POST /trainer/sessions/{id}/preview                        -> previewToken + impact
//   5. POST /trainer/sessions/{id}/commit       {preview_token}   (Confirm)
// Steps 2–4 are "Propose"; nothing is written until Confirm. The preview step is
// kept because the Trainer page always previews before commit (Feature 18's
// stale-preview guard) — skipping it here would be a weaker path to the same write.
//
// SCOPE. The spec says "this vendor / all vendors". The backend removed
// all-vendor (Global) rule creation (Feature 18: commit 400s, /sessions/global
// is 410), so "All vendors" is shown disabled with that reason, not faked
// (plan open item #27). The vendor default comes from `defaultVendorFor`.
// =============================================================================

import React, { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, GraduationCap, Loader2, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { trainerService, type CommitResult, type PreviewResult, type TrainerSession, type VendorOption } from "@/lib/trainer-service";
import { defaultVendorFor } from "@/lib/teach";

const ALL_VENDORS = "__all__";

type Phase =
  | { kind: "scope" }
  | { kind: "proposing" }
  | { kind: "proposed"; session: TrainerSession; rule: string | null; preview: PreviewResult | null }
  | { kind: "committing"; session: TrainerSession; rule: string; preview: PreviewResult }
  | { kind: "committed"; result: CommitResult };

function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

interface TeachCardProps {
  /** The sentence after `teach:`. */
  ruleText: string;
  onClose?: () => void;
}

export default function TeachCard({ ruleText, onClose }: TeachCardProps) {
  const { canTrain, loading: authLoading } = useAuth();
  const [vendors, setVendors] = useState<VendorOption[] | null>(null);
  const [vendorName, setVendorName] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "scope" });
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    if (authLoading || !canTrain) return;
    let cancelled = false;
    trainerService
      .getTenantVendors()
      .then((list) => {
        if (cancelled) return;
        setVendors(list);
        setVendorName(defaultVendorFor(ruleText, list)?.name ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        setVendors([]);
        setError(errorDetail(err, "Could not load your vendors."));
      });
    return () => {
      cancelled = true;
    };
  }, [ruleText, canTrain, authLoading]);

  const vendor = useMemo(() => vendors?.find((v) => v.name === vendorName) ?? null, [vendors, vendorName]);

  const propose = async () => {
    if (!vendor || inFlight.current) return;
    inFlight.current = true;
    setError(null);
    setPhase({ kind: "proposing" });
    try {
      const session = await trainerService.startSessionFromInvoice(vendor.sampleInvoiceId);
      const chat = await trainerService.sendChatMessage(session, ruleText);
      const rule = chat.newRuleCreated ?? null;
      const preview = rule ? await trainerService.previewSession(chat.updatedSession.sessionId) : null;
      setPhase({ kind: "proposed", session: chat.updatedSession, rule, preview });
    } catch (err) {
      setError(errorDetail(err, "The Trainer could not propose a rule. Try again."));
      setPhase({ kind: "scope" });
    } finally {
      inFlight.current = false;
    }
  };

  const confirm = async () => {
    if (phase.kind !== "proposed" || !phase.rule || !phase.preview || inFlight.current) return;
    inFlight.current = true;
    const { session, rule, preview } = phase;
    setError(null);
    setPhase({ kind: "committing", session, rule, preview });
    try {
      const result = await trainerService.commitSession(session, preview.previewToken);
      setPhase({ kind: "committed", result });
    } catch (err) {
      setError(errorDetail(err, "Could not save this rule."));
      setPhase({ kind: "proposed", session, rule, preview });
    } finally {
      inFlight.current = false;
    }
  };

  const busy = phase.kind === "proposing" || phase.kind === "committing";
  const locked = phase.kind !== "scope";

  return (
    <section data-testid="teach-card" aria-label="Teach a rule" className="space-y-3 rounded-xl border border-violet-900/50 bg-violet-950/10 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-violet-300">
            <GraduationCap className="h-3.5 w-3.5" aria-hidden="true" />
            Teach
          </p>
          <p data-testid="teach-card-text" className="text-sm text-white">
            {ruleText}
          </p>
        </div>
        {onClose && !busy && (
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white">
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
      </div>

      {authLoading ? null : !canTrain ? (
        <p data-testid="teach-card-no-permission" className="text-xs text-amber-300">
          You don&apos;t have permission to teach rules. Ask an Admin to turn on training for your account.
        </p>
      ) : phase.kind === "committed" ? (
        <p data-testid="teach-card-committed" className="inline-flex items-center gap-1.5 text-xs text-emerald-300">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          Saved for {phase.result.vendorName ?? vendorName} (version {phase.result.version})
          {phase.result.reauditQueued ? " — re-checking their past invoices." : "."}
        </p>
      ) : (
        <>
          <label htmlFor="teach-scope" className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            Applies to
            {vendors === null ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-label="Loading vendors" />
            ) : (
              <select
                id="teach-scope"
                value={vendorName}
                onChange={(e) => setVendorName(e.target.value)}
                disabled={locked}
                className="rounded-lg border border-[#222D3D] bg-[#0B0F19] px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-violet-500/60 disabled:opacity-60"
              >
                <option value="">Choose a vendor…</option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.name}>
                    {v.name}
                  </option>
                ))}
                <option value={ALL_VENDORS} disabled>
                  All vendors (not available — rules are saved per vendor)
                </option>
              </select>
            )}
          </label>

          {vendors !== null && vendors.length === 0 && !error && (
            <p className="text-xs text-slate-400">No vendors yet — a rule is saved against a vendor, so process one of their invoices first.</p>
          )}

          {(phase.kind === "proposed" || phase.kind === "committing") && (
            <div data-testid="teach-card-proposal" className="rounded-lg border border-[#222D3D] bg-[#0B0F19] px-3 py-2.5 text-xs">
              {phase.rule ? (
                <>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">The Trainer proposes</p>
                  <p data-testid="teach-card-rule" className="text-slate-100">
                    {phase.rule}
                  </p>
                  {phase.preview?.impact?.summary && <p className="mt-1 text-slate-400">{phase.preview.impact.summary}</p>}
                </>
              ) : (
                <p data-testid="teach-card-no-rule" className="text-slate-300">
                  The Trainer didn&apos;t turn this into a new rule. Try saying it more specifically.
                </p>
              )}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {phase.kind === "scope" || phase.kind === "proposing" ? (
              <button
                type="button"
                onClick={() => void propose()}
                disabled={!vendor || busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {phase.kind === "proposing" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                Propose rule
              </button>
            ) : (
              <>
                {phase.rule && (
                  <button
                    type="button"
                    onClick={() => void confirm()}
                    disabled={busy || !phase.preview}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {phase.kind === "committing" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                    Confirm
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setPhase({ kind: "scope" })}
                  disabled={busy}
                  className="rounded-lg px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-white disabled:opacity-50"
                >
                  Change
                </button>
              </>
            )}
          </div>
        </>
      )}

      {error && (
        <p role="alert" className="text-xs text-rose-300">
          {error}
        </p>
      )}
    </section>
  );
}
