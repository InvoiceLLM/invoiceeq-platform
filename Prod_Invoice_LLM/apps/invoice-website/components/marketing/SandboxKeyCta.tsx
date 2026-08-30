"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Check, Copy, KeyRound, Loader2 } from "lucide-react";
import {
  SANDBOX_KEYS_ENABLED,
  readStoredSandboxKey,
  storeSandboxKey,
} from "@/lib/sandboxKey";

/**
 * Website Feature 7 / Gap 350 — the "Get Sandbox API Key" CTA.
 *
 * This is the CTA slot of `WorkflowRecipeSelector`, extracted into its own
 * component for one specific reason: it is the **only** part of Feature 7 that
 * makes a network call. The recipe selector, the SAGE preview, the hero mode
 * tabs and the pipeline demo are all fixture-driven and stay that way (see
 * `feature_7_plug_and_play_workflows.md` §7). Keeping the fetch here means that
 * contract is still checkable by looking at one file, rather than "the recipe
 * selector is fixture-only except for the bit at the bottom".
 *
 * It replaces the `<Link href="/signup">Start Free Trial</Link>` that Gap 348
 * shipped, together with the block comment that recorded "retarget this once BE
 * Gap 340 lands". Gap 340 has landed.
 *
 * THE /signup LINK DOES NOT GO AWAY. It is still rendered in every state:
 *
 *  * when `SANDBOX_KEYS_ENABLED` is false (the default, and the state of every
 *    environment today) this component renders exactly what Gap 348 rendered —
 *    one gradient "Start Free Trial" link and nothing else, so the default
 *    build ships no dead button;
 *  * when the sandbox CTA is on, "Start Free Trial" demotes to a secondary
 *    link beside it — a sandbox key is a trial of the engine, not a signup, and
 *    the visitor who already knows they want the product must not have to take
 *    a throwaway credential first;
 *  * after a key is issued it becomes the *next* step, because claiming
 *    (`POST /api/sandbox/claim`, wired in `app/signup/page.tsx`) is what turns
 *    the throwaway workspace into a real one.
 */

interface IssuedSandboxKey {
  apiKey: string;
  tenantId: string;
  expiresAt: string;
  chatMessageLimit: number | null;
  invoiceLimit: number | null;
  /** True when this was read back out of localStorage rather than just issued. */
  restored: boolean;
}

type CtaError = { detail: string; code: string };

/** `expires_at` is ISO-8601 from the backend; render it, or fall back to raw. */
function formatExpiry(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  return new Date(ts).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function SandboxKeyCta() {
  const [loading, setLoading] = useState(false);
  const [issued, setIssued] = useState<IssuedSandboxKey | null>(null);
  const [error, setError] = useState<CtaError | null>(null);
  const [copied, setCopied] = useState(false);

  // Read after mount, never during render: localStorage does not exist on the
  // server, and branching on it in the render body would be a hydration
  // mismatch. The idle button is what SSR emits, always.
  useEffect(() => {
    if (!SANDBOX_KEYS_ENABLED) return;
    const stored = readStoredSandboxKey();
    if (stored) {
      setIssued({
        apiKey: stored.apiKey,
        tenantId: stored.tenantId,
        expiresAt: stored.expiresAt,
        chatMessageLimit: null,
        invoiceLimit: null,
        restored: true,
      });
    }
  }, []);

  const requestKey = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/sandbox/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = (await response.json().catch(() => ({}))) as {
        api_key?: string;
        tenant_id?: string;
        expires_at?: string;
        chat_message_limit?: number;
        invoice_limit?: number;
        detail?: string;
        code?: string;
      };

      if (!response.ok || !data.api_key || !data.expires_at) {
        setError({
          detail:
            data.detail ||
            "Couldn't issue a sandbox key right now. Please try again shortly.",
          code: data.code || "error",
        });
        return;
      }

      // Persisted BEFORE it is rendered, so a visitor who copies the key and
      // immediately navigates to /signup still gets the claim. If persistence
      // fails (blocked site data) it warns and carries on — the key is still
      // usable, only the automatic claim is lost.
      storeSandboxKey({
        apiKey: data.api_key,
        tenantId: data.tenant_id || "",
        expiresAt: data.expires_at,
      });

      setIssued({
        apiKey: data.api_key,
        tenantId: data.tenant_id || "",
        expiresAt: data.expires_at,
        chatMessageLimit:
          typeof data.chat_message_limit === "number" ? data.chat_message_limit : null,
        invoiceLimit:
          typeof data.invoice_limit === "number" ? data.invoice_limit : null,
        restored: false,
      });
    } catch (err) {
      console.error("[sandbox-cta] request failed:", err);
      setError({
        detail: "Couldn't reach the sandbox service. Please try again shortly.",
        code: "unreachable",
      });
    } finally {
      setLoading(false);
    }
  };

  const copyKey = () => {
    if (!issued) return;
    navigator.clipboard?.writeText(issued.apiKey).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => {
        /* clipboard denied — the key is selectable on screen either way */
      }
    );
  };

  // ---------------------------------------------------------------------
  // Flag off: byte-for-byte the Gap 348 CTA. No button that cannot work.
  // ---------------------------------------------------------------------
  if (!SANDBOX_KEYS_ENABLED) {
    return (
      <Link
        href="/signup"
        className="btn-primary-gradient shrink-0 text-xs px-5 py-2.5 flex items-center justify-center gap-2 group"
      >
        <span>Start Free Trial</span>
        <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
      </Link>
    );
  }

  return (
    <div className="shrink-0 w-full sm:w-auto sm:max-w-[380px] flex flex-col gap-2.5 items-stretch">
      {!issued && (
        <div className="flex flex-col sm:flex-row sm:items-center gap-2.5">
          <button
            type="button"
            onClick={requestKey}
            disabled={loading}
            className="btn-primary-gradient shrink-0 text-xs px-5 py-2.5 flex items-center justify-center gap-2 group disabled:opacity-70"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <KeyRound className="w-4 h-4" />
            )}
            <span>{loading ? "Issuing…" : "Get Sandbox API Key"}</span>
          </button>
          <Link
            href="/signup"
            className="shrink-0 text-xs font-semibold text-[#94A3B8] hover:text-white transition-colors flex items-center justify-center gap-1.5 group"
          >
            <span>Start Free Trial</span>
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
          </Link>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg border border-[#F43F5E]/35 bg-[#F43F5E]/[0.08] text-[11px] leading-relaxed text-[#FDA4AF]">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
          <span>
            {error.detail}
            {error.code === "sandbox_disabled" && (
              // Honest about *why* nothing happened, without pretending the
              // feature is broken. This is the state a deployment is in
              // whenever the backend's SANDBOX_KEYS_ENABLED is still False.
              <> Everything else on this page is live.</>
            )}
          </span>
        </div>
      )}

      {issued && (
        <div className="p-3.5 rounded-lg border border-[rgba(255,255,255,0.10)] bg-[#050816]/80 backdrop-blur-md flex flex-col gap-2.5">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-[#22D3EE]">
            <KeyRound className="w-3.5 h-3.5" />
            <span>{issued.restored ? "Your sandbox key" : "Sandbox key issued"}</span>
          </div>

          <div className="flex items-start gap-2">
            <code
              className="flex-1 text-[11px] leading-relaxed font-mono text-[#E2E8F0] break-all select-all"
              data-testid="sandbox-key-value"
            >
              {issued.apiKey}
            </code>
            <button
              type="button"
              onClick={copyKey}
              className="shrink-0 px-2 py-1.5 rounded-md border border-[rgba(255,255,255,0.12)] bg-white/[0.04] text-[#94A3B8] hover:text-white hover:border-white/25 transition-colors"
              aria-label="Copy sandbox API key"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-[#10B981]" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          {/*
            The honest note. Every claim here is a real property of BE Gap 340,
            not marketing rounding:
              * "trial" -> a fresh throwaway Tenant, readonly scope, pinned
                three ways on the backend;
              * "limited" -> SANDBOX_CHAT_MESSAGE_LIMIT / SANDBOX_INVOICE_LIMIT,
                reported in the issuance response and shown verbatim when the
                backend sent them;
              * "expires" -> SandboxTenant.expires_at, enforced live on every
                authentication, not only by the sweep job;
              * "keep your trial data" -> POST /api/v1/sandbox/claim, which the
                signup page calls; the workspace is promoted rather than a new
                empty one being created.
          */}
          <p className="text-[11px] leading-relaxed text-[#94A3B8]">
            {issued.restored
              ? "Kept in this browser so signing up can carry your workspace over. "
              : "Shown once — copy it now. "}
            This is a temporary trial key
            {issued.invoiceLimit !== null && issued.chatMessageLimit !== null ? (
              <>
                {" "}
                ({issued.invoiceLimit} invoices, {issued.chatMessageLimit} chat
                messages)
              </>
            ) : null}
            , read and upload only, and it expires on{" "}
            <span className="text-[#E2E8F0]">{formatExpiry(issued.expiresAt)}</span>.
            Sign up for real from this browser and we&apos;ll move this workspace
            over — you keep everything you tried, instead of starting over.
          </p>

          <Link
            href="/signup"
            className="btn-primary-gradient text-xs px-4 py-2 flex items-center justify-center gap-2 group"
          >
            <span>Keep this workspace — sign up</span>
            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </Link>
        </div>
      )}
    </div>
  );
}
