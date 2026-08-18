"use client";

import React, { useState } from "react";
import { useSignUp } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { Header } from "@/components/marketing/Header";

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

async function provisionTenant(payload: ProvisionPayload): Promise<void> {
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

  if (!response.ok) {
    const data = await response.json().catch(() => ({} as { detail?: string }));
    throw new ProvisionError(
      data?.detail || `provisioning failed with HTTP ${response.status}`,
      response.status
    );
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

    try {
      await provisionTenant(payload);
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
      await provisionTenant(pendingProvision);
      setPendingProvision(null);
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
          {!needsVerification ? (
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
                        type="password"
                        placeholder="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onFocus={() => setFocused("password")}
                        onBlur={() => setFocused(null)}
                        style={inputStyle("password")}
                        required
                      />
                    </div>
                    <div style={S.inputWrap}>
                      <span style={S.inputIcon}>🔑</span>
                      <input
                        type="password"
                        placeholder="Confirm"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        onFocus={() => setFocused("confirm")}
                        onBlur={() => setFocused(null)}
                        style={inputStyle("confirm")}
                        required
                      />
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
