"use client";

import { useEffect, useState } from "react";

type Sender = { id: string; email: string; email_set: string };

type Props = {
  emailSet: "inbound" | "outbound";
  selected: string[];
  onChange: (emails: string[]) => void;
  className?: string;
};

/**
 * Gap 125: auditor multi-select of registered set emails before terminal actions.
 * Never offers free-text / customer addresses.
 */
export default function NotifyEmailPicker({ emailSet, selected, onChange, className }: Props) {
  const [senders, setSenders] = useState<Sender[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/email/settings/email-senders?email_set=${emailSet}`);
        if (!res.ok) throw new Error(`Failed to load ${emailSet} emails (${res.status})`);
        const data = await res.json();
        const list: Sender[] = Array.isArray(data) ? data : data?.senders ?? [];
        if (!cancelled) setSenders(list);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load emails");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [emailSet]);

  const toggle = (email: string) => {
    const e = email.toLowerCase();
    if (selected.includes(e)) onChange(selected.filter((x) => x !== e));
    else onChange([...selected, e]);
  };

  return (
    <div className={className ?? "flex items-center gap-3 rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-1.5 text-xs shrink-0"}>
      <span className="text-[11px] text-slate-400 font-medium whitespace-nowrap">
        Notify registered emails:
      </span>
      {loading && <span className="text-[11px] text-slate-500 italic">Loading…</span>}
      {error && <span className="text-[11px] text-amber-400">{error}</span>}
      {!loading && !error && senders.length === 0 && (
        <span className="text-[11px] text-slate-500 italic">None set ({emailSet})</span>
      )}
      <div className="flex items-center gap-3 overflow-x-auto custom-scrollbar flex-1 py-0.5">
        {senders.map((s) => {
          const email = s.email.toLowerCase();
          return (
            <label key={s.id} className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer whitespace-nowrap hover:text-white">
              <input
                type="checkbox"
                className="rounded border-slate-600 bg-slate-800 accent-blue-500"
                checked={selected.includes(email)}
                onChange={() => toggle(email)}
              />
              <span>{s.email}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
