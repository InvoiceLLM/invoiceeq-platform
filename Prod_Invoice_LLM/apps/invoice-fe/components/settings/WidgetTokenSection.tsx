"use client";

/**
 * Feature 17 (FE Gap 325): embedded chat widget tokens — Settings → Security.
 *
 * Backed by BE Feature 25 / Gap 341's three Admin-only endpoints in
 * invoice-be/routers/settings.py:
 *   GET    /api/v1/settings/security/widget-tokens
 *   POST   /api/v1/settings/security/widget-tokens          (shown once)
 *   DELETE /api/v1/settings/security/widget-tokens/{id}     (204)
 *
 * Five properties of that backend shape drive everything below, and each was
 * read out of the real code rather than assumed:
 *
 *  1. **A widget token is not the tenant API key.** It lives in its own
 *     `WidgetToken` table, not in `Tenant.api_key_hash/salt/prefix`, so a tenant
 *     may hold several at once (one per embedded site) and revoking one leaves
 *     the others working. Hence a list, not the single rotate-in-place control
 *     the API key section above uses.
 *  2. **Shown once.** The POST response is the only place the raw value ever
 *     exists outside the issuing request; the backend stores a PBKDF2 digest and
 *     cannot re-issue it. Same contract as `rotate_api_key()`, and the warning
 *     is literal rather than advisory.
 *  3. **There is no update endpoint.** `allowed_origins` is written by
 *     `issue_widget_token()` and never edited afterwards — no PATCH/PUT exists.
 *     "Changing" the domains therefore means issuing a new token and revoking
 *     the old one, and this UI says exactly that instead of rendering an edit
 *     control that would have nothing to call.
 *  4. **Origin pinning is one defensive layer, not a boundary.**
 *     `services/widget_tokens.py`'s module docstring is explicit that
 *     `curl -H 'Origin: https://acme.com'` is the entire bypass, and forbids
 *     describing it as a guarantee "in code, in docs, or to a customer". The
 *     copy below is written to that constraint.
 *  5. **There is no embeddable JavaScript bundle.** `routers/widget.py` serves
 *     one JSON endpoint and nothing else — no `<script>` to paste, no rendered
 *     chat bubble, nothing static (verified by grep across both apps: no
 *     widget.js, no loader, no StaticFiles mount). So the "embed" panel is a
 *     real HTTP call the tenant wires into their own UI, and says so.
 *
 * Sandbox keys (BE Gap 340) are deliberately NOT here. That credential is issued
 * to an anonymous website visitor with no login; a logged-in Settings screen is
 * the wrong surface for it and it belongs to invoice-website's own flow.
 */

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AppWindow,
  AlertTriangle,
  Check,
  Copy,
  Globe,
  Loader2,
  Plus,
  Trash2,
  X,
} from "lucide-react";

const WIDGET_TOKENS_URL = "/api/settings/security/widget-tokens";

/**
 * `WidgetTokenSummary` in invoice-be/routers/settings.py. Note what is absent:
 * there is deliberately no field on this model that could carry the token
 * itself — only `WidgetTokenCreateResponse` has one.
 */
interface WidgetTokenSummary {
  id: string;
  label: string;
  token_prefix: string;
  masked_token: string | null;
  allowed_origins: string[];
  created_at: string | null;
  last_used_at: string | null;
}

interface WidgetTokenCreateResponse extends WidgetTokenSummary {
  widget_token: string;
}

/**
 * Same rule as app/settings/workflows/page.tsx's copy of this helper (and
 * Website Gap 13's original): only a JSON error body is trusted for a
 * user-facing message, so an HTML error page from a proxy can never be rendered
 * verbatim inside the app. Worth surfacing here rather than writing generic
 * strings — the backend's own text names the per-tenant token cap (409) and
 * tells an Admin exactly what form an origin has to take (422).
 *
 * Duplicated rather than shared because the two callers are page/component
 * modules, not a lib; the API-key section on this page inlines the same logic
 * again. Extracting all three is a refactor, not this gap's scope.
 */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    if (!contentType.includes("application/json")) return fallback;
    const data = await res.json();
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.message === "string"
        ? data.message
        : null;
    return detail && detail.trim() ? detail.trim() : fallback;
  } catch {
    return fallback;
  }
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown";
  return parsed.toLocaleString();
}

/**
 * Split whatever an Admin typed into the domains box into a list. Commas and
 * newlines both, because both are what people actually paste.
 *
 * No validation happens here on purpose. `normalize_origin()` on the backend is
 * the thing that decides what a usable origin is (it accepts a bare host, an
 * `https://host:port`, or a full URL whose path it discards, and rejects
 * anything else with a 422 naming the required form). Re-implementing that rule
 * in TypeScript would give two answers to one question and the client's would
 * be the wrong one the first time the backend's changed.
 */
function parseOrigins(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

/**
 * The embed snippet. Deliberately a raw `fetch`, not a `<script src=...>` tag:
 * no such script exists (see the module comment). Targets the backend directly
 * because a widget runs on the tenant's own domain and cannot use this app's
 * `/api/...` proxy routes — those authenticate with the Clerk session cookie of
 * a logged-in user of *this* app. `routers/widget.py::WidgetCORSMiddleware` is
 * what makes the cross-origin call from their site work.
 */
function embedSnippet(): string {
  return [
    "// One question, one answer. There is no packaged widget script yet —",
    "// this is the real call, for you to wire into your own chat UI.",
    'const res = await fetch("https://<your-domain>/api/v1/widget/chat/message", {',
    '  method: "POST",',
    "  headers: {",
    '    "Content-Type": "application/json",',
    '    "X-API-Key": "YOUR_WIDGET_TOKEN",',
    "  },",
    "  body: JSON.stringify({",
    '    content: "What was our total spend last month?",',
    "    // Omit on the first message. Echo back the session_id from the",
    "    // response on follow-ups so the conversation keeps its context.",
    "    session_id: null,",
    "  }),",
    "});",
    "",
    "const { session_id, message_id, content } = await res.json();",
  ].join("\n");
}

export default function WidgetTokenSection({
  isAdmin,
  /**
   * `useAuth()`'s own loading flag, passed in rather than derived from
   * `isAdmin`. FE Gap 324 fixed exactly this failure mode one card down on this
   * page: while `/auth/me` is in flight `role` is `""`, so an Admin briefly
   * looks like a non-Admin. Telling them "only Administrators can manage these"
   * for the duration of a network round trip is wrong, so "still loading" and
   * "genuinely not an Admin" are kept as separate states here too.
   */
  authLoading = false,
}: {
  isAdmin: boolean;
  authLoading?: boolean;
}) {
  const [tokens, setTokens] = useState<WidgetTokenSummary[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // The raw token, held only for as long as this component stays mounted after
  // an issue. Never written to storage: the backend cannot re-issue it, so this
  // really is the Admin's one chance to copy it.
  const [revealedToken, setRevealedToken] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState("");
  const [originsInput, setOriginsInput] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const loadTokens = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const res = await fetch(WIDGET_TOKENS_URL, { cache: "no-store" });
      if (!res.ok) {
        throw new Error(
          await errorMessage(res, `Could not load widget tokens (HTTP ${res.status}).`)
        );
      }
      setTokens((await res.json()) as WidgetTokenSummary[]);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load widget tokens.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // All three endpoints are Admin-only, the GET included. Firing it for
    // anyone else is a guaranteed 403 on every page load, so don't — the same
    // reason app/settings/workflows/page.tsx checks the role before fetching.
    if (authLoading) return;
    if (!isAdmin) {
      setIsLoading(false);
      return;
    }
    void loadTokens();
  }, [authLoading, isAdmin, loadTokens]);

  const copy = (value: string, mark: (v: boolean) => void) => {
    if (typeof window === "undefined") return;
    navigator.clipboard.writeText(value);
    mark(true);
    setTimeout(() => mark(false), 2000);
  };

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isCreating) return;
    setIsCreating(true);
    setCreateError(null);
    // Clear any previously revealed token before issuing another: two raw
    // values on screen at once, only one of which is the new one, is exactly
    // the kind of thing that gets the wrong one pasted into a live site.
    setRevealedToken(null);
    try {
      const res = await fetch(WIDGET_TOKENS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: label.trim() || "Chat widget",
          allowed_origins: parseOrigins(originsInput),
        }),
      });
      if (!res.ok) {
        // The backend's own message is the useful one: 409 names the
        // per-workspace token cap, 422 names the exact origin form it wants,
        // 403 explains the Admin gate. Do NOT clear the form on failure — the
        // Admin's typed domains must survive a rejected request.
        throw new Error(
          await errorMessage(res, `Could not issue a widget token (HTTP ${res.status}).`)
        );
      }
      const data = (await res.json()) as WidgetTokenCreateResponse;
      const { widget_token: raw, ...summary } = data;
      setRevealedToken(raw);
      setTokens((prev) => [summary, ...(prev ?? [])]);
      setLabel("");
      setOriginsInput("");
      setShowForm(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Could not issue a widget token.");
    } finally {
      setIsCreating(false);
    }
  };

  const handleRevoke = async (tokenId: string) => {
    if (revokingId) return;
    setRevokingId(tokenId);
    setRevokeError(null);
    try {
      const res = await fetch(`${WIDGET_TOKENS_URL}/${tokenId}`, { method: "DELETE" });
      // 204 is the success case and carries no body — see the proxy route's
      // note on FE Gap 177.
      if (!res.ok) {
        throw new Error(
          await errorMessage(res, `Could not revoke this token (HTTP ${res.status}).`)
        );
      }
      setTokens((prev) => (prev ?? []).filter((t) => t.id !== tokenId));
      setConfirmRevokeId(null);
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : "Could not revoke this token.");
    } finally {
      setRevokingId(null);
    }
  };

  const hasTokens = Boolean(tokens && tokens.length > 0);

  return (
    <section
      aria-labelledby="widget-tokens-heading"
      className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg"
    >
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
          <AppWindow className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 id="widget-tokens-heading" className="font-semibold text-sm text-white">
            Chat Widget Tokens
          </h2>
          <p className="text-xs text-slate-400">
            Chat-only credentials for embedding the assistant on your own website, where your
            visitors can use it without signing in here
          </p>
        </div>
        {!authLoading && isAdmin && !showForm && (
          <button
            onClick={() => {
              setShowForm(true);
              setCreateError(null);
            }}
            data-testid="widget-token-new"
            className="px-3 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 hover:text-white border border-[#222D3D] text-xs font-semibold flex items-center gap-1.5 transition-all shrink-0"
          >
            <Plus className="w-3.5 h-3.5" /> New token
          </button>
        )}
      </div>

      {/* What this credential can actually reach. It is meant to be published in
          a customer's page source, so the honest version of "it is weaker than
          an API key" has to include the part that is still sensitive: chat
          answers are built from this workspace's real invoice data. */}
      <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1.5">
        <p className="text-[11px] text-slate-400 leading-relaxed">
          A widget token reaches <strong className="text-slate-300">one endpoint</strong> — send a
          chat message — and nothing else. It cannot upload, read, approve, export or change
          anything, and it is not an API key: it carries no role and no permissions.
        </p>
        <p className="text-[11px] text-amber-300/80 leading-relaxed">
          It is designed to be published in your site&apos;s client-side code, so treat it as
          public. Anyone who reads it can ask the assistant questions, and the answers come from
          this workspace&apos;s real invoice data. Only embed it where you are comfortable with
          that.
        </p>
      </div>

      {authLoading ? (
        <p className="text-xs text-slate-500 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking your access…
        </p>
      ) : !isAdmin ? (
        <p className="text-[11px] text-slate-500">
          Only organisation Administrators can view or manage chat widget tokens.
        </p>
      ) : (
        <>
          {/* The raw token, shown once. The backend stores only a salted digest
              and cannot re-issue this value, so the warning is literal. */}
          {revealedToken && (
            <div className="bg-emerald-500/5 border border-emerald-500/30 rounded-xl p-3.5 space-y-2">
              <p className="text-[11px] text-emerald-300 font-semibold flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                Copy this token now — it is shown once and cannot be retrieved again.
              </p>
              <div className="flex items-center gap-3">
                <span
                  data-testid="revealed-widget-token"
                  className="font-mono text-xs text-slate-100 truncate flex-1"
                >
                  {revealedToken}
                </span>
                <button
                  onClick={() => copy(revealedToken, setCopiedToken)}
                  className="p-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all flex items-center justify-center shrink-0"
                  title="Copy token"
                >
                  {copiedToken ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
                <button
                  onClick={() => setRevealedToken(null)}
                  data-testid="widget-token-dismiss-reveal"
                  className="p-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all flex items-center justify-center shrink-0"
                  title="I have copied it — hide"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-[11px] text-slate-400">
                If you lose it, issue another token and revoke this one. That is cheap here — a
                workspace can hold several, and revoking one does not affect the others.
              </p>
            </div>
          )}

          {/* Issue form */}
          {showForm && (
            <form
              onSubmit={handleCreate}
              data-testid="widget-token-form"
              className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-3"
            >
              <div className="space-y-1">
                <label
                  htmlFor="widget-token-label"
                  className="text-[10px] uppercase font-mono text-slate-500 tracking-wider"
                >
                  Label
                </label>
                <input
                  id="widget-token-label"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Chat widget"
                  className="w-full px-3 py-2 rounded-lg bg-[#151B26] border border-[#222D3D] text-xs text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-sky-500/50"
                />
                <p className="text-[11px] text-slate-500">
                  Only for telling your own tokens apart — e.g. &ldquo;Marketing site&rdquo;.
                </p>
              </div>

              <div className="space-y-1">
                <label
                  htmlFor="widget-token-origins"
                  className="text-[10px] uppercase font-mono text-slate-500 tracking-wider flex items-center gap-1.5"
                >
                  <Globe className="w-3 h-3" /> Allowed website domains (optional)
                </label>
                <textarea
                  id="widget-token-origins"
                  value={originsInput}
                  onChange={(e) => setOriginsInput(e.target.value)}
                  rows={2}
                  placeholder="https://acme.com, https://docs.acme.com"
                  className="w-full px-3 py-2 rounded-lg bg-[#151B26] border border-[#222D3D] text-xs font-mono text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-sky-500/50"
                />
                {/* services/widget_tokens.py's module docstring forbids
                    describing this as a guarantee, in code, in docs, or to a
                    customer. This copy is written to that constraint: what it
                    stops, what it does not, and what leaving it empty means. */}
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  One per line or comma-separated. Scheme and host only — a path is ignored.
                </p>
                <p className="text-[11px] text-amber-300/80 leading-relaxed">
                  This is one defensive layer, not a lock. Browsers set the{" "}
                  <span className="font-mono">Origin</span> header and page scripts cannot change
                  it, so it does stop a copied token being reused from a different{" "}
                  <em>website</em>. It stops nothing outside a browser — anything that can send an
                  HTTP request can set that header by hand. Leave this empty and the check is not
                  applied at all.
                </p>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Domains are fixed when the token is issued and cannot be edited afterwards. To
                  change them, issue a new token with the new list and revoke the old one.
                </p>
              </div>

              {createError && (
                <p className="text-xs text-rose-300 flex items-start gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {createError}
                </p>
              )}

              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  disabled={isCreating}
                  data-testid="widget-token-generate"
                  className="px-3 py-2 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 text-xs font-semibold flex items-center gap-1.5 transition-all disabled:opacity-50"
                >
                  {isCreating ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Plus className="w-3.5 h-3.5" />
                  )}
                  Generate token
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(false);
                    setCreateError(null);
                  }}
                  className="px-3 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 border border-[#222D3D] text-xs font-semibold transition-all"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {/* The list. Metadata only — the raw value is never re-shown. */}
          <div data-testid="widget-token-list" className="space-y-2">
            {isLoading ? (
              <p className="text-xs text-slate-500 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading widget tokens…
              </p>
            ) : loadError ? (
              <div className="flex items-center gap-3">
                <p className="text-xs text-rose-300 flex-1">{loadError}</p>
                <button
                  onClick={() => void loadTokens()}
                  className="px-3 py-1.5 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 border border-[#222D3D] text-xs font-semibold transition-all shrink-0"
                >
                  Try again
                </button>
              </div>
            ) : !hasTokens ? (
              <p className="text-xs text-slate-500">
                No widget token issued yet — generate one to embed chat on your own site.
              </p>
            ) : (
              tokens!.map((token) => (
                <div
                  key={token.id}
                  data-testid={`widget-token-${token.id}`}
                  className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-2"
                >
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="text-xs font-semibold text-white truncate">{token.label}</p>
                      <p className="font-mono text-[11px] text-slate-400 truncate">
                        {token.masked_token ?? token.token_prefix}
                      </p>
                    </div>
                    {confirmRevokeId !== token.id && (
                      <button
                        onClick={() => {
                          setConfirmRevokeId(token.id);
                          setRevokeError(null);
                        }}
                        data-testid={`widget-token-revoke-${token.id}`}
                        className="px-3 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-semibold flex items-center gap-1.5 transition-all shrink-0"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> Revoke
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
                    <div>
                      <span className="uppercase font-mono text-slate-500 tracking-wider text-[10px]">
                        Domains
                      </span>
                      <p className="text-slate-300 font-mono break-all">
                        {token.allowed_origins.length
                          ? token.allowed_origins.join(", ")
                          : "Any (origin check not applied)"}
                      </p>
                    </div>
                    <div>
                      <span className="uppercase font-mono text-slate-500 tracking-wider text-[10px]">
                        Issued
                      </span>
                      <p className="text-slate-300">{formatTimestamp(token.created_at)}</p>
                    </div>
                    <div>
                      <span className="uppercase font-mono text-slate-500 tracking-wider text-[10px]">
                        Last used
                      </span>
                      <p className="text-slate-300">{formatTimestamp(token.last_used_at)}</p>
                    </div>
                  </div>

                  {/* Revoke is destructive and immediate — the backend stamps
                      `revoked_at` and checks it on every resolve, so there is no
                      grace period to undo it in. Hence a confirm step rather
                      than a single click. */}
                  {confirmRevokeId === token.id && (
                    <div className="bg-rose-500/5 border border-rose-500/30 rounded-lg p-3 space-y-2">
                      <p className="text-[11px] text-rose-200 leading-relaxed">
                        Revoke <span className="font-semibold">{token.label}</span>? Any site using
                        this token stops working on its very next request, and the token cannot be
                        restored — you would have to issue a new one and re-paste it.
                      </p>
                      {revokeError && (
                        <p className="text-[11px] text-rose-300 flex items-start gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {revokeError}
                        </p>
                      )}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => void handleRevoke(token.id)}
                          disabled={revokingId === token.id}
                          data-testid={`widget-token-revoke-confirm-${token.id}`}
                          className="px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/40 text-xs font-semibold flex items-center gap-1.5 transition-all disabled:opacity-50"
                        >
                          {revokingId === token.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="w-3.5 h-3.5" />
                          )}
                          Yes, revoke it
                        </button>
                        <button
                          onClick={() => setConfirmRevokeId(null)}
                          className="px-3 py-1.5 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 border border-[#222D3D] text-xs font-semibold transition-all"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Embed instructions. Only once a token exists — before that there is
              nothing to embed and this is just noise. */}
          {hasTokens && (
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-white">Using your token</p>
                  {/* Said plainly, because the honest answer is not the one a
                      reader expects from the word "widget". */}
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    There is no drop-in script or ready-made chat bubble to paste yet — what exists
                    today is the token and one REST endpoint. You call it from your own site&apos;s
                    code and render the answer in your own UI.
                  </p>
                </div>
                <button
                  onClick={() => copy(embedSnippet(), setCopiedSnippet)}
                  className="px-3 py-1.5 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 border border-[#222D3D] text-xs font-semibold flex items-center gap-1.5 transition-all shrink-0"
                >
                  {copiedSnippet ? (
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                  Copy
                </button>
              </div>
              <pre
                data-testid="widget-embed-snippet"
                className="text-[11px] font-mono text-emerald-300 bg-[#050816] border border-[#222D3D] rounded-lg p-3 overflow-x-auto whitespace-pre"
              >
                {embedSnippet()}
              </pre>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                Replace <span className="font-mono text-slate-400">&lt;your-domain&gt;</span> with
                this workspace&apos;s API host and{" "}
                <span className="font-mono text-slate-400">YOUR_WIDGET_TOKEN</span> with the token
                you copied. Cross-origin calls from your own site are allowed for this endpoint
                specifically. Pick this as your chat channel in{" "}
                <Link
                  href="/settings/workflows"
                  className="text-blue-400 hover:text-blue-300 underline underline-offset-2"
                >
                  Settings → Workflows
                </Link>
                .
              </p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
