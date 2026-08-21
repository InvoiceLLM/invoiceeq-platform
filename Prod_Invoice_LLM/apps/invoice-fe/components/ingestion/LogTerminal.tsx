"use client";

import React, { useEffect, useRef, useState } from "react";
import { Terminal } from "lucide-react";

interface LogLine {
  id: string;
  invoiceId: string | null;
  message: string;
  level: "info" | "warn" | "error";
}

interface LogTerminalProps {
  batchId: string | null;
  /**
   * Gap 284: also render the coarse stage events (`{status, message}`) that
   * `_publish_sse_events` puts on the same channel, not just `type:
   * "log_line"` events.
   *
   * Off by default, which is the inbound behaviour and must stay that way:
   * `queue_worker/handlers.py::handle_process_invoice` publishes both kinds,
   * so turning this on for inbound would interleave four coarse duplicates
   * into an already-detailed per-stage feed.
   *
   * On for outbound, where it is the only thing that makes this component
   * show anything at all: `queue_worker/outbound_handlers.py` has no `on_log`
   * callback and never publishes a single `log_line` event — its four
   * `_publish_sse_events` calls (PROCESSING_OCR / EXTRACTING_DATA / the
   * terminal status / FAILED) carry human-readable `message` strings and are
   * the whole of outbound's log stream today.
   */
  includeStatusEvents?: boolean;
}

/**
 * Gap 2: scrolling console of real per-stage log lines (OCR, classify,
 * dynamic_qa, extract, verify, chunking, embedding), sourced from the same
 * SSE channel StatusTable subscribes to for status — filtered here to just
 * the `type: "log_line"` events, which StatusTable ignores (it keys off
 * `status`/`invoice_id`). Opens its own EventSource regardless of batch size,
 * since log visibility is independent of StatusTable's polling/SSE choice.
 */
export default function LogTerminal({ batchId, includeStatusEvents = false }: LogTerminalProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  // FE Gap 268: whether the user was already at (or near) the bottom before
  // this render's new line arrived. Starts true so the first lines still
  // auto-scroll into view. Ref, not state -- must be read synchronously
  // inside the scroll handler and the lines effect below without triggering
  // its own re-render.
  const isNearBottomRef = useRef(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isNearBottomRef.current = distanceFromBottom < 40;
  };

  useEffect(() => {
    setLines([]);
    if (!batchId) return;

    const es = new EventSource(`/api/invoices/stream/${batchId}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const isLogLine = payload?.type === "log_line";
        // Gap 284: a stage event is anything else on this channel that still
        // carries a human-readable message -- i.e. `_publish_sse_events`'
        // `{status, message}` shape. Only consumed when the caller opts in.
        const isStageEvent = includeStatusEvents && !payload?.type && !!payload?.status;
        if ((isLogLine || isStageEvent) && payload?.message) {
          setLines((prev) => {
            const isDuplicate = prev.slice(-3).some(
              (line) => line.invoiceId === (payload.invoice_id ?? null) && line.message === (payload.message ?? "")
            );
            if (isDuplicate) {
              return prev;
            }
            return [
              ...prev,
              {
                id: `${Date.now()}-${prev.length}-${Math.random()}`,
                invoiceId: payload.invoice_id ?? null,
                message: payload.message ?? "",
                level:
                  payload.level ??
                  (payload.status === "FAILED"
                    ? "error"
                    : payload.status === "NEEDS_REVIEW"
                    ? "warn"
                    : "info"),
              },
            ];
          });
        }
      } catch {
        // Non-JSON keep-alive comment lines are expected; ignore.
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [batchId, includeStatusEvents]);

  // FE Gap 268: this used to run unconditionally on every new line, so a
  // user who scrolled up mid-ingestion to read an earlier line got yanked
  // back to the bottom the instant the next line arrived. Now only follows
  // the tail when the user was already there -- matches how any log/chat
  // UI's "stick to bottom unless the reader scrolls away" behavior works.
  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines]);

  if (!batchId) return null;

  const levelColor = (level: LogLine["level"]) =>
    level === "error" ? "text-rose-400" : level === "warn" ? "text-amber-400" : "text-emerald-400";

  return (
    <div data-testid="log-terminal" className="glass-panel rounded-xl border border-[#222D3D] overflow-hidden">
      <div className="px-4 py-3 border-b border-[#222D3D] flex items-center gap-2">
        <Terminal className="w-4 h-4 text-slate-500" />
        <span className="text-xs font-semibold text-slate-300">Live Processing Log</span>
        <span className="ml-auto text-[10px] px-2 py-0.5 rounded-full bg-[#22D3EE]/10 text-[#22D3EE] border border-[#22D3EE]/30 font-mono font-semibold">NOVA</span>
      </div>
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="bg-[#0B0F19] p-3 h-40 overflow-y-auto font-mono text-[11px] leading-relaxed"
      >
        {lines.length === 0 ? (
          <span className="text-slate-600">Waiting for processing to start...</span>
        ) : (
          lines.map((line) => (
            <div key={line.id} className="flex gap-2">
              <span className={levelColor(line.level)}>&gt;</span>
              <span className="text-slate-300">
                {line.invoiceId ? `[${line.invoiceId.slice(0, 8)}] ` : ""}
                {line.message}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
