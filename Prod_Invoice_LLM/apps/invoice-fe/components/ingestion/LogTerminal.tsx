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
}

/**
 * Gap 2: scrolling console of real per-stage log lines (OCR, classify,
 * dynamic_qa, extract, verify, chunking, embedding), sourced from the same
 * SSE channel StatusTable subscribes to for status — filtered here to just
 * the `type: "log_line"` events, which StatusTable ignores (it keys off
 * `status`/`invoice_id`). Opens its own EventSource regardless of batch size,
 * since log visibility is independent of StatusTable's polling/SSE choice.
 */
export default function LogTerminal({ batchId }: LogTerminalProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setLines([]);
    if (!batchId) return;

    const es = new EventSource(`/api/invoices/stream/${batchId}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === "log_line" && payload?.message) {
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
                level: payload.level ?? (payload.status === "FAILED" ? "error" : "info"),
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
  }, [batchId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  if (!batchId) return null;

  const levelColor = (level: LogLine["level"]) =>
    level === "error" ? "text-rose-400" : level === "warn" ? "text-amber-400" : "text-emerald-400";

  return (
    <div className="glass-panel rounded-xl border border-[#222D3D] overflow-hidden">
      <div className="px-4 py-3 border-b border-[#222D3D] flex items-center gap-2">
        <Terminal className="w-4 h-4 text-slate-500" />
        <span className="text-xs font-semibold text-slate-300">Live Processing Log</span>
        <span className="ml-auto text-[10px] px-2 py-0.5 rounded-full bg-[#22D3EE]/10 text-[#22D3EE] border border-[#22D3EE]/30 font-mono font-semibold">NOVA</span>
      </div>
      <div className="bg-[#0B0F19] p-3 h-40 overflow-y-auto font-mono text-[11px] leading-relaxed">
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
