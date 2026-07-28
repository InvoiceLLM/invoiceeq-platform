"use client";

/**
 * Feature 10 — ServiceFlowToggles.tsx
 *
 * Two independently-toggleable switches:
 *   - Receive Invoices (Inbound / AP)
 *   - Send Invoices    (Outbound / AR) — requires outbound_sender_email + pro_combined plan
 *
 * Behaviour:
 *   - Admin: both switches and the sender-email field are interactive.
 *   - Non-Admin: everything renders disabled with an explanatory tooltip.
 *   - Trying to enable "Send Invoices" with an empty sender email → blocked client-side,
 *     inline error shown, no network call made.
 *   - If the tenant's billing_plan is not 'pro_combined' and Admin tries to enable
 *     "Send Invoices" → opens the Combined Pro Upgrade Modal instead.
 */

import React, { useState, useEffect } from "react";
import {
  Download,
  Send,
  Lock,
  AlertCircle,
  CheckCircle2,
  Loader2,
  ExternalLink,
  X,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ServiceFlowState {
  receive_invoices_enabled: boolean;
  send_invoices_enabled: boolean;
  outbound_sender_email: string | null;
  billing_plan: string;
}

interface Toast {
  text: string;
  type: "success" | "error" | "info";
}

// ---------------------------------------------------------------------------
// Upgrade Modal
// ---------------------------------------------------------------------------

function UpgradeModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-md mx-4 bg-[#0F172A] border border-[#222D3D] rounded-2xl shadow-2xl p-6">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-500 hover:text-slate-300 transition-colors"
          aria-label="Close upgrade modal"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
            <Send className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h2 className="text-white font-semibold text-sm">Upgrade Required</h2>
            <p className="text-slate-400 text-xs">Pro Combined Plan</p>
          </div>
        </div>

        {/* Body */}
        <p className="text-slate-300 text-xs leading-relaxed mb-4">
          Sending invoices (Outbound / AR) requires the{" "}
          <span className="text-violet-300 font-semibold">Pro Combined Plan</span> at{" "}
          <span className="text-white font-semibold">₹8,999 / month</span>. This plan includes
          unlimited inbound and outbound invoice processing.
        </p>

        <div className="bg-[#1E293B] border border-[#2D3F55] rounded-xl p-3 mb-5 space-y-1.5">
          {[
            "Unlimited inbound invoice ingestion (AP)",
            "Unlimited outbound invoice delivery (AR)",
            "Email, Webhook & Connector support",
          ].map((feat) => (
            <div key={feat} className="flex items-center gap-2 text-xs text-slate-300">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              {feat}
            </div>
          ))}
        </div>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-lg border border-[#2D3F55] text-slate-400 text-xs hover:text-slate-200 hover:border-slate-500 transition-colors"
          >
            Cancel
          </button>
          <a
            href="/billing/upgrade"
            className="flex-1 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium flex items-center justify-center gap-1.5 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Upgrade Now
          </a>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ServiceFlowToggles({ role }: { role: string }) {
  const isAdmin = role === "Admin";

  const [settings, setSettings] = useState<ServiceFlowState | null>(null);
  const [senderEmailDraft, setSenderEmailDraft] = useState("");
  const [emailError, setEmailError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [toast, setToast] = useState<Toast | null>(null);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);

  // --- Load current service flow settings on mount ---
  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch("/api/settings/service-flow");
        if (!res.ok) throw new Error("Failed to load settings");
        const data: ServiceFlowState = await res.json();
        setSettings(data);
        setSenderEmailDraft(data.outbound_sender_email ?? "");
      } catch {
        showToast("Failed to load service flow settings.", "error");
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, []);

  const showToast = (text: string, type: Toast["type"] = "success") => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 5000);
  };

  // --- Save helper ---
  const save = async (patch: Partial<ServiceFlowState>) => {
    setIsSaving(true);
    try {
      const res = await fetch("/api/settings/service-flow", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.detail ?? "Failed to save settings.", "error");
        return false;
      }
      setSettings(data);
      setSenderEmailDraft(data.outbound_sender_email ?? "");
      showToast("Settings saved.", "success");
      return true;
    } catch {
      showToast("Network error — could not save settings.", "error");
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  // --- Toggle handlers ---
  const handleToggleReceive = async () => {
    if (!isAdmin || !settings) return;
    await save({ receive_invoices_enabled: !settings.receive_invoices_enabled });
  };

  const handleToggleSend = async () => {
    if (!isAdmin || !settings) return;

    const enablingNow = !settings.send_invoices_enabled;

    if (enablingNow) {
      // Client-side email guard
      const email = senderEmailDraft.trim();
      if (!email) {
        setEmailError("Outbound Sender Email is required before enabling Send Invoices.");
        return;
      }
      // Billing plan guard
      if (settings.billing_plan !== "pro_combined") {
        setShowUpgradeModal(true);
        return;
      }
    }

    await save({
      send_invoices_enabled: enablingNow,
      outbound_sender_email: senderEmailDraft.trim() || null,
    });
  };

  const handleSaveEmail = async () => {
    if (!isAdmin || !settings) return;
    const email = senderEmailDraft.trim();
    if (!email) {
      setEmailError("Please enter a valid email address.");
      return;
    }
    setEmailError("");
    await save({ outbound_sender_email: email });
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-slate-500 text-xs py-8 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading settings…
      </div>
    );
  }

  if (!settings) return null;

  const disabledTooltip = !isAdmin
    ? "Only Admin users can change these settings."
    : undefined;

  return (
    <>
      {/* Toast */}
      {toast && (
        <div className="fixed top-5 right-5 z-50 animate-in slide-in-from-top duration-300">
          <div
            className={`flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl border text-xs font-medium ${
              toast.type === "success"
                ? "bg-[#10B981]/15 text-emerald-300 border-[#10B981]/40"
                : toast.type === "error"
                ? "bg-[#EF4444]/15 text-red-300 border-[#EF4444]/40"
                : "bg-[#3B82F6]/15 text-blue-300 border-[#3B82F6]/40"
            }`}
          >
            {toast.type === "error" ? (
              <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
            ) : (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            )}
            <span>{toast.text}</span>
            <button onClick={() => setToast(null)} className="p-1 hover:bg-white/10 rounded ml-2">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Upgrade Modal */}
      {showUpgradeModal && <UpgradeModal onClose={() => setShowUpgradeModal(false)} />}

      <div className="space-y-4">
        {/* Non-Admin read-only banner */}
        {!isAdmin && (
          <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300">
            <Lock className="w-4 h-4 shrink-0" />
            These settings are read-only for your role. Contact an Admin to make changes.
          </div>
        )}

        {/* Receive Invoices toggle */}
        <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
              <Download className="w-4 h-4 text-blue-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-white">Receive Invoices</p>
              <p className="text-xs text-slate-400">Inbound AP — process incoming vendor invoices</p>
            </div>
          </div>

          <button
            title={disabledTooltip}
            disabled={!isAdmin || isSaving}
            onClick={handleToggleReceive}
            className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500/40 ${
              settings.receive_invoices_enabled ? "bg-blue-600" : "bg-[#2D3F55]"
            } ${!isAdmin ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            role="switch"
            aria-checked={settings.receive_invoices_enabled}
            id="toggle-receive-invoices"
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${
                settings.receive_invoices_enabled ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {/* Outbound Sender Email */}
        <div className="px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B] space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Send className="w-3.5 h-3.5 text-violet-400" />
            <p className="text-xs font-medium text-slate-300">Outbound Sender Email</p>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-500/20 font-mono">
              AR
            </span>
          </div>
          <p className="text-[11px] text-slate-500">
            The "From" address used when delivering verified outbound invoices to customers.
          </p>

          <div className="flex gap-2">
            <input
              id="outbound-sender-email"
              type="email"
              value={senderEmailDraft}
              onChange={(e) => {
                setSenderEmailDraft(e.target.value);
                if (emailError) setEmailError("");
              }}
              disabled={!isAdmin || isSaving}
              placeholder="invoices@yourcompany.com"
              className={`flex-1 bg-[#0D131F] border rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500/50 transition-colors ${
                emailError ? "border-red-500/60" : "border-[#2D3F55]"
              } ${!isAdmin ? "opacity-50 cursor-not-allowed" : ""}`}
            />
            {isAdmin && (
              <button
                onClick={handleSaveEmail}
                disabled={isSaving}
                className="px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-medium transition-colors flex items-center gap-1.5"
              >
                {isSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Save
              </button>
            )}
          </div>

          {emailError && (
            <p className="flex items-center gap-1.5 text-[11px] text-red-400">
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
              {emailError}
            </p>
          )}
        </div>

        {/* Send Invoices toggle */}
        <div className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl bg-[#111827] border border-[#1E293B]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
              <Send className="w-4 h-4 text-violet-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-white">Send Invoices</p>
              <p className="text-xs text-slate-400">
                Outbound AR — deliver verified invoices to customers
                {settings.billing_plan !== "pro_combined" && (
                  <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-500/20 font-mono">
                    Requires Pro Combined
                  </span>
                )}
              </p>
            </div>
          </div>

          <button
            title={disabledTooltip}
            disabled={!isAdmin || isSaving}
            onClick={handleToggleSend}
            className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-violet-500/40 ${
              settings.send_invoices_enabled ? "bg-violet-600" : "bg-[#2D3F55]"
            } ${!isAdmin ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            role="switch"
            aria-checked={settings.send_invoices_enabled}
            id="toggle-send-invoices"
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${
                settings.send_invoices_enabled ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {/* Pro Combined active confirmation */}
        {settings.billing_plan === "pro_combined" && (
          <p className="flex items-center gap-1.5 text-[11px] text-emerald-400 px-1">
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
            Pro Combined plan active — outbound features available.
          </p>
        )}
      </div>
    </>
  );
}
