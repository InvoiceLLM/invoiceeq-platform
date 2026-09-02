"use client";

import React, { useState } from "react";
import { useSignUp } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { Header } from "@/components/marketing/Header";
import { clearStoredSandboxKey, readStoredSandboxKey } from "@/lib/sandboxKey";

// Gap 7: the backend is called through this app's own server-side route handler
// at /api/auth/provision, not directly from the browser. The backend Container
// App runs with ingress.external=false, so the browser cannot reach it in Azure.
// See app/api/auth/provision/route.ts.

/* Design tokens (match invoice-fe/invoice-website globals) */
const T = {
  bg: "#0B0F19",
  panel: "rgba(21, 27, 38, 0.80)",
  border: "#222D3D",
  textPrimary: "#E2E8F0",
  textMuted: "#94A3B8",
  textDim: "#64748B",
  green: "#10B981",
  blue: "#3B82F6",
  red: "#EF4444",
  font: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
};

const S: Record<string, React.CSSProperties> = {
  root: { minHeight: "calc(100vh - 65px)", background: T.bg, display: "flex", fontFamily: T.font, color: T.textPrimary, overflow: "hidden", position: "relative" },
  orbTL: { position: "absolute", top: "-120px", left: "-120px", width: "520px", height: "520px", borderRadius: "50%", background: "radial-gradient(circle, rgba(16,185,129,0.13) 0%, transparent 70%)", pointerEvents: "none", zIndex: 0 },
  orbBR: { position: "absolute", bottom: "-150px", right: "-100px", width: "620px", height: "620px", borderRadius: "50%", background: "radial-gradient(circle, rgba(59,130,246,0.10) 0%, transparent 70%)", pointerEvents: "none", zIndex: 0 },
  brandPanel: { flex: "1 1 45%", display: "flex", flexDirection: "column", justifyContent: "center", padding: "64px 56px", position: "relative", zIndex: 1 },
  logoRow: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "56px" },
  logoIcon: { width: "40px", height: "40px", borderRadius: "10px", background: "linear-gradient(135deg, #10B981 0%, #3B82F6 100%)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "20px", fontWeight: 700, color: "#fff", flexShrink: 0 },
  logoText: { fontSize: "20px", fontWeight: 700, letterSpacing: "-0.3px", background: "linear-gradient(90deg, #E2E8F0 0%, #94A3B8 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  headline: { fontSize: "40px", fontWeight: 800, lineHeight: 1.15, letterSpacing: "-1px", marginBottom: "20px", color: T.textPrimary },
  headlineAccent: { background: "linear-gradient(90deg, #10B981 0%, #3B82F6 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  subtext: { fontSize: "16px", color: T.textMuted, lineHeight: 1.65, maxWidth: "380px", marginBottom: "48px" },
  featureList: { display: "flex", flexDirection: "column", gap: "18px" },
  featureItem: { display: "flex", alignItems: "flex-start", gap: "14px" },
  featureDot: { width: "32px", height: "32px", borderRadius: "8px", background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.25)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: "15px" },
  featureTitle: { fontSize: "14px", fontWeight: 600, color: T.textPrimary, marginBottom: "2px" },
  featureDesc: { fontSize: "13px", color: T.textDim },
  vDivider: { width: "1px", flexShrink: 0, zIndex: 1, background: "linear-gradient(to bottom, transparent, #222D3D 20%, #222D3D 80%, transparent)" },
  formPanel: { flex: "1 1 55%", display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 48px", zIndex: 1 },
  card: { width: "100%", maxWidth: "460px", background: T.panel, backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)", border: `1px solid ${T.border}`, borderRadius: "20px", padding: "40px", boxShadow: "0 24px 64px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)" },
  cardHeader: { marginBottom: "28px", textAlign: "center" },
  badge: { display: "inline-flex", alignItems: "center", gap: "6px", background: "rgba(16,185,129,0.10)", border: "1px solid rgba(16,185,129,0.20)", borderRadius: "20px", padding: "4px 12px", fontSize: "11px", color: T.green, fontWeight: 700, letterSpacing: "0.8px", textTransform: "uppercase", marginBottom: "14px" },
  cardTitle: { fontSize: "26px", fontWeight: 700, color: T.textPrimary, letterSpacing: "-0.5px", marginBottom: "6px" },
  cardSubtitle: { fontSize: "14px", color: T.textDim },
  sectionLabel: { fontSize: "11px", fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: "#475569", marginBottom: "10px", marginTop: "22px" },
  inputWrap: { position: "relative" },
  inputIcon: { position: "absolute", left: "13px", top: "50%", transform: "translateY(-50%)", fontSize: "14px", opacity: 0.5, pointerEvents: "none" },
  input: { width: "100%", boxSizing: "border-box", background: "rgba(15, 20, 30, 0.60)", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "11px 14px 11px 38px", fontSize: "14px", color: T.textPrimary, outline: "none", transition: "border-color 0.2s, box-shadow 0.2s" },
  select: { width: "100%", boxSizing: "border-box", background: "rgba(15, 20, 30, 0.60)", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "11px 14px 11px 38px", fontSize: "14px", color: T.textPrimary, outline: "none", transition: "border-color 0.2s, box-shadow 0.2s", appearance: "none", cursor: "pointer" },
  inputFocus: { borderColor: T.green, boxShadow: "0 0 0 3px rgba(16,185,129,0.13)" },
  grid2: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" },
  errorBox: { display: "flex", alignItems: "flex-start", gap: "8px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "10px", padding: "10px 14px", fontSize: "13px", color: T.red, marginTop: "10px" },
  btn: { width: "100%", background: "linear-gradient(135deg, #10B981 0%, #059669 100%)", border: "none", borderRadius: "10px", padding: "13px", fontSize: "15px", fontWeight: 600, color: "#fff", cursor: "pointer", marginTop: "22px", letterSpacing: "0.2px", transition: "opacity 0.2s, transform 0.15s", boxShadow: "0 4px 20px rgba(16,185,129,0.25)" },
  retryBtn: { alignSelf: "flex-start", background: "rgba(239,68,68,0.14)", border: "1px solid rgba(239,68,68,0.35)", borderRadius: "8px", padding: "7px 14px", fontSize: "13px", fontWeight: 600, color: T.red, cursor: "pointer" },
  loginRow: { textAlign: "center", marginTop: "20px", fontSize: "13px", color: T.textDim },
  loginLink: { color: T.blue, textDecoration: "none", fontWeight: 600 },
};

const FEATURES = [
  { icon: "🤖", title: "AI-Powered Invoice Processing", desc: "Extract data from any invoice format automatically" },
  { icon: "🏢", title: "Multi-Tenant Architecture", desc: "Isolate data per organisation with role-based access" },
  { icon: "📊", title: "Real-Time Analytics", desc: "Live dashboards and approval workflows" },
];

const ORG_TYPES = ["Startup", "SMB", "Enterprise", "Freelancer", "Non-Profit", "Other"];
const COUNTRIES = [
  "United States", "United Kingdom", "India", "Canada", "Australia",
  "Germany", "France", "Singapore", "UAE", "Other",
];

/** Exactly the body POST /auth/provision expects (snake_case, FastAPI side). */
interface ProvisionPayload {
  clerk_org_id: string;
  org_name: string;
  admin_email: string;
  clerk_user_id: string;
}

/**
 * Gap 133: POST the provision request with a real Clerk session token.
 *
 * The token is minted here, client-side, immediately after `setActive` -- the
 * proxy route can also mint one from the session cookie, but that cookie lags a
 * just-completed `setActive` (Gap 157 proved this live), and sign-up is the
 * single moment where the lag is guaranteed to be at its worst. The backend
 * checks the token's `sub` against `clerk_user_id` in the body, so an anonymous
 * caller can no longer claim or rename somebody else's tenant.
 *
 * Throws on any non-2xx so both call sites (initial sign-up and Retry) handle
 * failure identically -- and visibly.
 */

/**
 * Carries the HTTP status alongside the message so callers can tell a
 * retryable failure from a terminal one. Without this the status was lost in
 * `new Error(detail)` and every failure looked equally retryable.
 */
class ProvisionError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ProvisionError";
    this.status = status;
  }
}

/**
 * Gap 133: a 409 from POST /auth/provision is terminal, not transient.
 *
 * All four 409 sites in routers/auth.py are "this already exists" conditions --
 * the user already belongs to a workspace, the admin email is held by another
 * account, or the tenant/clerk_org_id conflicts. None of them resolve by trying
 * again, so offering Retry traps the user in a loop that 409s forever.
 */
function isTerminalProvisionFailure(err: unknown): boolean {
  return err instanceof ProvisionError && err.status === 409;
}

/**
 * Gap 342: POST /auth/provision now also mints a production API key for a
 * brand-new tenant and returns it once in the response body -- this was
 * previously discarded entirely (the caller only checked `response.ok`), so
 * the key was minted server-side but never actually reached the user. Parsed
 * and returned here so the signup flow can show it before routing away.
 */
interface ProvisionResult {
  api_key: string | null;
}

async function provisionTenant(payload: ProvisionPayload): Promise<ProvisionResult> {
  let token: string | null = null;
  try {
    // @ts-expect-error -- window.Clerk is the runtime Clerk client, not typed here
    token = (await window.Clerk?.session?.getToken({ template: "invoice-app" })) || null;
  } catch (tokenErr) {
    console.error("Could not mint a Clerk session token for provisioning:", tokenErr);
  }

  const response = await fetch("/api/auth/provision", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({} as { detail?: string; api_key?: string }));

  if (!response.ok) {
    throw new ProvisionError(
      (data as { detail?: string })?.detail || `provisioning failed with HTTP ${response.status}`,
      response.status
    );
  }

  return { api_key: (data as { api_key?: string })?.api_key || null };
}

/**
 * Website Gap 350: the outcome of the optional sandbox-claim step.
 *
 * `claimed` is what the reveal screen's copy branches on. `apiKey` is the fresh
 * `inv_live_...` key the backend mints in the *same transaction* that revokes
 * the `inv_test_...` one — after a successful claim it is the only new key that
 * exists, because `POST /auth/provision` will then find the tenant by
 * `clerk_org_id`, return `is_new=false` and mint nothing.
 */
interface SandboxClaimOutcome {
  claimed: boolean;
  apiKey: string | null;
}

const NO_CLAIM: SandboxClaimOutcome = { claimed: false, apiKey: null };

/**
 * Website Gap 350: promote the sandbox workspace this visitor was issued on the
 * marketing site (BE Gap 340) into the organisation they have just created,
 * instead of stranding their trial invoices/chat in a tenant nobody will look
 * at again.
 *
 * HOW THE SIGNUP PAGE KNOWS THERE IS A SANDBOX. `lib/sandboxKey.ts` — the key
 * was written to localStorage by `SandboxKeyCta` at the moment it was issued.
 * There is nothing server-side to read: the visitor was anonymous when the key
 * was issued, by definition. `readStoredSandboxKey()` returns null when there
 * is no key, when it is malformed, or when it has already expired, so the
 * common case (an ordinary signup) is a synchronous null and no request.
 *
 * ORDERING IS LOAD-BEARING: this runs BEFORE `provisionTenant()`, never after.
 *   * Claim first  -> `claim_sandbox_tenant()` attaches `clerk_org_id` to the
 *     sandbox tenant, so the subsequent provision call finds it by that id,
 *     early-returns `is_new=false` and creates nothing. The `User` row is then
 *     created on first login by `dependencies.py::get_tenant_context`, exactly
 *     as it is for any other already-existing tenant — a claim does not strand
 *     the user (verified against dependencies.py, not assumed).
 *   * Provision first -> a brand-new tenant takes `clerk_org_id`, and the claim
 *     would then try to write the same value onto the sandbox tenant, against a
 *     UNIQUE column. Best case an error, worst case a 500 in the middle of
 *     signup. So the order is not a preference.
 *
 * THIS FUNCTION NEVER THROWS AND NEVER BLOCKS SIGNUP. Claiming is an upgrade
 * path, not a dependency: a lost race, an already-claimed workspace, an expired
 * key, `SANDBOX_KEYS_ENABLED` switched off between issuance and signup, or the
 * backend being unreachable all resolve to `NO_CLAIM`, and signup proceeds as
 * an ordinary fresh signup. Failing signup because a nice-to-have upgrade
 * failed would be strictly worse than not offering the upgrade at all.
 */
async function claimSandboxWorkspace(
  payload: ProvisionPayload
): Promise<SandboxClaimOutcome> {
  let stored: ReturnType<typeof readStoredSandboxKey> = null;
  try {
    stored = readStoredSandboxKey();
  } catch {
    return NO_CLAIM;
  }
  if (!stored) return NO_CLAIM;

  try {
    let token: string | null = null;
    try {
      // Minted client-side for the same reason provisionTenant() does it: the
      // session cookie the route handler would otherwise read lags a
      // just-completed setActive (Gap 157), and the backend binds this token's
      // `sub`/`org_id` to the body's clerk_user_id/clerk_org_id.
      // @ts-expect-error -- window.Clerk is the runtime Clerk client, not typed here
      token = (await window.Clerk?.session?.getToken({ template: "invoice-app" })) || null;
    } catch (tokenErr) {
      console.error("Could not mint a Clerk session token for the sandbox claim:", tokenErr);
    }

    const response = await fetch("/api/sandbox/claim", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        sandbox_key: stored.apiKey,
        clerk_org_id: payload.clerk_org_id,
        org_name: payload.org_name,
        clerk_user_id: payload.clerk_user_id,
      }),
    });

    const data = (await response.json().catch(() => ({}))) as {
      api_key?: string;
      detail?: string;
    };

    if (response.ok) {
      // The `inv_test_` key was revoked server-side in the claim transaction —
      // keeping it locally would only produce failing 401s later.
      clearStoredSandboxKey();
      return { claimed: true, apiKey: data.api_key || null };
    }

    // 400 not-a-sandbox-key / 403 wrong caller / 409 already claimed or not
    // claimable / 410 expired are all terminal: this key will never claim
    // anything, so drop it rather than retrying it at every future signup.
    // 502/503 (unreachable, or SANDBOX_KEYS_ENABLED off) are left alone — the
    // key may still be good, and it expires on its own regardless.
    if ([400, 401, 403, 404, 409, 410].indexOf(response.status) !== -1) {
      clearStoredSandboxKey();
    }
    console.warn(
      `Sandbox claim did not apply (HTTP ${response.status}): ${data?.detail || "no detail"}. ` +
        "Continuing as an ordinary signup."
    );
    return NO_CLAIM;
  } catch (err) {
    console.warn("Sandbox claim failed; continuing as an ordinary signup:", err);
    return NO_CLAIM;
  }
}

function provisionFailureMessage(err: unknown, orgId: string): string {
  const detail = err instanceof Error ? err.message : String(err);

  // Terminal: say so plainly and point somewhere that can actually resolve it.
  // Deliberately does not say "Retry" -- the Retry button is not rendered for
  // this case, and inviting one would just reproduce the same 409.
  if (isTerminalProvisionFailure(err)) {
    return (
      `This account or organisation is already set up, so we can't provision it again (${detail}). ` +
      `Retrying won't change this. If you already have a workspace, sign in below instead — ` +
      `otherwise contact support and quote org id ${orgId}.`
    );
  }

  return (
    `Your account was created, but we couldn't finish setting up your organisation (${detail}). ` +
    `Click Retry — if it keeps failing, contact support and quote org id ${orgId}.`
  );
}

export default function SignupPage() {
  const { isLoaded, signUp, setActive } = useSignUp();
  const router = useRouter();

  const [orgName, setOrgName] = useState("");
  const [orgType, setOrgType] = useState("");
  const [country, setCountry] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState<string | null>(null);
  // Gap 133: set when the Clerk account exists but the backend never registered
  // the organisation. Holds everything the retry needs, so Retry re-POSTs
  // /api/auth/provision for the org that already exists client-side rather than
  // re-running sign-up (which would fail -- the email is taken by then).
  const [pendingProvision, setPendingProvision] = useState<ProvisionPayload | null>(null);
  const [retrying, setRetrying] = useState(false);
  
  const [verificationCode, setVerificationCode] = useState("");
  const [needsVerification, setNeedsVerification] = useState(false);

  // Gap 342 fix: the API key provisioning now mints is shown here exactly
  // once, matching the "shown once, never re-revealed" convention Settings ->
  // Security already uses for key rotation. Null means either provisioning
  // hasn't happened yet, or this was a pre-existing tenant (no new key minted).
  const [provisionedApiKey, setProvisionedApiKey] = useState<string | null>(null);
  const [keyCopied, setKeyCopied] = useState(false);

  // Gap 350: held so the Retry path can still reveal the key a successful claim
  // minted even if the provision call that followed it failed, and so the
  // reveal screen's copy can say "we carried your sandbox over" rather than
  // silently showing a key that means something different from what the visitor
  // expects. Stays NO_CLAIM for every ordinary signup.
  const [sandboxClaim, setSandboxClaim] = useState<SandboxClaimOutcome>(NO_CLAIM);

  const inputStyle = (id: string) => ({ ...S.input, ...(focused === id ? S.inputFocus : {}) });
  const selectStyle = (id: string) => ({ ...S.select, ...(focused === id ? S.inputFocus : {}) });

  const completeSignupAndProvision = async (
    clerkUserId: string,
    createdSessionId: string,
    finalOrgName: string
  ) => {
    if (setActive) {
      await setActive({ session: createdSessionId });
    }

    let orgId: string | null = null;
    try {
      await new Promise((r) => setTimeout(r, 200));
      // @ts-expect-error -- window.Clerk is the runtime Clerk client, not typed here
      const org = await window.Clerk.createOrganization({ name: finalOrgName });
      orgId = org.id;
      // @ts-expect-error -- see above
      await window.Clerk.setActive({ organization: org.id });
    } catch (orgErr: any) {
      console.error("Clerk Org creation failed (is Organizations enabled in Clerk Dashboard?)", orgErr);
      setError(
        "Your account was created, but we couldn't create your organisation " +
          `(${orgErr?.errors?.[0]?.longMessage || orgErr?.message || "unknown error"}). ` +
          "Organisations may be disabled for this Clerk instance. Please contact support " +
          `and quote the email ${email} — do not sign up again with this address.`
      );
      return;
    }

    if (!orgId) {
      console.error("Clerk Org creation returned no organisation id");
      setError(
        "Your account was created, but your organisation could not be created " +
          `(no organisation id was returned). Please contact support and quote the email ${email} — ` +
          "do not sign up again with this address."
      );
      return;
    }

    try {
      // @ts-expect-error -- see above
      await window.Clerk.user.update({
        unsafeMetadata: { orgId, orgName: finalOrgName, orgType, country, role: "admin" },
      });
    } catch (metaErr) {
      console.warn("Metadata update failed:", metaErr);
    }

    // @ts-expect-error -- see above
    const finalUserId = clerkUserId || window.Clerk?.user?.id || null;

    if (!finalUserId) {
      setError(
        "Your account was created, but we couldn't read its user id to finish " +
          "setting up your organisation. Please contact support and quote org id " +
          `${orgId}.`
      );
      return;
    }

    const payload: ProvisionPayload = {
      clerk_org_id: orgId,
      org_name: finalOrgName,
      admin_email: email,
      clerk_user_id: finalUserId,
    };

    // Gap 350: the sandbox claim runs here, BEFORE provisioning -- see
    // claimSandboxWorkspace()'s doc comment for why the order is load-bearing.
    // It never throws and returns NO_CLAIM when there is no sandbox key in this
    // browser, which is every ordinary signup.
    const claim = await claimSandboxWorkspace(payload);
    setSandboxClaim(claim);

    try {
      const result = await provisionTenant(payload);
      // Gap 342 fix: show the key before navigating away instead of routing
      // straight to /login -- once this page unmounts the raw key is gone for
      // good, same as every other "shown once" credential in this app.
      //
      // Gap 350: after a successful claim, `result.api_key` is null by design
      // -- the tenant already carries this clerk_org_id, so provisioning
      // early-returns is_new=false and mints nothing. The claim's own key is
      // the live one, so it is what gets revealed.
      const revealKey = result.api_key || claim.apiKey;
      if (revealKey) {
        setProvisionedApiKey(revealKey);
        return;
      }
    } catch (provisionErr: any) {
      // Gap 133: blocking. Redirecting to /login on a failed provision is
      // what made this invisible -- the user reached a working-looking app
      // whose data lived in an unrelated tenant (or nowhere).
      console.error("Tenant provisioning failed:", provisionErr);
      // Only offer Retry when retrying could actually succeed. A 409 is
      // terminal (see isTerminalProvisionFailure), so leave pendingProvision
      // null and the Retry button unrendered.
      if (!isTerminalProvisionFailure(provisionErr)) {
        setPendingProvision(payload);
      }
      setError(provisionFailureMessage(provisionErr, orgId));
      return;
    }

    router.push("/login");
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;
    if (password !== confirm) { setError("Passwords do not match"); return; }

    setLoading(true);
    setError(null);
    setPendingProvision(null);
    try {
      const result = await signUp.create({
        emailAddress: email,
        password,
        unsafeMetadata: { orgType, country, role: "admin" },
      });

      const finalOrgName = orgName.trim() || `${email.split("@")[0]}'s Org`;

      if (result.status === "complete") {
        await completeSignupAndProvision(result.createdUserId || "", result.createdSessionId || "", finalOrgName);
      } else if (result.status === "missing_requirements") {
        await signUp.prepareEmailAddressVerification({ strategy: "email_code" });
        setNeedsVerification(true);
      } else {
        setError("Account created! Please check your Clerk dashboard settings to disable email verification for demo mode.");
      }
    } catch (err: any) {
      setError(err?.errors?.[0]?.longMessage || err?.message || "Signup failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded || !verificationCode) return;

    setLoading(true);
    setError(null);
    try {
      const result = await signUp.attemptEmailAddressVerification({ code: verificationCode });
      const finalOrgName = orgName.trim() || `${email.split("@")[0]}'s Org`;

      if (result.status === "complete") {
        await completeSignupAndProvision(result.createdUserId || "", result.createdSessionId || "", finalOrgName);
      } else {
        setError(`Verification status: ${result.status}. Please check the code and try again.`);
      }
    } catch (err: any) {
      setError(err?.errors?.[0]?.longMessage || err?.message || "Verification failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleBackToSignup = () => {
    setNeedsVerification(false);
    setVerificationCode("");
    setError(null);
  };

  /**
   * Gap 133: retry only the backend call. The Clerk user, the Clerk
   * Organisation and the active session all already exist at this point, so
   * re-running sign-up would fail on a duplicate email; the only thing that
   * failed is POST /auth/provision, and that endpoint is idempotent on
   * clerk_org_id.
   */
  const handleRetryProvision = async () => {
    if (!pendingProvision) return;
    setRetrying(true);
    setError(null);
    try {
      // Gap 350: retry the claim too, but only when the first attempt did not
      // already succeed -- a claimed sandbox is single-winner and a second
      // attempt would only ever 409. When the first attempt did succeed,
      // `sandboxClaim.apiKey` still holds the key that claim minted, so the
      // reveal below can surface it even though provisioning is what failed.
      const claim = sandboxClaim.claimed
        ? sandboxClaim
        : await claimSandboxWorkspace(pendingProvision);
      if (!sandboxClaim.claimed) setSandboxClaim(claim);

      const result = await provisionTenant(pendingProvision);
      setPendingProvision(null);
      const revealKey = result.api_key || claim.apiKey;
      if (revealKey) {
        setProvisionedApiKey(revealKey);
        return;
      }
      router.push("/login");
    } catch (retryErr: any) {
      console.error("Tenant provisioning retry failed:", retryErr);
      const orgId = pendingProvision.clerk_org_id;
      // A retry that comes back 409 has become terminal -- typically the first
      // attempt actually landed. Drop pendingProvision so the Retry button
      // disappears rather than inviting an endless 409 loop.
      if (isTerminalProvisionFailure(retryErr)) {
        setPendingProvision(null);
      }
      setError(provisionFailureMessage(retryErr, orgId));
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <div style={S.root}>
      <div style={S.orbTL} />
      <div style={S.orbBR} />

      <div style={S.brandPanel}>
        <div style={S.logoRow}>
          <div style={S.logoIcon}>I</div>
          <span style={S.logoText}>InvoiceAI</span>
        </div>
        <h1 style={S.headline}>
          Automate your <span style={S.headlineAccent}>invoice workflow</span> end-to-end.
        </h1>
        <p style={S.subtext}>
          Set up your organisation in minutes and unlock AI-powered invoice extraction, real-time approval flows, and multi-tenant access control.
        </p>
        <div style={S.featureList}>
          {FEATURES.map((f) => (
            <div key={f.title} style={S.featureItem}>
              <div style={S.featureDot}>{f.icon}</div>
              <div>
                <div style={S.featureTitle}>{f.title}</div>
                <div style={S.featureDesc}>{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={S.vDivider} />

      <div style={S.formPanel}>
        <div style={S.card}>
          {provisionedApiKey ? (
            <>
              <div style={S.cardHeader}>
                {/* Gap 350: a claimed signup is a materially different event
                    from a fresh one -- the visitor's trial workspace was
                    promoted rather than a new empty one created, and the key
                    below is the replacement that revoked their inv_test_ one in
                    the same transaction. Saying so is the difference between
                    "here is a key" and "your trial is still here". */}
                <div style={S.badge}>
                  {sandboxClaim.claimed ? "✦ Sandbox workspace kept" : "✦ Organisation ready"}
                </div>
                <h2 style={S.cardTitle}>Your API key</h2>
                <p style={S.cardSubtitle}>
                  {sandboxClaim.claimed
                    ? "Your sandbox workspace has been moved into this organisation — the invoices and chats you tried are still there. Your old inv_test_ key has been replaced by the one below."
                    : "For connecting your own systems (Settings → Workflows can walk you through this later)."}
                  {" "}This is the only time it&apos;s shown — copy it now.
                </p>
              </div>

              <div
                style={{
                  ...S.input,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "10px",
                  padding: "13px 14px",
                  fontFamily: "ui-monospace, monospace",
                  fontSize: "13px",
                  wordBreak: "break-all",
                  userSelect: "all",
                }}
              >
                <span>{provisionedApiKey}</span>
              </div>

              <button
                type="button"
                onClick={() => {
                  navigator.clipboard?.writeText(provisionedApiKey).then(() => {
                    setKeyCopied(true);
                    setTimeout(() => setKeyCopied(false), 2000);
                  });
                }}
                style={{ ...S.retryBtn, marginTop: "10px", color: T.textPrimary, background: "rgba(59,130,246,0.14)", border: "1px solid rgba(59,130,246,0.35)" }}
              >
                {keyCopied ? "✓ Copied" : "📋 Copy key"}
              </button>

              <button
                type="button"
                onClick={() => router.push("/login")}
                style={{ ...S.btn }}
              >
                Continue to dashboard →
              </button>
            </>
          ) : !needsVerification ? (
            <>
              <div style={S.cardHeader}>
                <div style={S.badge}>✦ Free 14-day trial</div>
                <h2 style={S.cardTitle}>Create your organisation</h2>
                <p style={S.cardSubtitle}>Fill in the details below to get started</p>
              </div>

              <form onSubmit={handleSignup}>
                <div style={S.sectionLabel}>Organisation</div>
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  <div style={S.inputWrap}>
                    <span style={S.inputIcon}>🏢</span>
                    <input
                      type="text"
                      placeholder="Organisation name (optional)"
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      onFocus={() => setFocused("orgName")}
                      onBlur={() => setFocused(null)}
                      style={inputStyle("orgName")}
                    />
                  </div>
                  <div style={S.grid2}>
                    <div style={S.inputWrap}>
                      <span style={S.inputIcon}>📁</span>
                      <select
                        value={orgType}
                        onChange={(e) => setOrgType(e.target.value)}
                        onFocus={() => setFocused("orgType")}
                        onBlur={() => setFocused(null)}
                        style={selectStyle("orgType")}
                        required
                      >
                        <option value="">Org type</option>
                        {ORG_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                    <div style={S.inputWrap}>
                      <span style={S.inputIcon}>🌍</span>
                      <select
                        value={country}
                        onChange={(e) => setCountry(e.target.value)}
                        onFocus={() => setFocused("country")}
                        onBlur={() => setFocused(null)}
                        style={selectStyle("country")}
                        required
                      >
                        <option value="">Country</option>
                        {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  </div>
                </div>

                <div style={S.sectionLabel}>Account</div>
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  <div style={S.inputWrap}>
                    <span style={S.inputIcon}>✉️</span>
                    <input
                      type="email"
                      placeholder="Work email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      onFocus={() => setFocused("email")}
                      onBlur={() => setFocused(null)}
                      style={inputStyle("email")}
                      required
                    />
                  </div>
                  <div style={S.grid2}>
                    <div style={S.inputWrap}>
                      <span style={S.inputIcon}>🔒</span>
                      <input
                        type={showPassword ? "text" : "password"}
                        placeholder="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onFocus={() => setFocused("password")}
                        onBlur={() => setFocused(null)}
                        style={{ ...inputStyle("password"), paddingRight: "36px" }}
                        required
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        style={{
                          position: "absolute",
                          right: "10px",
                          top: "50%",
                          transform: "translateY(-50%)",
                          background: "none",
                          border: "none",
                          color: T.textDim,
                          cursor: "pointer",
                          padding: "4px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          transition: "color 0.2s",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.color = T.textPrimary)}
                        onMouseLeave={(e) => (e.currentTarget.style.color = T.textDim)}
                        aria-label={showPassword ? "Hide password" : "Show password"}
                        tabIndex={0}
                      >
                        {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                    <div style={S.inputWrap}>
                      <span style={S.inputIcon}>🔑</span>
                      <input
                        type={showConfirm ? "text" : "password"}
                        placeholder="Confirm"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        onFocus={() => setFocused("confirm")}
                        onBlur={() => setFocused(null)}
                        style={{ ...inputStyle("confirm"), paddingRight: "36px" }}
                        required
                      />
                      <button
                        type="button"
                        onClick={() => setShowConfirm(!showConfirm)}
                        style={{
                          position: "absolute",
                          right: "10px",
                          top: "50%",
                          transform: "translateY(-50%)",
                          background: "none",
                          border: "none",
                          color: T.textDim,
                          cursor: "pointer",
                          padding: "4px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          transition: "color 0.2s",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.color = T.textPrimary)}
                        onMouseLeave={(e) => (e.currentTarget.style.color = T.textDim)}
                        aria-label={showConfirm ? "Hide confirm password" : "Show confirm password"}
                        tabIndex={0}
                      >
                        {showConfirm ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </div>
                </div>

                {error && (
                  <div style={S.errorBox}>
                    <span>⚠️</span>
                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                      <span>{error}</span>
                      {/* Gap 133: only the backend provision call is retried -- the
                          Clerk account and organisation already exist by now. */}
                      {pendingProvision && (
                        <button
                          type="button"
                          onClick={handleRetryProvision}
                          disabled={retrying}
                          style={{ ...S.retryBtn, opacity: retrying ? 0.7 : 1 }}
                        >
                          {retrying ? "⏳ Retrying…" : "↻ Retry setup"}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Gap 9 (real-key verification): this Clerk instance has Smart
                    CAPTCHA / bot sign-up protection enabled. Without this element,
                    Clerk can't mount the managed CAPTCHA challenge and silently
                    falls back to an invisible Cloudflare Turnstile challenge that
                    also fails in this environment -- signUp.create() then hangs
                    forever with no error ever surfacing to the catch block. Found
                    by actually running signup against real Clerk keys, not
                    visible with placeholder keys since Clerk never attempts a
                    real challenge against those. */}
                <div id="clerk-captcha" />

                <button type="submit" disabled={loading} style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}>
                  {loading ? "⏳ Creating organisation…" : "🚀 Create Organisation"}
                </button>
              </form>
            </>
          ) : (
            <>
              <div style={S.cardHeader}>
                <div style={S.badge}>✦ Verify email</div>
                <h2 style={S.cardTitle}>Verify your email</h2>
                <p style={S.cardSubtitle}>Enter the code sent to <strong>{email}</strong></p>
              </div>

              <form onSubmit={handleVerifyEmail}>
                <div style={S.sectionLabel}>Verification Code</div>
                <div style={S.inputWrap}>
                  <span style={S.inputIcon}>🔑</span>
                  <input
                    type="text"
                    placeholder="Enter 6-digit code"
                    value={verificationCode}
                    onChange={(e) => setVerificationCode(e.target.value)}
                    onFocus={() => setFocused("verification")}
                    onBlur={() => setFocused(null)}
                    style={inputStyle("verification")}
                    required
                    autoFocus
                  />
                </div>

                {error && (
                  <div style={S.errorBox}>
                    <span>⚠️</span><span>{error}</span>
                  </div>
                )}

                <button type="submit" disabled={loading} style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}>
                  {loading ? "⏳ Verifying…" : "✓ Verify & Create Organisation"}
                </button>

                <button
                  type="button"
                  onClick={handleBackToSignup}
                  style={{ background: "none", border: "none", color: "gray", fontSize: "13px", marginTop: "12px", width: "100%", cursor: "pointer" }}
                >
                  ← Back to Sign Up
                </button>
              </form>
            </>
          )}

          <div style={S.loginRow}>
            Already have an account? <a href="/login" style={S.loginLink}>Log in →</a>
          </div>
        </div>
      </div>
    </div>
  </div>
  );
}
