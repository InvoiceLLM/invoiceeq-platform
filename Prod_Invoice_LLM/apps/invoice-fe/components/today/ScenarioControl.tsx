"use client";

// =============================================================================
// FILE: components/today/ScenarioControl.tsx
// FEATURE: FE Feature 22 Task 22.20 — "what if Kaveri pays 20 days late?" under
//          Today's Cash section.
//
// One change -> `POST /today/{id}/scenario` with
// `{change: {counterparty, delay_days}, horizon_days: 30}` (the horizon Today's
// own cash lines use) -> the backend's recomputed `certain_summary`, rendered as
// one sentence PER CURRENCY. Nothing is recomputed or blended here — no
// optimistic preview; the arithmetic is `services/forecast.py::scenario()`.
//
// Supported change keys are the backend's (scenario() docstring): this control
// sends `counterparty` + `delay_days` only. The route ignores its `{item_id}`
// segment (routers/today.py::run_scenario_route); "cash" is sent as the id.
//
// Lives inside the Cash section, which the server only sends to roles allowed
// to see cash — so the control needs no role check of its own.
//
// FpaLine (the other half of 22.20) is blocked: `GET /today` sends no FP&A lines
// (plan open item #18).
// =============================================================================

import React, { useRef, useState } from "react";
import { FlaskConical, Loader2, X } from "lucide-react";
import { runScenario, todayErrorOf } from "@/lib/today";

export const SCENARIO_HORIZON_DAYS = 30;

export default function ScenarioControl() {
  const [open, setOpen] = useState(false);
  const [counterparty, setCounterparty] = useState("");
  const [delayDays, setDelayDays] = useState("");
  const [running, setRunning] = useState(false);
  // A ref, not just state: two clicks in the same tick both see `running === false`.
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ currency: string; text: string }[] | null>(null);

  const days = Number(delayDays);
  const valid = counterparty.trim() !== "" && Number.isInteger(days) && days !== 0 && Math.abs(days) <= 365;

  const run = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!valid || inFlight.current) return;
    inFlight.current = true;
    setRunning(true);
    setError(null);
    try {
      const response = await runScenario("cash", {
        change: { counterparty: counterparty.trim(), delay_days: days },
        horizon_days: SCENARIO_HORIZON_DAYS,
      });
      setResult(
        (response.currencies ?? []).map((currency) => ({
          currency,
          text: response.certain_summary?.[currency] ?? "",
        }))
      );
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not run this scenario. Try again.");
    } finally {
      inFlight.current = false;
      setRunning(false);
    }
  };

  const reset = () => {
    setResult(null);
    setError(null);
  };

  if (!open) {
    return (
      <div className="px-5 py-2.5">
        <button
          type="button"
          data-testid="scenario-open"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-400 hover:text-sky-300"
        >
          <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
          What if a customer pays late?
        </button>
      </div>
    );
  }

  return (
    <div data-testid="scenario-control" className="flex flex-col gap-3 border-t border-[#1E293B] px-5 py-3.5">
      <form onSubmit={run} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-slate-400" htmlFor="scenario-counterparty">
          Who
          <input
            id="scenario-counterparty"
            value={counterparty}
            onChange={(e) => setCounterparty(e.target.value)}
            placeholder="e.g. Kaveri Traders"
            className="w-48 rounded-lg border border-[#222D3D] bg-[#0B0F19] px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500/60"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-slate-400" htmlFor="scenario-delay">
          Days late
          <input
            id="scenario-delay"
            type="number"
            inputMode="numeric"
            value={delayDays}
            onChange={(e) => setDelayDays(e.target.value)}
            placeholder="20"
            className="w-24 rounded-lg border border-[#222D3D] bg-[#0B0F19] px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500/60"
          />
        </label>
        <button
          type="submit"
          disabled={!valid || running}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#3B82F6] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#2563EB] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          Recalculate
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          aria-label="Close scenario"
          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-white"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </form>

      {error && (
        <p role="alert" className="text-xs text-rose-300">
          {error}
        </p>
      )}

      {result && (
        <div data-testid="scenario-result" className="flex flex-col gap-1.5 rounded-lg border border-sky-900/40 bg-sky-950/20 px-3 py-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-sky-300">
            If {counterparty.trim()} pays {Math.abs(days)} days {days > 0 ? "late" : "early"}
          </p>
          {result.length === 0 ? (
            <p className="text-xs text-slate-400">No cash position to recalculate.</p>
          ) : (
            result.map((line) => (
              <p key={line.currency} data-testid="scenario-line" data-currency={line.currency} className="text-xs text-slate-100">
                {line.text}
              </p>
            ))
          )}
        </div>
      )}
    </div>
  );
}
