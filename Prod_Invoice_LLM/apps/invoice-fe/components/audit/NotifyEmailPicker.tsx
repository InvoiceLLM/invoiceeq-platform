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
    <div className={className ?? "rounded-lg border border-slate-700/60 bg-slate-900/40 p-3"}>
      <p className="text-xs font-medium text-slate-300 mb-1">Notify registered emails</p>
      <p className="text-[11px] text-slate-500 mb-2">
        Staff only — the app never emails customers. Leave unchecked to skip email.
      </p>
      {loading && <p className="text-[11px] text-slate-500">Loading…</p>}
      {error && <p className="text-[11px] text-amber-400">{error}</p>}
      {!loading && !error && senders.length === 0 && (
        <p className="text-[11px] text-slate-500">
          No {emailSet} addresses in Settings → Email. Add some to enable notify.
        </p>
      )}
      <ul className="space-y-1.5 max-h-28 overflow-y-auto">
        {senders.map((s) => {
          const email = s.email.toLowerCase();
          return (
            <li key={s.id}>
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  className="rounded border-slate-600 bg-slate-800"
                  checked={selected.includes(email)}
                  onChange={() => toggle(email)}
                />
                <span className="truncate">{s.email}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
