"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { 
  ArrowLeft, 
  Webhook, 
  Copy, 
  Check, 
  Plus, 
  Trash2, 
  AlertCircle, 
  ShieldAlert, 
  Settings, 
  Info,
  Power,
  RotateCw
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

interface WebhookSub {
  id: string;
  target_url: string;
  subscribed_events: string[];
  enabled: boolean;
  consecutive_failures: number;
  created_at: string;
  updated_at: string;
  secret?: string; // only present upon creation
}

const ALLOWED_EVENTS = [
  { value: "invoice.completed", label: "Inbound Completed", desc: "Fires when an inbound invoice finishes extraction successfully." },
  { value: "invoice.audit_required", label: "Inbound Audit Required", desc: "Fires when an inbound invoice requires human audit." },
  { value: "invoice.paid", label: "Inbound Paid", desc: "Fires when an inbound invoice is marked as paid." },
  { value: "invoice.rejected", label: "Inbound Rejected", desc: "Fires when an inbound invoice is rejected by auditor." },
  { value: "outbound_invoice.sent", label: "Outbound Sent", desc: "Fires when an outbound invoice is dispatched to the recipient." },
  { value: "outbound_invoice.overdue", label: "Outbound Overdue", desc: "Fires when an outbound invoice crosses its payment due date." },
  { value: "outbound_invoice.paid", label: "Outbound Paid", desc: "Fires when an outbound invoice is marked as paid." }
];

export default function WebhooksPage() {
  const { role, loading } = useAuth();
  const isAdmin = role === "Admin";

  const [webhooks, setWebhooks] = useState<WebhookSub[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [targetUrl, setTargetUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [copiedUrlId, setCopiedUrlId] = useState<string | null>(null);

  const fetchWebhooks = async () => {
    try {
      setFetching(true);
      setError(null);
      const res = await fetch("/api/webhooks");
      if (!res.ok) {
        throw new Error(await res.text() || "Failed to load webhooks.");
      }
      const data = await res.json();
      setWebhooks(data);
    } catch (err: any) {
      setError(err.message || "An error occurred while fetching webhooks.");
    } finally {
      setFetching(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchWebhooks();
    }
  }, [isAdmin]);

  const handleCreateWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUrl) return;
    if (selectedEvents.length === 0) {
      alert("Please select at least one event type.");
      return;
    }

    try {
      setSubmitting(true);
      setError(null);
      const res = await fetch("/api/webhooks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_url: targetUrl,
          subscribed_events: selectedEvents
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to create webhook.");
      }

      const newWebhook = await res.json();
      setWebhooks(prev => [...prev, newWebhook]);
      setCreatedSecret(newWebhook.secret);
      
      // Reset form
      setTargetUrl("");
      setSelectedEvents([]);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleWebhook = async (webhook: WebhookSub) => {
    try {
      const res = await fetch(`/api/webhooks/${webhook.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: !webhook.enabled
        })
      });

      if (!res.ok) {
        throw new Error("Failed to toggle status.");
      }

      setWebhooks(prev => prev.map(w => w.id === webhook.id ? { ...w, enabled: !w.enabled } : w));
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDeleteWebhook = async (id: string) => {
    if (!confirm("Are you sure you want to delete this webhook subscription?")) return;

    try {
      const res = await fetch(`/api/webhooks/${id}`, {
        method: "DELETE"
      });

      if (!res.ok) {
        throw new Error("Failed to delete webhook.");
      }

      setWebhooks(prev => prev.filter(w => w.id !== id));
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleCopySecret = () => {
    if (createdSecret) {
      navigator.clipboard.writeText(createdSecret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2000);
    }
  };

  const handleCopyUrl = (url: string, id: string) => {
    navigator.clipboard.writeText(url);
    setCopiedUrlId(id);
    setTimeout(() => setCopiedUrlId(null), 2000);
  };

  const toggleEventSelection = (val: string) => {
    setSelectedEvents(prev => 
      prev.includes(val) ? prev.filter(e => e !== val) : [...prev, val]
    );
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0B0F19] text-slate-400">
        <RotateCw className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-[#0B0F19] text-center p-6">
        <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center text-red-500 mb-4 animate-pulse">
          <ShieldAlert className="w-8 h-8" />
        </div>
        <h1 className="text-xl font-bold text-white mb-2">Access Restricted</h1>
        <p className="text-slate-400 text-sm max-w-sm mb-6">
          Only organization Administrators can configure webhook routes and event notifications.
        </p>
        <Link 
          href="/settings"
          className="px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-medium text-sm transition-all border border-[#222D3D]"
        >
          Return to Settings
        </Link>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      {/* Header */}
      <header className="h-16 border-b border-[#222D3D] bg-[#0F172A]/70 backdrop-blur-md px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href="/settings"
            className="w-9 h-9 rounded-xl bg-slate-500/10 border border-slate-500/20 flex items-center justify-center text-slate-300 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-base font-semibold text-white tracking-wide">Developer Webhooks</h1>
            <p className="text-xs text-slate-400">Register endpoints to receive automated event payloads</p>
          </div>
        </div>

        <button
          onClick={() => {
            setCreatedSecret(null);
            setShowCreateModal(true);
          }}
          className="h-9 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-2 transition-all shadow-md active:scale-95"
        >
          <Plus className="w-4 h-4" />
          Add Endpoint
        </button>
      </header>

      {/* Main Content */}
      <main className="flex-1 px-6 py-8 max-w-4xl w-full mx-auto space-y-6">
        
        {/* Error Display */}
        {error && (
          <div className="flex items-start gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-red-300 text-sm">
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Webhooks List */}
        {fetching ? (
          <div className="space-y-4">
            {[1, 2].map((i) => (
              <div key={i} className="h-28 bg-[#151B26] border border-[#222D3D] rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : webhooks.length === 0 ? (
          <div className="bg-[#151B26] border border-[#222D3D] border-dashed rounded-3xl p-12 text-center space-y-4">
            <div className="w-12 h-12 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mx-auto">
              <Webhook className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-white">No Webhooks Registered</h3>
              <p className="text-xs text-slate-400 max-w-sm mx-auto">
                Configure HTTP callbacks to notify downstream applications (e.g. accounting, ERP) automatically.
              </p>
            </div>
            <button
              onClick={() => {
                setCreatedSecret(null);
                setShowCreateModal(true);
              }}
              className="px-4 py-2 bg-blue-600/10 hover:bg-blue-600/20 border border-blue-500/30 rounded-xl text-blue-400 text-xs font-semibold transition-all inline-flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              Configure Endpoint
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {webhooks.map((sub) => (
              <div 
                key={sub.id} 
                className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 hover:border-slate-700 transition-all space-y-4 shadow-md"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1 flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-slate-200 truncate font-semibold block max-w-md">
                        {sub.target_url}
                      </span>
                      <button
                        onClick={() => handleCopyUrl(sub.target_url, sub.id)}
                        className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                        title="Copy URL"
                      >
                        {copiedUrlId === sub.id ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-1.5 pt-1.5">
                      {sub.subscribed_events.map((evt) => (
                        <span 
                          key={evt} 
                          className="px-2 py-0.5 rounded-md bg-[#0B0F19] border border-[#222D3D] text-[10px] text-slate-400 font-mono"
                        >
                          {evt}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleToggleWebhook(sub)}
                      className={`p-2 rounded-xl border flex items-center justify-center transition-all ${
                        sub.enabled 
                          ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/20" 
                          : "bg-slate-500/10 border-slate-500/20 text-slate-400 hover:bg-slate-500/20"
                      }`}
                      title={sub.enabled ? "Active - Click to Disable" : "Inactive - Click to Enable"}
                    >
                      <Power className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteWebhook(sub.id)}
                      className="p-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20 flex items-center justify-center transition-all"
                      title="Delete webhook"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Health Warning */}
                {sub.consecutive_failures > 0 && (
                  <div className="flex items-center gap-2 p-2.5 rounded-xl bg-amber-500/5 border border-amber-500/10 text-[11px] text-amber-300">
                    <AlertCircle className="w-4 h-4 shrink-0 text-amber-400" />
                    <span>
                      Warning: Webhook failed {sub.consecutive_failures} consecutive times. Auto-disables at 10 failures.
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 bg-[#060810]/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#151B26] border border-[#222D3D] w-full max-w-lg rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
            
            {/* Modal Header */}
            <div className="p-6 border-b border-[#222D3D] flex items-center justify-between shrink-0">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <Webhook className="w-4.5 h-4.5 text-blue-400" />
                Configure New Webhook
              </h2>
              <button 
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white transition-colors text-xs font-semibold"
              >
                Close
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              
              {createdSecret ? (
                /* Secret display view */
                <div className="space-y-4">
                  <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-2xl text-emerald-300 text-xs flex items-start gap-2.5">
                    <Check className="w-5 h-5 text-emerald-400 shrink-0" />
                    <div className="space-y-1">
                      <p className="font-semibold text-white">Webhook Created Successfully</p>
                      <p>Copy the HMAC signing secret below. It will NOT be shown again for security.</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold font-mono">Signing Secret</label>
                    <div className="flex items-center gap-3 bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 pl-4 font-mono text-xs">
                      <span className="text-slate-200 truncate flex-1 leading-none">{createdSecret}</span>
                      <button
                        onClick={handleCopySecret}
                        className="p-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all shrink-0"
                        title="Copy secret"
                      >
                        {copiedSecret ? (
                          <Check className="w-4 h-4 text-emerald-400" />
                        ) : (
                          <Copy className="w-4 h-4" />
                        )}
                      </button>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      setCreatedSecret(null);
                      setShowCreateModal(false);
                      fetchWebhooks();
                    }}
                    className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition-all shadow-md"
                  >
                    Done & Close
                  </button>
                </div>
              ) : (
                /* Creation form */
                <form onSubmit={handleCreateWebhook} className="space-y-5">
                  <div className="space-y-2">
                    <label htmlFor="target-url-input" className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold font-mono">Target URL</label>
                    <input
                      id="target-url-input"
                      type="url"
                      required
                      placeholder="https://your-system.com/webhooks/invoice"
                      value={targetUrl}
                      onChange={(e) => setTargetUrl(e.target.value)}
                      className="w-full bg-[#0B0F19] border border-[#222D3D] rounded-xl px-4 py-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
                    />
                  </div>

                  {/* Subscriptions Selection */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold font-mono">Subscribed Events</span>
                      <span className="text-[10px] text-slate-500 font-mono">{selectedEvents.length} selected</span>
                    </div>
                    
                    <div className="space-y-2.5 max-h-56 overflow-y-auto pr-1">
                      {ALLOWED_EVENTS.map((evt) => {
                        const isChecked = selectedEvents.includes(evt.value);
                        return (
                          <div 
                            key={evt.value}
                            onClick={() => toggleEventSelection(evt.value)}
                            className={`p-3 rounded-xl border transition-all cursor-pointer flex items-start gap-3 ${
                              isChecked 
                                ? "bg-blue-500/5 border-blue-500/20 text-slate-200" 
                                : "bg-[#0B0F19] border-[#222D3D] text-slate-400 hover:border-slate-800"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              readOnly
                              className="mt-0.5 accent-blue-500"
                            />
                            <div className="space-y-0.5 leading-none">
                              <p className="text-xs font-semibold text-slate-200">{evt.label}</p>
                              <p className="text-[10px] text-slate-500 leading-normal">{evt.desc}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Form Actions */}
                  <div className="flex items-center gap-3 pt-3">
                    <button
                      type="button"
                      onClick={() => setShowCreateModal(false)}
                      className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-[#222D3D] text-xs font-semibold transition-all"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={submitting || !targetUrl}
                      className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition-all shadow-md active:scale-95 disabled:opacity-55 disabled:pointer-events-none"
                    >
                      {submitting ? "Registering..." : "Register Endpoint"}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
