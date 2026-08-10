"use client";

/**
 * Feature 8 — authorized email set CRUD (inbound | outbound).
 */

import React, { useState, useEffect } from "react";
import { Mail, Plus, Trash2, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

interface EmailSender {
  id: string;
  email: string;
  email_set: string;
  created_at: string;
}

interface EmailSendersListProps {
  isAdmin: boolean;
  emailSet: "inbound" | "outbound";
  title: string;
  subtitle: string;
  placeholder?: string;
}

export default function EmailSendersList({
  isAdmin,
  emailSet,
  title,
  subtitle,
  placeholder = "name@company.com",
}: EmailSendersListProps) {
  const [senders, setSenders] = useState<EmailSender[]>([]);
  const [newEmail, setNewEmail] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchSenders = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`/api/email/settings/email-senders?email_set=${emailSet}`);
      if (!res.ok) throw new Error("Failed to load senders");
      const data = await res.json();
      setSenders(data);
    } catch (err) {
      console.error(err);
      setErrorMsg("Failed to load authorized emails.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSenders();
  }, [emailSet]);

  const validateEmail = (email: string) => {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email.trim().toLowerCase());
  };

  const handleAddSender = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateEmail(newEmail)) {
      setErrorMsg("Please enter a valid email address.");
      return;
    }

    setErrorMsg(null);
    setSuccessMsg(null);
    setIsSubmitting(true);

    try {
      const res = await fetch("/api/email/settings/email-senders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: newEmail.trim(), email_set: emailSet }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to add email address.");
      }

      setNewEmail("");
      setSuccessMsg("Email address added.");
      fetchSenders();
    } catch (err: any) {
      setErrorMsg(err.message || "An error occurred.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteSender = async (id: string) => {
    setErrorMsg(null);
    setSuccessMsg(null);
    setDeletingId(id);

    try {
      const res = await fetch(`/api/email/settings/email-senders/${id}`, {
        method: "DELETE",
      });

      if (!res.ok) throw new Error("Failed to delete email address.");

      setSuccessMsg("Email address removed.");
      fetchSenders();
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to remove email address.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <h3 className="font-semibold text-xs text-white uppercase tracking-wider">{title}</h3>
        <p className="text-[11px] text-slate-400">{subtitle}</p>
      </div>

      {errorMsg && (
        <div className="flex items-start gap-2.5 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div className="flex items-start gap-2.5 px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs">
          <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{successMsg}</span>
        </div>
      )}

      {isAdmin && (
        <form onSubmit={handleAddSender} className="flex gap-3">
          <input
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            disabled={isSubmitting}
            placeholder={placeholder}
            className="flex-1 px-4 py-2.5 rounded-xl bg-[#0B0F19] border border-[#222D3D] text-slate-200 placeholder-slate-500 text-xs focus:outline-none focus:border-blue-500 transition-colors"
          />
          <button
            type="submit"
            disabled={isSubmitting || !newEmail.trim()}
            className="px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-md shadow-blue-900/10"
          >
            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Add
          </button>
        </form>
      )}

      <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
        {isLoading ? (
          <div className="flex justify-center items-center py-6 text-slate-500 text-xs gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
            Loading…
          </div>
        ) : senders.length === 0 ? (
          <div className="text-center py-6 text-slate-500 text-xs">
            No addresses in this set yet.
          </div>
        ) : (
          senders.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between px-4 py-3 rounded-xl bg-[#0F141F] border border-[#1E293B]"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Mail className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                <span className="text-xs text-slate-200 truncate font-mono">{s.email}</span>
              </div>

              {isAdmin && (
                <button
                  onClick={() => handleDeleteSender(s.id)}
                  disabled={deletingId === s.id}
                  className="p-1 rounded-lg hover:bg-[#1E293B] text-slate-500 hover:text-red-400 transition-colors"
                  title="Remove"
                  aria-label={`Remove ${s.email}`}
                >
                  {deletingId === s.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
