"use client";

/**
 * Feature 8 — OutboundEmailSettings.tsx
 *
 * Configures the outbound sender email address for tenant invoice dispatching.
 */

import React, { useState, useEffect } from "react";
import { Send, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

interface OutboundEmailSettingsProps {
  isAdmin: boolean;
}

export default function OutboundEmailSettings({ isAdmin }: OutboundEmailSettingsProps) {
  const [email, setEmail] = useState("");
  const [initialEmail, setInitialEmail] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // --- Load initial settings ---
  const loadSettings = async () => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/settings/service-flow");
      if (!res.ok) throw new Error("Failed to load settings");
      const data = await res.json();
      const outboundEmail = data.outbound_sender_email || "";
      setEmail(outboundEmail);
      setInitialEmail(outboundEmail);
    } catch (err) {
      console.error(err);
      setErrorMsg("Failed to retrieve outbound email settings.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const validateEmail = (value: string) => {
    if (!value.trim()) return true; // Empty value is allowed to clear the sender
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(value.trim().toLowerCase());
  };

  // --- Handle update ---
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateEmail(email)) {
      setErrorMsg("Please enter a valid email format.");
      return;
    }

    setErrorMsg(null);
    setSuccessMsg(null);
    setIsSaving(true);

    try {
      const payload = {
        outbound_sender_email: email.trim() || null
      };

      const res = await fetch("/api/settings/service-flow", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to update outbound email settings.");
      }

      setSuccessMsg("Outbound sender email updated successfully!");
      setInitialEmail(email);
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to save outbound email settings.");
    } finally {
      setIsSaving(false);
    }
  };

  const isChanged = email.trim() !== initialEmail.trim();

  return (
    <div className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-5 shadow-lg">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400">
          <Send className="w-5 h-5" />
        </div>
        <div>
          <h3 className="font-semibold text-sm text-white">Outbound Invoicing Delivery</h3>
          <p className="text-xs text-slate-400">Set the custom from-address used when dispatching invoices</p>
        </div>
      </div>

      {/* Notifications */}
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

      {isLoading ? (
        <div className="flex justify-center items-center py-6 text-slate-500 text-xs gap-2">
          <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
          Loading outbound settings…
        </div>
      ) : (
        <form onSubmit={handleSave} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="outbound-email" className="text-[11px] text-slate-500 font-mono tracking-wide uppercase">
              Outbound Sender Email Address
            </label>
            <input
              id="outbound-email"
              type="text"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isSaving || !isAdmin}
              placeholder="e.g. billing@yourcompany.com"
              className="w-full px-4 py-2.5 rounded-xl bg-[#0B0F19] border border-[#222D3D] text-slate-200 placeholder-slate-500 text-xs focus:outline-none focus:border-blue-500 transition-colors"
            />
            <p className="text-[10px] text-slate-500 leading-normal">
              Before setting this custom address, verify that your domain's SPF, DKIM, and DMARC settings authorize sending from this host to prevent email bouncing.
            </p>
          </div>

          {isAdmin && (
            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={isSaving || !isChanged}
                className="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-md"
              >
                {isSaving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
                Save Settings
              </button>
            </div>
          )}
        </form>
      )}
    </div>
  );
}
