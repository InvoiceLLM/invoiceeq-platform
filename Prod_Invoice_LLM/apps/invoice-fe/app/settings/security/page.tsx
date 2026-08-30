"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ShieldCheck, Key, Lock, CheckCircle2, Copy, Check, RefreshCw, FileText, AlertTriangle, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import WidgetTokenSection from "@/components/settings/WidgetTokenSection";

/**
 * Gap 184: metadata about the tenant's live API key, as returned by
 * GET /api/settings/security/api-key. There is deliberately no field here that
 * could carry the key itself — the raw value is returned by exactly one
 * response in the whole app (the rotate call) and is unrecoverable afterwards.
 */
interface ApiKeyStatus {
  has_key: boolean;
  key_prefix: string | null;
  masked_key: string | null;
  rotated_at: string | null;
  last_used_at: string | null;
  can_rotate: boolean;
}

interface ApiKeyRotateResponse extends ApiKeyStatus {
  api_key: string;
}

const API_KEY_URL = "/api/settings/security/api-key";
const API_KEY_ROTATE_URL = "/api/settings/security/api-key/rotate";

/**
 * FE Gap 324: what the "Active Role" tile shows when there is no role to show.
 *
 * Two different states land here and both mean the same thing to a user:
 *   - `useAuth().role === ""` — identity is still loading, or the /auth/me
 *     lookup failed (see hooks/useAuth.ts's ANONYMOUS).
 *   - the backend literally returns "Restricted" — BE Gap 337's
 *     `RoleMapper.NO_ROLE`, the zero-permission fallback for an unmapped IDP
 *     role string, an org-mismatch clamp, or a first-login clamp.
 *
 * "Restricted" is deliberately never shown verbatim. It is an accurate internal
 * name and a punitive-sounding label for someone whose only problem is that
 * nobody has assigned them a role yet — and it is explicitly excluded from
 * `RoleMapper.USER_FACING_ROLES` on the backend for that reason.
 */
const UNASSIGNED_ROLE_LABEL = "Unassigned";
const BACKEND_NO_ROLE = "Restricted";

function formatTimestamp(value: string | null): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown";
  return parsed.toLocaleString();
}

export default function SecuritySettingsPage() {
  usePageHeader({
    title: "Security & Access Control",
    subtitle: "Manage API credentials, tenant isolation parameters, and security policies",
    backHref: "/settings",
  });

  const { role, loading: authLoading } = useAuth();
  const [activeTab, setActiveTab] = useState<"access" | "docs">("access");

  // Gap 184: all of this used to be a hardcoded `inv_live_9f8a...` string that
  // the "Rotate" button replaced with a Math.random() value in local state —
  // nothing ever reached the backend, and the key shown authenticated nothing.
  const [keyStatus, setKeyStatus] = useState<ApiKeyStatus | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  // The raw key, held only for as long as this page stays mounted after a
  // rotation. It is never written to storage — the backend cannot re-issue it,
  // so this is genuinely the user's one chance to copy it.
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);
  const [isRotating, setIsRotating] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);

  // `can_rotate` comes from the backend (which is the thing that enforces it);
  // the local role is only a fallback for rendering before the first response.
  const canRotate = keyStatus?.can_rotate ?? role === "Admin";

  const loadStatus = useCallback(async () => {
    setIsLoadingStatus(true);
    setStatusError(null);
    try {
      const response = await fetch(API_KEY_URL, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Request failed (HTTP ${response.status})`);
      }
      setKeyStatus((await response.json()) as ApiKeyStatus);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : "Could not load API key status.");
    } finally {
      setIsLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const handleCopyKey = () => {
    if (typeof window === "undefined" || !revealedKey) return;
    navigator.clipboard.writeText(revealedKey);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  };

  const handleRotateKey = async () => {
    if (!canRotate || isRotating) return;
    setIsRotating(true);
    setRotateError(null);
    try {
      const response = await fetch(API_KEY_ROTATE_URL, { method: "POST" });
      if (!response.ok) {
        // The backend's own message is the useful one here (403 for a
        // non-Admin, 402 for a lapsed plan), so surface it rather than a
        // generic string.
        let detail = `Rotation failed (HTTP ${response.status})`;
        try {
          const body = await response.json();
          if (body?.detail) detail = String(body.detail);
        } catch {
          /* non-JSON error body — keep the status-code message */
        }
        throw new Error(detail);
      }
      const data = (await response.json()) as ApiKeyRotateResponse;
      setRevealedKey(data.api_key);
      const { api_key: _rawKey, ...status } = data;
      setKeyStatus(status);
    } catch (err) {
      setRotateError(err instanceof Error ? err.message : "Rotation failed.");
    } finally {
      setIsRotating(false);
    }
  };

  /**
   * FE Gap 324: the three roles a user is actually assigned, with the real
   * default permissions from the backend's `RoleMapper.ROLE_PERMISSION_DEFAULTS`
   * (invoice-be/models.py). This table previously disagreed with the backend in
   * three places at once: it listed "Loader" (not a role — `can_load` is a
   * per-user permission an Admin grants from the Admin Console), it listed the
   * now-retired "Viewer" (BE Gap 337), it gave Auditor `train: true` (Auditor is
   * `can_train=False`), and it omitted Trainer entirely.
   *
   * `NO_ROLE` / "Restricted" is deliberately absent: it is an internal fallback,
   * never assignable, and listing it would imply an Admin could pick it.
   */
  const roleMatrix = [
    { role: "Admin", load: true, audit: true, train: true, settings: true, desc: "Full administrative access, user management, and API key rotation" },
    { role: "Auditor", load: false, audit: true, train: false, settings: false, desc: "Review, correct, approve and reject invoices in the Auditor Console" },
    { role: "Trainer", load: false, audit: false, train: true, settings: false, desc: "Author and commit extraction rules in the AI Trainer" },
  ];

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      <main className="flex-1 px-6 py-8 max-w-4xl w-full mx-auto space-y-6">

        {/* Gap 184: API Access / API Docs tabs */}
        <div role="tablist" aria-label="Security settings sections" className="flex items-center gap-2 border-b border-[#222D3D]">
          <button
            role="tab"
            id="tab-access"
            aria-selected={activeTab === "access"}
            aria-controls="panel-access"
            onClick={() => setActiveTab("access")}
            className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 -mb-px transition-all ${
              activeTab === "access"
                ? "border-emerald-400 text-white"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Key className="w-3.5 h-3.5" /> API Access
          </button>
          <button
            role="tab"
            id="tab-docs"
            aria-selected={activeTab === "docs"}
            aria-controls="panel-docs"
            onClick={() => setActiveTab("docs")}
            className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 -mb-px transition-all ${
              activeTab === "docs"
                ? "border-emerald-400 text-white"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileText className="w-3.5 h-3.5" /> API Docs
          </button>
        </div>

        {activeTab === "docs" ? (
          /* Docs Hub — the backend's own FastAPI Swagger UI, proxied same-origin
             by /api/docs/ui so it renders inside the app and shows the REST
             routes and outbound webhook payload schemas in one place. */
          <section
            role="tabpanel"
            id="panel-docs"
            aria-labelledby="tab-docs"
            className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
                <FileText className="w-5 h-5" />
              </div>
              <div className="flex-1">
                <h2 className="font-semibold text-sm text-white">API &amp; Webhook Reference</h2>
                <p className="text-xs text-slate-400">
                  Live OpenAPI schema for every programmatic REST endpoint and outbound webhook payload
                </p>
              </div>
              <a
                href="/api/docs/openapi"
                target="_blank"
                rel="noreferrer"
                className="px-3 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 hover:text-white border border-[#222D3D] text-xs font-semibold transition-all shrink-0"
              >
                Raw schema
              </a>
            </div>

            <iframe
              src="/api/docs/ui"
              title="API documentation"
              className="w-full h-[70vh] rounded-xl bg-white border border-[#222D3D]"
            />
          </section>
        ) : (
        <>
        {/* API Credentials */}
        <section role="tabpanel" id="panel-access" aria-labelledby="tab-access" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <Key className="w-5 h-5" />
            </div>
            <div>
              <h2 id="api-keys-heading" className="font-semibold text-sm text-white">API Authentication Key</h2>
              <p className="text-xs text-slate-400">
                Send this key as <span className="font-mono">X-API-Key</span> or{" "}
                <span className="font-mono">Authorization: Bearer</span> to authenticate programmatic REST API requests
              </p>
            </div>
          </div>

          {/* The raw key, shown once. The backend stores only a salted hash and
              cannot re-issue this value, so the warning is literal, not advisory. */}
          {revealedKey && (
            <div className="bg-emerald-500/5 border border-emerald-500/30 rounded-xl p-3.5 space-y-2">
              <p className="text-[11px] text-emerald-300 font-semibold flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                Copy this key now — it is shown once and cannot be retrieved again.
              </p>
              <div className="flex items-center gap-3">
                <span data-testid="revealed-api-key" className="font-mono text-xs text-slate-100 truncate flex-1">{revealedKey}</span>
                <button
                  onClick={handleCopyKey}
                  className="p-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all flex items-center justify-center shrink-0"
                  title="Copy Key"
                >
                  {copiedKey ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 pl-4">
            <span data-testid="api-key-display" className="font-mono text-xs text-slate-200 truncate flex-1">
              {isLoadingStatus ? (
                <span className="text-slate-500 flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading key status…
                </span>
              ) : statusError ? (
                <span className="text-rose-300">{statusError}</span>
              ) : keyStatus?.has_key ? (
                keyStatus.masked_key
              ) : (
                <span className="text-slate-500">
                  No API key issued yet{canRotate ? " — generate one to start using the REST API." : "."}
                </span>
              )}
            </span>
            {canRotate && (
              <button
                onClick={handleRotateKey}
                disabled={isRotating || isLoadingStatus}
                className="px-3 py-2 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-semibold flex items-center gap-1.5 transition-all disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isRotating ? "animate-spin" : ""}`} />
                {keyStatus?.has_key ? "Rotate Key" : "Generate Key"}
              </button>
            )}
          </div>

          {rotateError && (
            <p className="text-xs text-rose-300 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" /> {rotateError}
            </p>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Last Rotated</span>
              <p className="text-xs font-semibold text-white">{formatTimestamp(keyStatus?.rotated_at ?? null)}</p>
            </div>
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Last Used</span>
              <p className="text-xs font-semibold text-white">{formatTimestamp(keyStatus?.last_used_at ?? null)}</p>
            </div>
          </div>

          {keyStatus?.has_key && canRotate && (
            <p className="text-[11px] text-slate-500">
              Rotating immediately invalidates the previous key — any integration still using it will start receiving 401 responses.
            </p>
          )}
        </section>

        {/* FE Gap 325 — chat widget tokens (BE Feature 25 / Gap 341).
            Sits directly under the API key because both are programmatic
            credentials, but it is deliberately a separate card: a widget token
            is a different credential in a different table with a different
            trust level (published in a customer's page source, chat-only, no
            role and no permissions), and rendering it as another row of the
            API-key panel would imply they are variants of one thing.
            Sandbox keys (BE Gap 340) are NOT here — that credential belongs to
            an anonymous website visitor, not to a signed-in Settings screen. */}
        <WidgetTokenSection isAdmin={role === "Admin"} authLoading={authLoading} />

        {/* Tenant Isolation Status */}
        <section aria-labelledby="tenant-security-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Lock className="w-5 h-5" />
            </div>
            <div>
              <h2 id="tenant-security-heading" className="font-semibold text-sm text-white">Tenant Isolation & Data Encryption</h2>
              <p className="text-xs text-slate-400">Row-level security enforcement and data isolation posture</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Isolation Mode</span>
              <p className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" /> Multi-Tenant Row Security
              </p>
            </div>
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Encryption at Rest</span>
              <p className="text-xs font-semibold text-white">AES-256 GCM</p>
            </div>
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Active Role</span>
              {/* `loading` is checked separately from `!role` deliberately.
                  Found in a live run: while identity is in flight `role` is ""
                  and this tile told an Admin they had no role assigned, for as
                  long as /auth/me took. "Still loading" and "genuinely has no
                  role" are different answers and must not share a label. */}
              <p className="text-xs font-semibold text-blue-400">
                {authLoading
                  ? "…"
                  : !role || role === BACKEND_NO_ROLE
                  ? UNASSIGNED_ROLE_LABEL
                  : role}
              </p>
              {!authLoading && (!role || role === BACKEND_NO_ROLE) && (
                <p className="text-[10px] text-slate-500 leading-tight">
                  No role assigned yet — an Admin can assign one from the Admin Console.
                </p>
              )}
            </div>
          </div>
        </section>

        {/* Role Access Matrix */}
        <section aria-labelledby="role-matrix-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 id="role-matrix-heading" className="font-semibold text-sm text-white">Role-Based Access Control (RBAC) Matrix</h2>
              <p className="text-xs text-slate-400">Configured permissions for each role level</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-[#222D3D] text-slate-400 font-mono text-[10px] uppercase">
                  <th className="py-2.5 px-3">Role</th>
                  <th className="py-2.5 px-3 text-center">Ingest</th>
                  <th className="py-2.5 px-3 text-center">Audit</th>
                  <th className="py-2.5 px-3 text-center">Trainer</th>
                  <th className="py-2.5 px-3 text-center">Settings</th>
                  <th className="py-2.5 px-3">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222D3D]/50 text-slate-300">
                {roleMatrix.map((item) => (
                  <tr key={item.role} className="hover:bg-slate-900/30">
                    <td className="py-3 px-3 font-semibold text-white font-mono">{item.role}</td>
                    <td className="py-3 px-3 text-center">{item.load ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-center">{item.audit ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-center">{item.train ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-center">{item.settings ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-slate-400 text-[11px]">{item.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* FE Gap 324: the table shows role *defaults*. It cannot show that an
              Admin may grant Ingest / Audit / Trainer to an individual user from
              the Admin Console, which is what `can_load`/`can_audit`/`can_train`
              on the user row actually are -- so say it here rather than let the
              table read as the whole truth. */}
          <p className="text-[11px] text-slate-500 leading-relaxed">
            These are the default permissions for each role. An Admin can additionally grant
            Ingest, Audit or Trainer access to an individual member from the Admin Console, so a
            given user&apos;s effective access can be wider than their role&apos;s row. A member with no
            role assigned yet can still reach the Dashboard, Chat and Help.
          </p>
        </section>
        </>
        )}
      </main>
    </div>
  );
}
