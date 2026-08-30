"use client";

/**
 * Feature 17 (FE Gap 323): Plug & Play Setup Wizard — /settings/workflows
 *
 * Four questions, in the founder's own order: where invoices come in, how much
 * a machine is allowed to finish on its own, where results go, and how the
 * tenant reaches chat. A fifth screen reviews the answers before saving.
 *
 * Backed by BE Feature 25 / Gap 336's `GET`/`PUT /api/v1/settings/workflow`
 * (invoice-be/routers/settings.py). Three properties of that endpoint shape
 * this page and are worth knowing before editing it:
 *
 *   1. **Both verbs are Admin-only**, including the GET — it reports
 *      `api_key_scope`, which is security configuration. Hence the
 *      Access-Restricted gate below, rather than a read-only view for others.
 *   2. **`audit_policy` is derived from `Tenant.api_key_scope` on read**, not
 *      echoed back from the stored config row. So the server's answer is
 *      authoritative and can legitimately differ from what was sent; every
 *      piece of form state is re-seeded from the PUT response rather than
 *      assumed to match the local draft.
 *   3. **Unbuilt output destinations are rejected with a 422**, not stored.
 *      One is left (`drive_archive`, BE Gap 338) and it is disabled here so a
 *      user cannot lose a selection, but `handleSave` still surfaces the
 *      backend's own message and keeps the draft intact if one ever gets
 *      through. `email_summary` became selectable when BE Gap 339 built its
 *      delivery; `chat_access: "widget"` became selectable when BE Gap 341
 *      built the widget runtime and FE Gap 325 built the token UI.
 *
 * Settings screens in this app call the proxy routes with a bare `fetch`, not
 * `lib/apiClient.ts` — matched here deliberately rather than introducing a
 * second idiom on one surface.
 */

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Mail,
  FolderSync,
  Terminal,
  Upload,
  Zap,
  ShieldCheck,
  Webhook,
  LayoutDashboard,
  MessageSquare,
  Code2,
  AppWindow,
  Check,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertTriangle,
  ShieldAlert,
  CheckCircle2,
  Pencil,
  Workflow,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

const WORKFLOW_URL = "/api/settings/workflow";
/**
 * FE Gap 325: read-only here. Used only to tell an Admin who picks the widget
 * chat channel whether they have actually issued a token yet — the wizard never
 * issues or revokes one, that lives on Settings → Security. Admin-only on the
 * backend, same as the workflow endpoint, so this page is already the right
 * audience for it.
 */
const WIDGET_TOKENS_URL = "/api/settings/security/widget-tokens";

/** The exact response shape of GET/PUT /api/v1/settings/workflow. */
interface WorkflowConfig {
  input_channels: string[];
  audit_policy: string;
  output_destinations: string[];
  chat_access: string;
  completed_at: string | null;
  /** Read-only mirror of `Tenant.api_key_scope` — "readonly" or "actions". */
  api_key_scope: string;
}

/** Local, editable copy of the four answerable fields. */
interface WorkflowConfigDraft {
  input_channels: string[];
  audit_policy: string;
  output_destinations: string[];
  chat_access: string;
}

interface Option {
  /** The literal the backend accepts. Never a display string. */
  value: string;
  label: string;
  desc: string;
  icon: React.ComponentType<{ className?: string }>;
  /**
   * Set when the thing this option describes does not exist yet. The option is
   * rendered, disabled, with this text as the reason — naming the gap that will
   * build it, so "coming soon" is a specific claim rather than a vague one.
   */
  unavailable?: string;
  /** Where in the product this channel/destination is actually configured. */
  configuredAt?: { label: string; href: string };
}

const STEPS = [
  "Input channels",
  "Audit policy",
  "Output destinations",
  "Chat access",
] as const;
const REVIEW_STEP = STEPS.length;

/**
 * All four input channels work today. `api` is the newest: BE Gap 335 built the
 * dual-credential auth that makes an API key able to do more than echo its own
 * identity, so "Direct API" is a real answer rather than an aspiration.
 */
const INPUT_CHANNELS: Option[] = [
  {
    value: "email",
    label: "Email",
    desc: "Vendors email invoices to your shared mailbox; addresses on your inbound set are ingested automatically.",
    icon: Mail,
    configuredAt: { label: "Settings → Email Setup", href: "/settings/email" },
  },
  {
    value: "drive",
    label: "Google Drive",
    desc: "A watched Drive folder is synced on a schedule and every new document is ingested.",
    icon: FolderSync,
    configuredAt: { label: "Settings → Connectors", href: "/settings/connectors" },
  },
  {
    value: "api",
    label: "Direct API",
    desc: "Your own system POSTs invoices to the REST API using your tenant API key.",
    icon: Terminal,
    configuredAt: { label: "Settings → Security", href: "/settings/security" },
  },
  {
    value: "manual",
    label: "Manual upload",
    desc: "A person drops files into the Ingest screen. Always available, whatever else you pick.",
    icon: Upload,
    configuredAt: { label: "Ingest", href: "/ingestion" },
  },
];

/**
 * The founder's two policies. The wire values are `full_automation` /
 * `strict_review` — NOT `full_auto_pilot`. Feature 13 already ships a "Tenant
 * Autopilot" that means scheduled Google Drive sync and is configured from this
 * same Settings area, so the copy below names that collision explicitly instead
 * of leaving two unrelated things sharing a word.
 */
const AUDIT_POLICIES: (Option & { scope: string; caution: string })[] = [
  {
    value: "full_automation",
    label: "Full Automation",
    desc: "Your API key can approve, reject, verify, confirm-send and mark-paid on its own. Invoices can complete their whole lifecycle with no human step.",
    icon: Zap,
    scope: "actions",
    caution:
      "This widens what a leaked or misused key can do — it can finalise money movement, not just read and upload. Rotate the key from Settings → Security if you ever suspect it is exposed.",
  },
  {
    value: "strict_review",
    label: "Strict Review",
    desc: "Your API key stays read- and upload-only. A person finalises every invoice in this app, no matter how it arrived.",
    icon: ShieldCheck,
    scope: "readonly",
    caution:
      "Machines can still feed the system and read from it. Only the approve / reject / send / mark-paid actions require a human.",
  },
];

/**
 * Email summary (BE Gap 339) landed 2026-08-30 -- the backend now accepts and
 * delivers it, gated on the tenant having at least one registered sender
 * address (the same allowlist Settings -> Email Setup manages). Drive archive
 * (BE Gap 338) is still designed but nothing delivers to it; the backend
 * answers 422 rather than storing a choice it cannot honour, so it stays
 * rendered disabled to avoid a selection that silently gets lost on save.
 */
const OUTPUT_DESTINATIONS: Option[] = [
  {
    value: "email_summary",
    label: "Email summary",
    desc: "A run summary emailed to your team after each batch is processed.",
    icon: Mail,
    configuredAt: { label: "Settings → Email Setup", href: "/settings/email" },
  },
  {
    value: "drive_archive",
    label: "Google Drive archive",
    desc: "Processed invoices and their extracted data written back to a Drive folder.",
    icon: FolderSync,
    unavailable: "Not available yet — BE Gap 338 will build the Google Drive write-back.",
  },
  {
    value: "webhook",
    label: "Webhook",
    desc: "Signed HTTP callbacks to your endpoint as invoices change state.",
    icon: Webhook,
    configuredAt: { label: "Settings → Webhooks", href: "/settings/webhooks" },
  },
  {
    value: "dashboard_only",
    label: "Dashboard only",
    desc: "Results stay in this app. Nothing is pushed anywhere else.",
    icon: LayoutDashboard,
  },
];

/**
 * The widget was the awkward one, and it is no longer disabled.
 *
 * It used to be: the backend *accepted and stored* `chat_access: "widget"`
 * while BE Gap 341 had built nothing behind it, so picking it would have saved
 * cleanly and done nothing at all, with no 422 to correct the impression.
 * BE Gap 341 landed 2026-08-30 and built the runtime — `WidgetToken`, the
 * Admin-only issue/revoke endpoints, and `POST /api/v1/widget/chat/message`
 * with its own CORS — and FE Gap 325 built the UI that issues the token
 * (`components/settings/WidgetTokenSection.tsx`). So the option is enabled and
 * points at where it is finished, exactly like `email` and `api` do.
 *
 * It is enabled unconditionally rather than gated on a token already existing.
 * `chat_access` is a stated preference and stores nothing that implies
 * delivery (BE Gap 336 recorded that distinction against the rejected output
 * destinations), and the wizard is precisely where a tenant finds out they need
 * a token. Blocking the selection would mean an Admin has to leave, issue a
 * credential for a feature they have not chosen yet, and come back. Instead the
 * step shows a live "no token issued yet" note when the list is empty — see
 * `widgetTokenCount` below.
 */
const CHAT_ACCESS_OPTIONS: Option[] = [
  {
    value: "dashboard",
    label: "Our dashboard",
    desc: "Your team uses the Chat screen in this app. Nothing to set up.",
    icon: MessageSquare,
    configuredAt: { label: "Chat", href: "/chat" },
  },
  {
    value: "api",
    label: "API",
    desc: "Your own product calls the chat endpoints with your tenant API key.",
    icon: Code2,
    configuredAt: { label: "Settings → Security", href: "/settings/security" },
  },
  {
    value: "widget",
    label: "Embeddable widget",
    desc: "Your website's visitors chat with the assistant without signing in here, using a published chat-only token. You call one endpoint and render the answer in your own UI — there is no drop-in script yet.",
    icon: AppWindow,
    configuredAt: { label: "Settings → Security", href: "/settings/security" },
  },
];

/**
 * Website Gap 13's rule, reused: only a JSON error body is trusted for a
 * user-facing message. Everything else falls back to the caller's generic
 * string, so an HTML error page from a proxy can never be rendered verbatim
 * inside the app. The backend's 422 `detail` here already names the
 * destination, the gap that will build it, and what is available instead —
 * which is exactly why it is shown rather than replaced.
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

function labelFor(options: Option[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

/**
 * Founder ask, 2026-08-30: after saving, someone who picked an "API" option
 * had nothing telling them what to actually call -- "API" was recorded as a
 * preference, but no real example request was ever shown anywhere. This is
 * that example, built from what was actually just saved (input=api and/or
 * chat_access=api and/or audit_policy=full_automation), not a generic docs
 * link. `YOUR_API_KEY` is a placeholder deliberately -- the raw key is only
 * ever shown once, at rotation time on Settings -> Security, and this page
 * has no access to it.
 */
function QuickStartSnippets({ config }: { config: WorkflowConfig }) {
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const snippets: { title: string; body: string }[] = [];

  if (config.input_channels.includes("api")) {
    snippets.push({
      title: "Upload an invoice",
      body:
        `curl -X POST https://<your-domain>/api/v1/invoices/upload \\\n` +
        `  -H "X-API-Key: YOUR_API_KEY" \\\n` +
        `  -F "file=@invoice.pdf"`,
    });
  }

  if (config.chat_access === "api") {
    snippets.push({
      title: "Ask SAGE a question",
      body:
        `curl -X POST https://<your-domain>/api/v1/chat/sessions/YOUR_SESSION_ID/message \\\n` +
        `  -H "X-API-Key: YOUR_API_KEY" \\\n` +
        `  -H "Content-Type: application/json" \\\n` +
        `  -d '{"message": "What was our total spend last month?"}'`,
    });
  }

  if (config.chat_access === "widget") {
    // FE Gap 325. A different credential from the two above, on a different
    // route — `inv_widget_...`, issued on Settings → Security, and the only
    // endpoint it reaches. Named as such so nobody pastes their API key here.
    snippets.push({
      title: "Chat from your own website",
      body:
        `curl -X POST https://<your-domain>/api/v1/widget/chat/message \\\n` +
        `  -H "X-API-Key: YOUR_WIDGET_TOKEN" \\\n` +
        `  -H "Content-Type: application/json" \\\n` +
        `  -d '{"content": "What was our total spend last month?"}'`,
    });
  }

  if (config.audit_policy === "full_automation") {
    snippets.push({
      title: "Approve an invoice",
      body:
        `curl -X PUT https://<your-domain>/api/v1/audit/resolve/YOUR_INVOICE_ID \\\n` +
        `  -H "X-API-Key: YOUR_API_KEY" \\\n` +
        `  -H "Content-Type: application/json" \\\n` +
        `  -d '{"status": "PAID"}'`,
    });
  }

  if (!snippets.length) return null;

  return (
    <div className="bg-[#0F1622] border border-[#222D3D] rounded-2xl p-4 space-y-3">
      <div>
        <p className="text-sm font-semibold text-white">Quick start</p>
        <p className="text-[11px] text-slate-400 leading-relaxed">
          Based on what you just saved. Swap{" "}
          <span className="font-mono text-slate-300">YOUR_API_KEY</span> and{" "}
          <span className="font-mono text-slate-300">YOUR_WIDGET_TOKEN</span> for the real
          credentials from{" "}
          <Link href="/settings/security" className="text-blue-400 hover:text-blue-300 underline">
            Settings → Security
          </Link>
          . They are two different credentials — the widget token is chat-only and meant to be
          published in your site; the API key is not.
        </p>
      </div>
      {snippets.map((s, i) => (
        <div key={s.title} className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-300">{s.title}</span>
            <button
              onClick={() => {
                navigator.clipboard?.writeText(s.body).then(() => {
                  setCopiedIdx(i);
                  setTimeout(() => setCopiedIdx((cur) => (cur === i ? null : cur)), 2000);
                });
              }}
              className="text-[10px] font-semibold text-blue-400 hover:text-blue-300"
            >
              {copiedIdx === i ? "✓ Copied" : "Copy"}
            </button>
          </div>
          <pre className="text-[11px] font-mono text-emerald-300 bg-[#050816] border border-[#222D3D] rounded-lg p-3 overflow-x-auto whitespace-pre">
            {s.body}
          </pre>
        </div>
      ))}
    </div>
  );
}

/** One selectable option row. Multi-select renders as a checkbox, single as a radio. */
function OptionCard({
  option,
  selected,
  multi,
  onToggle,
}: {
  option: Option;
  selected: boolean;
  multi: boolean;
  onToggle: () => void;
}) {
  const Icon = option.icon;
  const disabled = Boolean(option.unavailable);

  return (
    <div
      role={multi ? "checkbox" : "radio"}
      aria-checked={selected}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      data-testid={`workflow-option-${option.value}`}
      onClick={() => !disabled && onToggle()}
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      className={`flex items-start gap-3 p-4 rounded-xl border text-left transition-all ${
        disabled
          ? "bg-[#0B0F19] border-[#1B2434] opacity-60 cursor-not-allowed"
          : selected
          ? "bg-blue-500/10 border-blue-500/50 cursor-pointer"
          : "bg-[#0B0F19] border-[#222D3D] hover:border-[#334155] cursor-pointer"
      }`}
    >
      <div
        className={`w-9 h-9 rounded-lg border flex items-center justify-center shrink-0 ${
          selected && !disabled
            ? "bg-blue-500/15 border-blue-500/30 text-blue-300"
            : "bg-[#151B26] border-[#222D3D] text-slate-400"
        }`}
      >
        <Icon className="w-4 h-4" />
      </div>

      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-semibold text-white">{option.label}</p>
          {disabled && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-amber-500/10 text-amber-300 border border-amber-500/30">
              Not available yet
            </span>
          )}
        </div>
        <p className="text-[11px] text-slate-400 leading-relaxed">{option.desc}</p>
        {option.unavailable && (
          <p className="text-[11px] text-amber-300/80 leading-relaxed">{option.unavailable}</p>
        )}
        {option.configuredAt && !disabled && (
          <Link
            href={option.configuredAt.href}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-block text-[11px] text-blue-400 hover:text-blue-300 underline underline-offset-2"
          >
            Configure in {option.configuredAt.label} ↗ (opens in a new tab — your progress here is kept)
          </Link>
        )}
      </div>

      <div
        className={`w-5 h-5 shrink-0 border flex items-center justify-center ${
          multi ? "rounded" : "rounded-full"
        } ${
          selected && !disabled
            ? "bg-blue-500 border-blue-500 text-white"
            : "border-[#334155] text-transparent"
        }`}
      >
        <Check className="w-3.5 h-3.5" />
      </div>
    </div>
  );
}

/** The step indicator. Same tablist idiom the Security settings page uses. */
function StepDots({
  step,
  onJump,
}: {
  step: number;
  onJump: (index: number) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Setup steps"
      className="flex items-center gap-1 border-b border-[#222D3D] overflow-x-auto"
    >
      {STEPS.map((label, index) => (
        <button
          key={label}
          role="tab"
          id={`workflow-tab-${index}`}
          aria-selected={step === index}
          aria-controls="workflow-step-panel"
          onClick={() => onJump(index)}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 -mb-px whitespace-nowrap transition-all ${
            step === index
              ? "border-blue-400 text-white"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <span
            className={`w-5 h-5 rounded-full text-[10px] flex items-center justify-center border ${
              step > index
                ? "bg-blue-500/20 border-blue-500/40 text-blue-300"
                : "border-[#334155] text-slate-400"
            }`}
          >
            {step > index ? <Check className="w-3 h-3" /> : index + 1}
          </span>
          {label}
        </button>
      ))}
      <button
        role="tab"
        id={`workflow-tab-${REVIEW_STEP}`}
        aria-selected={step === REVIEW_STEP}
        aria-controls="workflow-step-panel"
        onClick={() => onJump(REVIEW_STEP)}
        className={`px-4 py-2.5 text-xs font-semibold border-b-2 -mb-px whitespace-nowrap transition-all ${
          step === REVIEW_STEP
            ? "border-blue-400 text-white"
            : "border-transparent text-slate-400 hover:text-slate-200"
        }`}
      >
        Review
      </button>
    </div>
  );
}

export default function WorkflowSettingsPage() {
  // Declared above every early return so the shared header still names the
  // screen while loading and on the Access-Restricted gate — the same ordering
  // app/settings/webhooks/page.tsx uses.
  usePageHeader({
    title: "Plug & Play Workflows",
    subtitle: "Choose how invoices arrive, who finalises them, and where results go",
    backHref: "/settings",
  });

  const { role, loading: authLoading } = useAuth();
  const isAdmin = role === "Admin";

  const [config, setConfig] = useState<WorkflowConfig | null>(null);
  const [draft, setDraft] = useState<WorkflowConfigDraft>({
    input_channels: [],
    audit_policy: "strict_review",
    output_destinations: [],
    chat_access: "dashboard",
  });
  const [fetching, setFetching] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  /**
   * FE Gap 325: how many chat widget tokens this workspace holds. `null` means
   * "not known" — the fetch has not finished or it failed — and the hint below
   * renders nothing in that case rather than guessing. Telling an Admin they
   * have no token when the request simply errored would be worse than saying
   * nothing, and this is advisory copy, not a gate.
   */
  const [widgetTokenCount, setWidgetTokenCount] = useState<number | null>(null);

  /** Seed every piece of local state from a server response, never from the draft. */
  const applyServerConfig = useCallback((data: WorkflowConfig) => {
    setConfig(data);
    setDraft({
      input_channels: data.input_channels ?? [],
      audit_policy: data.audit_policy,
      output_destinations: data.output_destinations ?? [],
      chat_access: data.chat_access,
    });
  }, []);

  const loadConfig = useCallback(async () => {
    setFetching(true);
    setLoadError(null);
    try {
      const res = await fetch(WORKFLOW_URL, { cache: "no-store" });
      if (!res.ok) {
        throw new Error(
          await errorMessage(res, `Could not load your workflow settings (HTTP ${res.status}).`)
        );
      }
      applyServerConfig((await res.json()) as WorkflowConfig);
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Could not load your workflow settings."
      );
    } finally {
      setFetching(false);
    }
  }, [applyServerConfig]);

  /**
   * FE Gap 325. Fails silently on purpose: this drives one advisory line under
   * the widget option, so a failure must leave the wizard exactly as it was
   * rather than turning a nice-to-have into a visible error on a screen about
   * something else. It also does not block `fetching` — the wizard renders
   * without waiting for it.
   */
  const loadWidgetTokenCount = useCallback(async () => {
    try {
      const res = await fetch(WIDGET_TOKENS_URL, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data)) setWidgetTokenCount(data.length);
    } catch {
      /* advisory only — leave it unknown */
    }
  }, []);

  useEffect(() => {
    // The GET is Admin-only on the backend; firing it for anyone else is a
    // guaranteed 403, so wait for identity and skip it entirely for non-Admins.
    // The widget-token list is Admin-only for the same reason and rides along.
    if (authLoading) return;
    if (!isAdmin) {
      setFetching(false);
      return;
    }
    void loadConfig();
    void loadWidgetTokenCount();
  }, [authLoading, isAdmin, loadConfig, loadWidgetTokenCount]);

  const toggleMulti = (field: "input_channels" | "output_destinations", value: string) => {
    setJustSaved(false);
    setDraft((prev) => {
      const current = prev[field];
      return {
        ...prev,
        [field]: current.includes(value)
          ? current.filter((v) => v !== value)
          : [...current, value],
      };
    });
  };

  const setSingle = (field: "audit_policy" | "chat_access", value: string) => {
    setJustSaved(false);
    setDraft((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaveError(null);
    // Clear the previous run's success state before re-saving. Found in a live
    // click-through: a failed second save left "Workflow activated" sitting
    // directly above the failure message, which reads as both at once.
    setJustSaved(false);
    try {
      const res = await fetch(WORKFLOW_URL, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (!res.ok) {
        // The backend's own 422 text names the destination, the gap that will
        // build it, and what is available instead — strictly more useful than
        // anything this page could write. Surface it, and deliberately do NOT
        // touch `draft`: a rejected save must leave the user's answers intact,
        // exactly as the backend leaves its own state untouched.
        throw new Error(await errorMessage(res, `Could not save (HTTP ${res.status}).`));
      }
      applyServerConfig((await res.json()) as WorkflowConfig);
      setJustSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save your workflow settings.");
    } finally {
      setSaving(false);
    }
  };

  const selectedPolicy = AUDIT_POLICIES.find((p) => p.value === draft.audit_policy);
  const isFirstRun = config !== null && config.completed_at === null;

  // ---- gates -------------------------------------------------------------

  if (authLoading || fetching) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0B0F19]">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-[#0B0F19] text-center p-6">
        <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center text-red-500 mb-4">
          <ShieldAlert className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-bold text-white mb-2">Access Restricted</h2>
        <p className="text-slate-400 text-sm max-w-sm mb-6">
          Only organisation Administrators can view or change workflow settings — this decides
          whether a machine may approve and send your invoices.
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

  if (loadError) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-[#0B0F19] text-center p-6">
        <AlertTriangle className="w-8 h-8 text-rose-400 mb-3" />
        <p className="text-sm text-rose-300 max-w-md mb-4">{loadError}</p>
        <button
          onClick={() => void loadConfig()}
          className="px-4 py-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-200 border border-[#222D3D] text-xs font-semibold transition-all"
        >
          Try again
        </button>
      </div>
    );
  }

  // ---- wizard ------------------------------------------------------------

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      <main className="flex-1 px-6 py-8 max-w-4xl w-full mx-auto space-y-5">

        {isFirstRun && (
          <div className="bg-blue-500/5 border border-blue-500/30 rounded-2xl p-4 flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-300 shrink-0">
              <Workflow className="w-4 h-4" />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-white">Let&apos;s set up your workflow</p>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Four questions. Nothing here is permanent — you can come back to Settings →
                Workflows and change any of it at any time.
              </p>
            </div>
          </div>
        )}

        {justSaved && (
          <div
            data-testid="workflow-saved"
            className="bg-emerald-500/5 border border-emerald-500/30 rounded-2xl p-4 flex items-start gap-3"
          >
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="text-sm font-semibold text-white">Workflow activated</p>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Your API key scope is now{" "}
                <span className="font-mono text-emerald-300">{config?.api_key_scope}</span>. Change
                any answer below and save again whenever you need to.
              </p>
            </div>
          </div>
        )}

        {justSaved && config && <QuickStartSnippets config={config} />}

        <StepDots step={step} onJump={setStep} />

        <section
          role="tabpanel"
          id="workflow-step-panel"
          aria-labelledby={`workflow-tab-${step}`}
          className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg"
        >
          {/* ---- Step 1: input channels ---- */}
          {step === 0 && (
            <>
              <div>
                <h2 className="font-semibold text-sm text-white">Where do invoices come in?</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Pick every channel you use. All four are live today.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {INPUT_CHANNELS.map((option) => (
                  <OptionCard
                    key={option.value}
                    option={option}
                    multi
                    selected={draft.input_channels.includes(option.value)}
                    onToggle={() => toggleMulti("input_channels", option.value)}
                  />
                ))}
              </div>
            </>
          )}

          {/* ---- Step 2: audit policy ---- */}
          {step === 1 && (
            <>
              <div>
                <h2 className="font-semibold text-sm text-white">
                  How much can a machine finish on its own?
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  This decides what your API key is allowed to do. It does not change how invoices
                  are checked — only who is permitted to press the button.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3">
                {AUDIT_POLICIES.map((option) => (
                  <OptionCard
                    key={option.value}
                    option={option}
                    multi={false}
                    selected={draft.audit_policy === option.value}
                    onToggle={() => setSingle("audit_policy", option.value)}
                  />
                ))}
              </div>
              {selectedPolicy && (
                <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1.5">
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    {selectedPolicy.caution}
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Resulting API key scope:{" "}
                    <span className="font-mono text-slate-300">{selectedPolicy.scope}</span>
                  </p>
                </div>
              )}
              {/* Feature 13 ships a "Tenant Autopilot" meaning scheduled Drive
                  sync, configured from this same Settings area. Two unrelated
                  things must not quietly share a word in the user's head. */}
              <p className="text-[11px] text-slate-500 leading-relaxed">
                Not the same thing as <strong className="text-slate-400">Autopilot</strong> under
                Connectors — that schedules Google Drive folder syncing. This setting is only about
                who may approve, send and mark invoices paid.
              </p>
            </>
          )}

          {/* ---- Step 3: output destinations ---- */}
          {step === 2 && (
            <>
              <div>
                <h2 className="font-semibold text-sm text-white">Where should results go?</h2>
                {/* Was "Two of these" — email summary became selectable when BE
                    Gap 339 built its delivery, leaving only the Drive archive
                    disabled. Corrected here because it is the same "not
                    available yet" mechanism FE Gap 325 is changing one step
                    along, and a count the user can see is wrong reads as
                    carelessness about the rest of the claim. */}
                <p className="text-xs text-slate-400 mt-0.5">
                  One of these is still being built and cannot be selected yet — it is listed so you
                  know it is coming, not to imply it works.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {OUTPUT_DESTINATIONS.map((option) => (
                  <OptionCard
                    key={option.value}
                    option={option}
                    multi
                    selected={draft.output_destinations.includes(option.value)}
                    onToggle={() => toggleMulti("output_destinations", option.value)}
                  />
                ))}
              </div>
            </>
          )}

          {/* ---- Step 4: chat access ---- */}
          {step === 3 && (
            <>
              <div>
                <h2 className="font-semibold text-sm text-white">How will you use chat?</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Ask questions about your invoice data from this app, from your own code, or from
                  your own website.
                </p>
              </div>
              <div
                role="radiogroup"
                aria-label="Chat access"
                className="grid grid-cols-1 sm:grid-cols-2 gap-3"
              >
                {CHAT_ACCESS_OPTIONS.map((option) => (
                  <OptionCard
                    key={option.value}
                    option={option}
                    multi={false}
                    selected={draft.chat_access === option.value}
                    onToggle={() => setSingle("chat_access", option.value)}
                  />
                ))}
              </div>
              {/* FE Gap 325: advisory, not a gate. Saving `widget` is valid on
                  its own — it records the intent and promises no delivery — but
                  nothing works until a token exists, and this is where a tenant
                  would otherwise find that out by silence. Rendered only when
                  the count is actually known (see `widgetTokenCount`). */}
              {draft.chat_access === "widget" && widgetTokenCount === 0 && (
                <div
                  data-testid="widget-token-missing-hint"
                  className="bg-amber-500/5 border border-amber-500/30 rounded-xl p-3.5 flex items-start gap-2"
                >
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <p className="text-[11px] text-amber-200/90 leading-relaxed">
                    You have not issued a chat widget token yet, so nothing will work on your site
                    until you do. This answer still saves fine — issue one in{" "}
                    <Link
                      href="/settings/security"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-300 hover:text-blue-200 underline underline-offset-2"
                    >
                      Settings → Security ↗
                    </Link>{" "}
                    when you are ready.
                  </p>
                </div>
              )}
            </>
          )}

          {/* ---- Review ---- */}
          {step === REVIEW_STEP && (
            <>
              <div>
                <h2 className="font-semibold text-sm text-white">Review and activate</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  This is exactly what will be saved. Options that are not built yet are not
                  included.
                </p>
              </div>

              <dl className="divide-y divide-[#222D3D]/60">
                <div className="py-3 grid grid-cols-1 sm:grid-cols-3 gap-1">
                  <dt className="text-[11px] uppercase font-mono text-slate-500 tracking-wider">
                    Input channels
                  </dt>
                  <dd className="sm:col-span-2 text-xs text-slate-200">
                    {draft.input_channels.length
                      ? draft.input_channels.map((v) => labelFor(INPUT_CHANNELS, v)).join(", ")
                      : "None selected"}
                  </dd>
                </div>
                <div className="py-3 grid grid-cols-1 sm:grid-cols-3 gap-1">
                  <dt className="text-[11px] uppercase font-mono text-slate-500 tracking-wider">
                    Audit policy
                  </dt>
                  <dd className="sm:col-span-2 text-xs text-slate-200">
                    {labelFor(AUDIT_POLICIES, draft.audit_policy)}
                    <span className="text-slate-500">
                      {" "}
                      — API key scope{" "}
                      <span className="font-mono">{selectedPolicy?.scope ?? "readonly"}</span>
                    </span>
                  </dd>
                </div>
                <div className="py-3 grid grid-cols-1 sm:grid-cols-3 gap-1">
                  <dt className="text-[11px] uppercase font-mono text-slate-500 tracking-wider">
                    Output destinations
                  </dt>
                  <dd className="sm:col-span-2 text-xs text-slate-200">
                    {draft.output_destinations.length
                      ? draft.output_destinations
                          .map((v) => labelFor(OUTPUT_DESTINATIONS, v))
                          .join(", ")
                      : "None selected"}
                  </dd>
                </div>
                <div className="py-3 grid grid-cols-1 sm:grid-cols-3 gap-1">
                  <dt className="text-[11px] uppercase font-mono text-slate-500 tracking-wider">
                    Chat access
                  </dt>
                  <dd className="sm:col-span-2 text-xs text-slate-200">
                    {labelFor(CHAT_ACCESS_OPTIONS, draft.chat_access)}
                  </dd>
                </div>
              </dl>

              {saveError && (
                <div
                  data-testid="workflow-save-error"
                  className="bg-rose-500/5 border border-rose-500/30 rounded-xl p-3.5 flex items-start gap-2"
                >
                  <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    {/* The backend's own words, not a rewrite of them. */}
                    <p className="text-xs text-rose-200 leading-relaxed">{saveError}</p>
                    <p className="text-[11px] text-slate-400">
                      Nothing was saved and your answers above are unchanged — adjust them and try
                      again.
                    </p>
                  </div>
                </div>
              )}

              <div className="flex items-center gap-3">
                <button
                  onClick={() => void handleSave()}
                  disabled={saving}
                  data-testid="workflow-save"
                  className="px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-3.5 h-3.5" />
                  )}
                  Save &amp; Activate
                </button>
                <button
                  onClick={() => setStep(0)}
                  className="px-4 py-2.5 rounded-xl bg-[#1E293B] hover:bg-[#2D3F55] text-slate-300 border border-[#222D3D] text-xs font-semibold flex items-center gap-2 transition-all"
                >
                  <Pencil className="w-3.5 h-3.5" /> Edit answers
                </button>
              </div>
            </>
          )}
        </section>

        {/* Step navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="px-4 py-2.5 rounded-xl bg-[#151B26] hover:bg-[#1E293B] text-slate-300 border border-[#222D3D] text-xs font-semibold flex items-center gap-1.5 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="w-3.5 h-3.5" /> Back
          </button>
          <button
            onClick={() => setStep((s) => Math.min(REVIEW_STEP, s + 1))}
            disabled={step === REVIEW_STEP}
            className="px-4 py-2.5 rounded-xl bg-[#151B26] hover:bg-[#1E293B] text-slate-300 border border-[#222D3D] text-xs font-semibold flex items-center gap-1.5 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {step === REVIEW_STEP - 1 ? "Review" : "Next"}{" "}
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {config?.completed_at && (
          <p className="text-[11px] text-slate-500">
            Last completed {new Date(config.completed_at).toLocaleString()}. Current API key scope:{" "}
            <span className="font-mono text-slate-400">{config.api_key_scope}</span>.
          </p>
        )}
      </main>
    </div>
  );
}
