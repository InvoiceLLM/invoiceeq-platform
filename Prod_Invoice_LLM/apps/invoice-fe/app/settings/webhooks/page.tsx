"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
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
  Pencil,
  RotateCw,
  History
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";

interface WebhookSub {
  id: string;
  target_url: string;
  subscribed_events: string[];
  enabled: boolean;
  consecutive_failures: number;
  // Gap 194: {event_type: consecutive failures}. Optional so a response from a
  // backend that predates the field doesn't break the row.
  event_failure_counts?: Record<string, number>;
  created_at: string;
  updated_at: string;
  secret?: string; // only present upon creation
}

/** Gap 194: one row of GET /api/webhooks/{id}/deliveries. */
interface WebhookDelivery {
  id: string;
  event_type: string;
  success: boolean;
  status_code: number | null;
  attempts: number;
  duration_ms: number | null;
  error: string | null;
  created_at: string;
}

const ALLOWED_EVENTS = [
  { value: "invoice.processing", label: "Inbound Processing", desc: "Fires when an inbound invoice enters the extraction pipeline." },
  { value: "invoice.completed", label: "Inbound Completed", desc: "Fires when an inbound invoice finishes extraction successfully." },
  { value: "invoice.audit_required", label: "Inbound Audit Required", desc: "Fires when an inbound invoice requires human audit." },
  { value: "invoice.duplicate", label: "Inbound Duplicate", desc: "Fires when an uploaded invoice matches a previously ingested file." },
  { value: "invoice.approved", label: "Inbound Approved", desc: "Fires when an inbound invoice is approved by auditor." },
  { value: "invoice.rejected", label: "Inbound Rejected", desc: "Fires when an inbound invoice is rejected by auditor." },
  { value: "outbound_invoice.sent", label: "Outbound Sent", desc: "Fires when an outbound invoice is dispatched to the recipient." },
  { value: "outbound_invoice.overdue", label: "Outbound Overdue", desc: "Fires when an outbound invoice crosses its payment due date." },
  { value: "outbound_invoice.approved", label: "Outbound Approved", desc: "Fires when an outbound invoice is marked as approved/paid." }
];

const GENERIC_ERRORS = {
  load: "Failed to load webhooks. Please try again.",
  create: "Failed to create webhook. Please try again.",
  update: "Failed to update webhook. Please try again.",
  toggle: "Failed to update the webhook's status. Please try again.",
  delete: "Failed to delete webhook. Please try again.",
  deliveries: "Failed to load delivery history. Please try again."
};

/**
 * Website Gap 13 (2026-08-05): never surface a raw response body to the user.
 * This screen used to do `throw new Error(await res.text())` and render the
 * result verbatim in the error banner -- so when `/api/webhooks` was answered
 * by something other than the intended API (a Next.js 404 HTML page, an
 * upstream proxy error page, a gateway timeout page), the *entire HTML source*
 * of that page rendered inside the app screen. Only a JSON error body is
 * trusted for a user-facing message; every other content type, a body that
 * doesn't parse, and any body without a usable string field all fall back to
 * the caller's generic message.
 */
const errorMessage = async (res: Response, fallback: string): Promise<string> => {
  try {
    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    if (!contentType.includes("application/json")) return fallback;
    const data = await res.json();
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
        ? data.error
        : typeof data?.message === "string"
        ? data.message
        : null;
    return detail && detail.trim() ? detail.trim() : fallback;
  } catch {
    return fallback;
  }
};

export default function WebhooksPage() {
  // FE Gap 110: declared above the loading/Access-Restricted early returns, so
  // the shared header still names the screen in both of those states.
  usePageHeader({
    title: "Developer Webhooks",
    subtitle: "Register endpoints to receive automated event payloads",
    backHref: "/settings",
  });

  const { role, loading } = useAuth();
  const isAdmin = role === "Admin";

  const [webhooks, setWebhooks] = useState<WebhookSub[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [showCreateModal, setShowCreateModal] = useState(false);
  // FE Gap 203: the same modal serves create and edit. `null` means create;
  // a webhook id means the form is editing that existing subscription and
  // submits PUT /webhooks/{id} instead of POST /webhooks.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [targetUrl, setTargetUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [copiedUrlId, setCopiedUrlId] = useState<string | null>(null);

  // FE Gap 194: delivery history, fetched lazily per subscription the first
  // time its panel is opened (the list endpoint returns subscriptions only, and
  // a tenant can have many endpoints -- no reason to fetch logs nobody asked
  // for). `expandedId` is the one open panel; keyed state so re-opening a panel
  // shows what was already loaded instead of flashing a spinner.
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<Record<string, WebhookDelivery[]>>({});
  const [loadingDeliveriesId, setLoadingDeliveriesId] = useState<string | null>(null);
  const [deliveriesError, setDeliveriesError] = useState<Record<string, string>>({});

  const fetchWebhooks = async () => {
    try {
      setFetching(true);
      setError(null);
      const res = await fetch("/api/webhooks");
      if (!res.ok) {
        throw new Error(await errorMessage(res, GENERIC_ERRORS.load));
      }
      // A 200 that isn't JSON is just as untrustworthy as a non-OK one here --
      // don't let a stray HTML body reach res.json()'s parser error message.
      const contentType = (res.headers.get("content-type") || "").toLowerCase();
      if (!contentType.includes("application/json")) {
        throw new Error(GENERIC_ERRORS.load);
      }
      const data = await res.json();
      setWebhooks(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(typeof err?.message === "string" && err.message ? err.message : GENERIC_ERRORS.load);
    } finally {
      setFetching(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchWebhooks();
    }
  }, [isAdmin]);

  // FE Gap 203: single entry point for both modal modes, so the form never
  // opens carrying the previous session's values.
  const openCreateModal = () => {
    setEditingId(null);
    setCreatedSecret(null);
    setTargetUrl("");
    setSelectedEvents([]);
    setShowCreateModal(true);
  };

  const openEditModal = (webhook: WebhookSub) => {
    setEditingId(webhook.id);
    // The secret is only ever returned once, at creation -- an edit can never
    // show it, so this view must always be the form, not the secret panel.
    setCreatedSecret(null);
    setTargetUrl(webhook.target_url);
    setSelectedEvents([...webhook.subscribed_events]);
    setShowCreateModal(true);
  };

  const closeModal = () => {
    setShowCreateModal(false);
    setEditingId(null);
    setTargetUrl("");
    setSelectedEvents([]);
  };

  const handleSubmitWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUrl) return;
    if (selectedEvents.length === 0) {
      alert("Please select at least one event type.");
      return;
    }

    const isEdit = editingId !== null;
    const genericError = isEdit ? GENERIC_ERRORS.update : GENERIC_ERRORS.create;

    try {
      setSubmitting(true);
      setError(null);
      const res = await fetch(isEdit ? `/api/webhooks/${editingId}` : "/api/webhooks", {
        method: isEdit ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_url: targetUrl,
          subscribed_events: selectedEvents
        })
      });

      if (!res.ok) {
        throw new Error(await errorMessage(res, genericError));
      }

      const saved = await res.json();

      if (isEdit) {
        // PUT returns the public dict (no secret) -- merge it over the row so
        // the list reflects the new URL/events without a refetch.
        setWebhooks(prev => prev.map(w => (w.id === editingId ? { ...w, ...saved } : w)));
        closeModal();
        return;
      }

      setWebhooks(prev => [...prev, saved]);
      setCreatedSecret(saved.secret);

      // Reset form
      setTargetUrl("");
      setSelectedEvents([]);
    } catch (err: any) {
      alert(typeof err?.message === "string" && err.message ? err.message : genericError);
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
        throw new Error(await errorMessage(res, GENERIC_ERRORS.toggle));
      }

      setWebhooks(prev => prev.map(w => w.id === webhook.id ? { ...w, enabled: !w.enabled } : w));
    } catch (err: any) {
      alert(typeof err?.message === "string" && err.message ? err.message : GENERIC_ERRORS.toggle);
    }
  };

  const handleDeleteWebhook = async (id: string) => {
    if (!confirm("Are you sure you want to delete this webhook subscription?")) return;

    try {
      const res = await fetch(`/api/webhooks/${id}`, {
        method: "DELETE"
      });

      if (!res.ok) {
        throw new Error(await errorMessage(res, GENERIC_ERRORS.delete));
      }

      setWebhooks(prev => prev.filter(w => w.id !== id));
      // FE Gap 194: drop the deleted endpoint's cached delivery history too,
      // so a newly created webhook can't inherit it if an id is ever reused.
      setDeliveries(prev => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setExpandedId(prev => (prev === id ? null : prev));
    } catch (err: any) {
      alert(typeof err?.message === "string" && err.message ? err.message : GENERIC_ERRORS.delete);
    }
  };

  // FE Gap 194: fetches on first open and on every explicit refresh, so the
  // panel can be re-checked after a fix without reloading the page.
  const loadDeliveries = async (id: string) => {
    try {
      setLoadingDeliveriesId(id);
      setDeliveriesError(prev => ({ ...prev, [id]: "" }));
      const res = await fetch(`/api/webhooks/${id}/deliveries?limit=25`);
      if (!res.ok) {
        throw new Error(await errorMessage(res, GENERIC_ERRORS.deliveries));
      }
      const contentType = (res.headers.get("content-type") || "").toLowerCase();
      if (!contentType.includes("application/json")) {
        throw new Error(GENERIC_ERRORS.deliveries);
      }
      const data = await res.json();
      setDeliveries(prev => ({ ...prev, [id]: Array.isArray(data) ? data : [] }));
    } catch (err: any) {
      setDeliveriesError(prev => ({
        ...prev,
        [id]: typeof err?.message === "string" && err.message ? err.message : GENERIC_ERRORS.deliveries
      }));
    } finally {
      setLoadingDeliveriesId(null);
    }
  };

  const handleToggleDeliveries = (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!deliveries[id]) {
      loadDeliveries(id);
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
      {/* FE Gap 110: own h-16 header bar replaced by the shared one; "Add
          Endpoint" portals up into it so it keeps sitting beside the title. */}
      <PageHeaderActions>
        <button
          onClick={openCreateModal}
          className="h-9 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-2 transition-all shadow-md active:scale-95 shrink-0"
        >
          <Plus className="w-4 h-4" />
          Add Endpoint
        </button>
      </PageHeaderActions>

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
              onClick={openCreateModal}
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
                    {/* FE Gap 194: delivery history for this endpoint. */}
                    <button
                      onClick={() => handleToggleDeliveries(sub.id)}
                      className={`p-2 rounded-xl border flex items-center justify-center transition-all ${
                        expandedId === sub.id
                          ? "bg-blue-500/10 border-blue-500/20 text-blue-400"
                          : "bg-slate-500/10 border-slate-500/20 text-slate-400 hover:bg-slate-500/20 hover:text-white"
                      }`}
                      title="Recent deliveries"
                      aria-label="Recent deliveries"
                      aria-expanded={expandedId === sub.id}
                    >
                      <History className="w-4 h-4" />
                    </button>
                    {/* FE Gap 203: edit affordance -- opens the same modal
                        prefilled, submitting PUT /webhooks/{id}. */}
                    <button
                      onClick={() => openEditModal(sub)}
                      className="p-2 rounded-xl bg-slate-500/10 border border-slate-500/20 text-slate-400 hover:bg-slate-500/20 hover:text-white flex items-center justify-center transition-all"
                      title="Edit webhook"
                      aria-label="Edit webhook"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
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

                {/* Health Warning. FE Gap 194: failures are now counted per
                    event type on the backend, and the endpoint is only
                    auto-disabled once no event type is still delivering — so
                    name the failing events instead of implying the whole
                    endpoint is 10 failures from being switched off. */}
                {sub.consecutive_failures > 0 && (
                  <div className="flex items-start gap-2 p-2.5 rounded-xl bg-amber-500/5 border border-amber-500/10 text-[11px] text-amber-300">
                    <AlertCircle className="w-4 h-4 shrink-0 text-amber-400 mt-0.5" />
                    <div className="space-y-1">
                      <p>
                        Warning: {sub.consecutive_failures} consecutive delivery failure
                        {sub.consecutive_failures === 1 ? "" : "s"}. An endpoint is auto-disabled once an
                        event type reaches 10 failures and no other event type is still being delivered.
                      </p>
                      {(() => {
                        const failing = Object.entries(sub.event_failure_counts || {}).filter(
                          ([, count]) => count > 0
                        );
                        if (failing.length === 0) return null;
                        return (
                          <p className="font-mono text-[10px] text-amber-200/80">
                            {failing.map(([evt, count]) => `${evt}: ${count}`).join(" · ")}
                          </p>
                        );
                      })()}
                    </div>
                  </div>
                )}

                {/* FE Gap 194: delivery history. Before this existed, delivery
                    errors were swallowed by design (a dead subscriber must
                    never fail the invoice operation that fired the event), so
                    a totally broken fan-out looked identical to a clean one. */}
                {expandedId === sub.id && (
                  <div className="rounded-xl bg-[#0B0F19] border border-[#222D3D] p-3 space-y-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold font-mono">
                        Recent Deliveries
                      </span>
                      <button
                        onClick={() => loadDeliveries(sub.id)}
                        disabled={loadingDeliveriesId === sub.id}
                        className="text-[10px] text-slate-400 hover:text-white font-semibold inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
                      >
                        <RotateCw className={`w-3 h-3 ${loadingDeliveriesId === sub.id ? "animate-spin" : ""}`} />
                        Refresh
                      </button>
                    </div>

                    {deliveriesError[sub.id] ? (
                      <p className="text-[11px] text-red-300">{deliveriesError[sub.id]}</p>
                    ) : loadingDeliveriesId === sub.id && !deliveries[sub.id] ? (
                      <p className="text-[11px] text-slate-500">Loading delivery history...</p>
                    ) : (deliveries[sub.id] || []).length === 0 ? (
                      <p className="text-[11px] text-slate-500">
                        No delivery attempts recorded yet for this endpoint.
                      </p>
                    ) : (
                      <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                        {(deliveries[sub.id] || []).map((d) => (
                          <div
                            key={d.id}
                            className="flex items-start justify-between gap-3 rounded-lg bg-[#151B26] border border-[#222D3D] px-2.5 py-2"
                          >
                            <div className="min-w-0 space-y-0.5">
                              <p className="font-mono text-[10px] text-slate-300 truncate">{d.event_type}</p>
                              <p className="text-[10px] text-slate-500">
                                {new Date(d.created_at).toLocaleString()}
                                {d.attempts > 0 && ` · ${d.attempts} attempt${d.attempts === 1 ? "" : "s"}`}
                                {d.duration_ms !== null && ` · ${d.duration_ms}ms`}
                              </p>
                              {!d.success && d.error && (
                                <p className="text-[10px] text-red-300/80 break-all">{d.error}</p>
                              )}
                            </div>
                            <span
                              className={`shrink-0 px-2 py-0.5 rounded-md text-[10px] font-mono font-semibold border ${
                                d.success
                                  ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                                  : "bg-red-500/10 border-red-500/20 text-red-400"
                              }`}
                            >
                              {d.status_code !== null ? d.status_code : d.success ? "OK" : "FAILED"}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
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
                {editingId ? "Edit Webhook" : "Configure New Webhook"}
              </h2>
              <button
                onClick={closeModal}
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
                      closeModal();
                      setCreatedSecret(null);
                      fetchWebhooks();
                    }}
                    className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition-all shadow-md"
                  >
                    Done & Close
                  </button>
                </div>
              ) : (
                /* Create / edit form */
                <form onSubmit={handleSubmitWebhook} className="space-y-5">
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
                      onClick={closeModal}
                      className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-[#222D3D] text-xs font-semibold transition-all"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={submitting || !targetUrl}
                      className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition-all shadow-md active:scale-95 disabled:opacity-55 disabled:pointer-events-none"
                    >
                      {editingId
                        ? submitting
                          ? "Saving..."
                          : "Save Changes"
                        : submitting
                        ? "Registering..."
                        : "Register Endpoint"}
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
