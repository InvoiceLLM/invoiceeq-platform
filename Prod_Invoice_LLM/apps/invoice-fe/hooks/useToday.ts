"use client";

// =============================================================================
// FILE: hooks/useToday.ts
// FEATURE: FE Feature 22 Task 22.4 — keeps the Today list current.
//
// NO LIVE EVENT YET: the spec subscribes to `today_updated` on the tenant SSE
// channel, but the backend emits no such event (plan §4.6a, open item #5). Until
// it does, Today polls every TODAY_POLL_MS and refetches when the tab becomes
// visible again. Swapping the poll for the event later changes only this file.
//
// A slower response never overwrites a newer one (request sequence guard), and a
// failed refresh keeps the last good list on screen with the error beside it.
// =============================================================================

import { useCallback, useEffect, useRef, useState } from "react";
import { getToday, todayErrorOf, type TodayResponse } from "@/lib/today";

export const TODAY_POLL_MS = 60_000;

export interface TodayState {
  data: TodayResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useToday(enabled: boolean): TodayState {
  const [data, setData] = useState<TodayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const sequence = useRef(0);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    const mine = ++sequence.current;
    try {
      const next = await getToday();
      if (mine !== sequence.current) return;
      setData(next);
      setError(null);
    } catch (err) {
      if (mine !== sequence.current) return;
      setError(todayErrorOf(err)?.detail ?? "Today could not be loaded.");
    } finally {
      if (mine === sequence.current) setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    refresh();
    const timer = window.setInterval(refresh, TODAY_POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, refresh]);

  return { data, loading, error, refresh };
}
