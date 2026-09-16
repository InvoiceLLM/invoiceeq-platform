"use client";

// =============================================================================
// FILE: components/today/RunNowButton.tsx
// FEATURE: FE Feature 22 Task 22.23 — Admin "Run now": re-run ATLAS for the tenant
//          instead of waiting for the weekly job.
//
// Contract (invoice-be routers/today.py::run_now, verified 2026-09-16):
//   200 {job_id, status: "enqueued", cooldown_seconds}
//   429 {detail, retry_after_seconds}   — the cooldown is live
//   403                                 — not an Admin
//
// Admin only — hidden for every other role. After a run is queued, and whenever
// the server answers 429, the button is disabled and counts down on its own face
// (no toast). The seconds come from the server, never a hardcoded 600, so the UI
// stays right if the cooldown is retuned. `runNow()` turns the 429 into a result
// (lib/today.ts); any other failure is shown beside the button.
// =============================================================================

import React, { useEffect, useState } from "react";
import { Loader2, Play, Timer } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { runNow, todayErrorOf } from "@/lib/today";

/** `437` -> `"7:17"`. */
export function formatCountdown(totalSeconds: number): string {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function RunNowButton({ onQueued }: { onQueued?: () => void }) {
  const { role, loading } = useAuth();
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [running, setRunning] = useState(false);
  const [queued, setQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const coolingDown = secondsLeft > 0;

  useEffect(() => {
    if (!coolingDown) return;
    const timer = window.setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [coolingDown]);

  if (loading || role !== "Admin") return null;

  const run = async () => {
    if (running || coolingDown) return;
    setRunning(true);
    setError(null);
    setQueued(false);
    try {
      const result = await runNow();
      if (result.kind === "enqueued") {
        setQueued(true);
        setSecondsLeft(result.cooldown_seconds);
        onQueued?.();
      } else {
        setSecondsLeft(result.retry_after_seconds);
      }
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not start a run. Try again.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {queued && coolingDown && (
        <span role="status" className="text-xs text-emerald-300">
          Run queued — Today updates when it finishes.
        </span>
      )}
      {error && (
        <span role="alert" className="text-xs text-rose-300">
          {error}
        </span>
      )}
      <button
        type="button"
        data-testid="today-run-now"
        onClick={run}
        disabled={running || coolingDown}
        title={coolingDown ? "ATLAS ran recently. You can run it again when the countdown ends." : "Re-run ATLAS now"}
        className="inline-flex items-center gap-1.5 rounded-lg border border-[#222D3D] bg-[#0F172A] px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {running ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : coolingDown ? (
          <Timer className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <Play className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {coolingDown ? `Run again in ${formatCountdown(secondsLeft)}` : "Run now"}
      </button>
    </div>
  );
}
