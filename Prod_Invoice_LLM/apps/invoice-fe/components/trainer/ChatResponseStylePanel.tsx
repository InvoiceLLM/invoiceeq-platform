"use client";

import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";

export type ResponseLength = "brief" | "balanced" | "detailed";
export type ResponseTone = "formal" | "conversational" | "technical";

interface ChatResponseStylePanelProps {
  sessionId: string;
  onSaved?: () => void;
}

export default function ChatResponseStylePanel({ sessionId, onSaved }: ChatResponseStylePanelProps) {
  const [responseLength, setResponseLength] = useState<ResponseLength>("balanced");
  const [tone, setTone] = useState<ResponseTone>("conversational");
  const [customInstructions, setCustomInstructions] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/trainer/chat-style")
      .then(({ data }) => {
        if (cancelled || !data) return;
        setResponseLength(data.response_length || "balanced");
        setTone(data.tone || "conversational");
        setCustomInstructions(data.custom_instructions || "");
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await apiClient.post(`/trainer/sessions/${sessionId}/commit-behavior`, {
        response_length: responseLength,
        tone,
        custom_instructions: customInstructions,
      });
      setMessage("Response style saved.");
      onSaved?.();
    } catch {
      setMessage("Failed to save response style.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-slate-500">
        Loading response style…
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6 max-w-2xl">
      <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-xs text-amber-200 mb-6">
        These instructions guide how the AI responds in Chat — not what it extracts.
      </div>

      <div className="space-y-6">
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Response length
          </label>
          <div className="mt-2 flex flex-wrap gap-2">
            {(["brief", "balanced", "detailed"] as const).map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => setResponseLength(opt)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border capitalize ${
                  responseLength === opt
                    ? "bg-blue-600/20 border-blue-500/50 text-blue-200"
                    : "border-[#222D3D] text-slate-400 hover:text-slate-200"
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Tone
          </label>
          <div className="mt-2 flex flex-wrap gap-2">
            {(["formal", "conversational", "technical"] as const).map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => setTone(opt)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border capitalize ${
                  tone === opt
                    ? "bg-violet-600/20 border-violet-500/50 text-violet-200"
                    : "border-[#222D3D] text-slate-400 hover:text-slate-200"
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Custom instructions
          </label>
          <textarea
            value={customInstructions}
            onChange={(e) => setCustomInstructions(e.target.value)}
            rows={4}
            placeholder="e.g. Always mention the PO number when summarizing invoices."
            className="mt-2 w-full rounded-lg border border-[#222D3D] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500/50"
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-semibold"
          >
            {saving ? "Saving…" : "Save Response Style"}
          </button>
          {message && <span className="text-xs text-slate-400">{message}</span>}
        </div>
      </div>
    </div>
  );
}
