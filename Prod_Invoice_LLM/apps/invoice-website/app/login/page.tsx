"use client";

import React, { useState } from "react";
import { useSignIn, useClerk, useUser } from "@clerk/nextjs";
import { Eye, EyeOff } from "lucide-react";
import { appHref } from "../../lib/billingPlans";
import { Header } from "@/components/marketing/Header";

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
  orbTL: { position: "absolute", top: "-120px", left: "-120px", width: "520px", height: "520px", borderRadius: "50%", background: "radial-gradient(circle, rgba(59,130,246,0.12) 0%, transparent 70%)", pointerEvents: "none", zIndex: 0 },
  orbBR: { position: "absolute", bottom: "-150px", right: "-100px", width: "620px", height: "620px", borderRadius: "50%", background: "radial-gradient(circle, rgba(16,185,129,0.09) 0%, transparent 70%)", pointerEvents: "none", zIndex: 0 },
  brandPanel: { flex: "1 1 45%", display: "flex", flexDirection: "column", justifyContent: "center", position: "relative", zIndex: 1 },
  logoRow: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "32px" },
  logoIcon: { width: "40px", height: "40px", borderRadius: "10px", background: "linear-gradient(135deg, #10B981 0%, #3B82F6 100%)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "20px", fontWeight: 700, color: "#fff", flexShrink: 0 },
  logoText: { fontSize: "20px", fontWeight: 700, letterSpacing: "-0.3px", background: "linear-gradient(90deg, #E2E8F0 0%, #94A3B8 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  headline: { fontSize: "36px", fontWeight: 800, lineHeight: 1.15, letterSpacing: "-1px", marginBottom: "16px", color: T.textPrimary },
  headlineAccent: { background: "linear-gradient(90deg, #3B82F6 0%, #10B981 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  subtext: { fontSize: "15px", color: T.textMuted, lineHeight: 1.6, maxWidth: "380px", marginBottom: "32px" },
  statRow: { display: "flex", gap: "24px", flexWrap: "wrap" },
  stat: { display: "flex", flexDirection: "column", gap: "4px" },
  statNum: { fontSize: "24px", fontWeight: 800, letterSpacing: "-1px", background: "linear-gradient(90deg, #10B981 0%, #3B82F6 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  statLabel: { fontSize: "12px", color: T.textDim },
  vDivider: { width: "1px", flexShrink: 0, zIndex: 1, background: "linear-gradient(to bottom, transparent, #222D3D 20%, #222D3D 80%, transparent)" },
  formPanel: { flex: "1 1 55%", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1 },
  card: { width: "100%", maxWidth: "420px", background: T.panel, backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)", border: `1px solid ${T.border}`, borderRadius: "20px", boxShadow: "0 24px 64px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)" },
  cardHeader: { marginBottom: "24px", textAlign: "center" },
  avatarIcon: { width: "52px", height: "52px", borderRadius: "14px", background: "linear-gradient(135deg, rgba(59,130,246,0.15) 0%, rgba(16,185,129,0.15) 100%)", border: "1px solid rgba(59,130,246,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "24px", margin: "0 auto 12px" },
  cardTitle: { fontSize: "24px", fontWeight: 700, color: T.textPrimary, letterSpacing: "-0.5px", marginBottom: "4px" },
  cardSubtitle: { fontSize: "13px", color: T.textDim },
  sectionLabel: { fontSize: "11px", fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: "#475569", marginBottom: "8px", marginTop: "4px" },
  inputWrap: { position: "relative", marginBottom: "10px" },
  inputIcon: { position: "absolute", left: "13px", top: "50%", transform: "translateY(-50%)", fontSize: "14px", opacity: 0.5, pointerEvents: "none" },
  input: { width: "100%", boxSizing: "border-box", background: "rgba(15, 20, 30, 0.60)", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "12px 42px 12px 38px", fontSize: "14px", color: T.textPrimary, outline: "none", transition: "border-color 0.2s, box-shadow 0.2s" },
  inputFocusBlue: { borderColor: T.blue, boxShadow: "0 0 0 3px rgba(59,130,246,0.13)" },
  eyeBtn: { position: "absolute", right: "12px", top: "50%", transform: "translateY(-50%)", background: "transparent", border: "none", color: "#64748B", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", padding: "4px", borderRadius: "4px" },
  errorBox: { display: "flex", alignItems: "flex-start", gap: "8px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "10px", padding: "10px 14px", fontSize: "13px", color: T.red, marginTop: "6px", marginBottom: "6px" },
  btn: { width: "100%", background: "linear-gradient(135deg, #3B82F6 0%, #2563EB 100%)", border: "none", borderRadius: "10px", padding: "13px", fontSize: "15px", fontWeight: 600, color: "#fff", cursor: "pointer", marginTop: "16px", letterSpacing: "0.2px", transition: "opacity 0.2s", boxShadow: "0 4px 20px rgba(59,130,246,0.25)" },
  sessionBanner: { display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: "10px", padding: "10px 14px", marginBottom: "16px", fontSize: "12px", color: T.textPrimary },
};

const STATS = [
  { num: "10K+", label: "Invoices processed" },
  { num: "200+", label: "Organisations" },
  { num: "99.9%", label: "Uptime SLA" },
];

// invoice-fe currently has one dashboard for all authenticated users, no
// distinct admin/user route split yet -- both roles land on /dashboard for
// now. Revisit if/when that split gets built.

export default function LoginPage() {
  const { isLoaded, signIn, setActive } = useSignIn();
  const { signOut } = useClerk();
  const { user: currentUser } = useUser();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [needsOtp, setNeedsOtp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState<string | null>(null);

  const inputStyle = (id: string) => ({ ...S.input, ...(focused === id ? S.inputFocusBlue : {}) });

  // Gap 173: used to gate sign-in on a role picked in the UI, checked against
  // the client-writable unsafeMetadata.role -- neither the gate nor the
  // picker had any bearing on what the user could actually do once signed
  // in, since useAuth()/Sidebar.tsx already resolve real screens from the
  // backend's GET /auth/me (now backed by Clerk's org_role, not this field).
  // Removed the picker entirely: sign in, then show whatever the resolved
  // role actually grants -- no self-reported role to mismatch against.
  const processSignIn = async (activeSignIn: any) => {
    if (activeSignIn.status === "complete" || activeSignIn.createdSessionId) {
      const session = activeSignIn.createdSessionId;
      // setActive is typed as possibly undefined until Clerk finishes loading.
      if (session && setActive) await setActive({ session });

      try {
        // Gap 157: a fixed 200ms wait was a guess at how long Clerk's client
        // takes to populate session.user/organizationMemberships after
        // setActive({session}) -- not a guarantee. Poll the real state
        // instead, up to 2s, checking every 50ms, for either metadata.orgId
        // (set synchronously at signup, available as soon as the user object
        // loads) or a populated organizationMemberships array.
        // @ts-expect-error -- window.Clerk is the runtime Clerk client, not typed here
        let clerkUser = window.Clerk?.session?.user || window.Clerk?.user;
        let metadata = clerkUser?.unsafeMetadata || {};
        let memberships = clerkUser?.organizationMemberships || [];
        const deadline = Date.now() + 2000;
        while (!metadata.orgId && memberships.length === 0 && Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 50));
          // @ts-expect-error -- see above
          clerkUser = window.Clerk?.session?.user || window.Clerk?.user;
          metadata = clerkUser?.unsafeMetadata || {};
          memberships = clerkUser?.organizationMemberships || [];
        }
        // Users belong to at most one org in this app's current model (the
        // creator's own org, or none for a Settings-added user) -- prefer
        // the org they created, else whichever single membership exists.
        const selectedOrgId: string | null = metadata.orgId || memberships[0]?.organization?.id || null;

        if (selectedOrgId) {
          // @ts-expect-error -- see above
          await window.Clerk.setActive({ organization: selectedOrgId });
        }
      } catch (orgErr) {
        console.error("Could not set active org:", orgErr);
      }

      window.location.href = appHref("/dashboard");
    } else {
      setError(`Sign-in status: ${activeSignIn.status}. Re-creating the user from Admin Console will fix this.`);
      setLoading(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;

    setLoading(true);
    setError(null);

    try {
      // @ts-expect-error -- window.Clerk is the runtime Clerk client, not typed here
      if (currentUser || window.Clerk?.session) {
        await signOut();
      }

      const result = await signIn.create({ identifier: email, password });

      if (result.status === "needs_second_factor") {
        try {
          // @ts-expect-error -- Clerk types only allow "phone_code"/"totp" as a
          // second factor. "email_code" is intentional here and the call is
          // guarded by the catch below; changing the strategy would alter the
          // auth flow, so the behaviour is left as-is. See FIXME in docs.
          await result.prepareSecondFactor({ strategy: "email_code" });
          // OTP copy lives on the verify form -- do not stash it in `error`
          // or "← Back to Login" leaves a red banner on the password form.
          setNeedsOtp(true);
          setError(null);
          setLoading(false);
          return;
        } catch {
          setError("⚠️ This unverified account requires email verification. Please create a new account or re-create from Admin Console.");
          setLoading(false);
          return;
        }
      }

      await processSignIn(result);
    } catch (err: any) {
      if (err?.errors?.[0]?.code === "form_identifier_not_found") {
        setError("Couldn't find your account. Please check the email address or create an account.");
      } else if (err?.errors?.[0]?.code === "session_exists" || err?.message?.includes("already signed in")) {
        try {
          await signOut();
          const retryResult = await signIn.create({ identifier: email, password });
          await processSignIn(retryResult);
          return;
        } catch (retryErr: any) {
          setError(retryErr?.errors?.[0]?.longMessage || retryErr?.message || "Invalid email or password.");
        }
      } else {
        setError(err?.errors?.[0]?.longMessage || err?.message || "Invalid email or password.");
      }
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded || !otpCode) return;

    setLoading(true);
    setError(null);
    try {
      const result = await signIn.attemptSecondFactor({
        strategy: "email_code",
        code: otpCode,
      });

      if (result.status === "complete") {
        await processSignIn(result);
      } else {
        setError(`Verification status: ${result.status}. Please check the code and try again.`);
        setLoading(false);
      }
    } catch (err: any) {
      setError(err?.errors?.[0]?.longMessage || err?.message || "Invalid verification code. Please try again.");
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <div style={S.root} className="flex flex-col lg:flex-row">
      <div style={S.orbTL} />
      <div style={S.orbBR} />

      <div style={S.brandPanel} className="hidden lg:flex p-10 lg:p-14">
        <div style={S.logoRow}>
          <div style={S.logoIcon}>I</div>
          <span style={S.logoText}>InvoiceAI</span>
        </div>
        <h1 style={S.headline}>
          Welcome back to <span style={S.headlineAccent}>your workspace.</span>
        </h1>
        <p style={S.subtext}>
          Sign in to access your organisation&apos;s AI-powered invoice processing dashboard, approval workflows, and real-time analytics.
        </p>
        <div style={S.statRow}>
          {STATS.map((s) => (
            <div key={s.label} style={S.stat}>
              <span style={S.statNum}>{s.num}</span>
              <span style={S.statLabel}>{s.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={S.vDivider} className="hidden lg:block" />

      <div style={S.formPanel} className="w-full p-4 sm:p-8 lg:p-12">
        <div style={S.card} className="w-full max-w-[420px] p-6 sm:p-10">
          {currentUser && (
            <div style={S.sessionBanner}>
              <span>Signed in as <strong>{currentUser.primaryEmailAddress?.emailAddress || "active user"}</strong></span>
              <button
                type="button"
                onClick={async () => { await signOut(); window.location.href = "/login"; }}
                style={{ background: "none", border: "none", color: T.red, cursor: "pointer", fontWeight: 600, fontSize: "12px" }}
              >
                Sign out
              </button>
            </div>
          )}

          <div style={S.cardHeader}>
            <div style={S.avatarIcon}>🔐</div>
            <h2 style={S.cardTitle}>Welcome back</h2>
            <p style={S.cardSubtitle}>Sign in to your workspace</p>
          </div>

          {!needsOtp ? (
            <form onSubmit={handleLogin}>
              <div style={S.sectionLabel}>Credentials</div>

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
                  autoFocus
                />
              </div>

              <div style={S.inputWrap}>
                <span style={S.inputIcon}>🔒</span>
                <input
                  type={showPassword ? "text" : "password"}
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onFocus={() => setFocused("password")}
                  onBlur={() => setFocused(null)}
                  style={inputStyle("password")}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  style={S.eyeBtn}
                  title={showPassword ? "Hide password" : "Show password"}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>

              <div style={{ textAlign: "right", marginTop: "6px", marginBottom: "8px" }}>
                <a
                  href="/forgot-password"
                  style={{ fontSize: "12px", color: T.textDim, textDecoration: "none", transition: "color 0.2s" }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = T.blue)}
                  onMouseLeave={(e) => (e.currentTarget.style.color = T.textDim)}
                >
                  Forgot password?
                </a>
              </div>

              {error && (
                <div style={S.errorBox}>
                  <span>⚠️</span><span>{error}</span>
                </div>
              )}

              <button type="submit" disabled={loading} style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}>
                {loading ? "⏳ Signing in…" : "→ Sign In"}
              </button>

              <p style={{ textAlign: "center", marginTop: "18px", fontSize: "13px", color: T.textDim }}>
                New here?{" "}
                <a href="/signup" style={{ color: T.green, textDecoration: "none", fontWeight: 600 }}>
                  Create an organisation →
                </a>
              </p>
            </form>
          ) : (
            <form onSubmit={handleVerifyOtp}>
              <div style={S.sectionLabel}>Verification Code</div>
              <div style={{ fontSize: "13px", color: T.textMuted, marginBottom: "12px" }}>
                We sent a 6-digit code to <strong>{email}</strong>.
              </div>

              <div style={S.inputWrap}>
                <span style={S.inputIcon}>🔑</span>
                <input
                  type="text"
                  placeholder="Enter 6-digit code"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value)}
                  onFocus={() => setFocused("otp")}
                  onBlur={() => setFocused(null)}
                  style={inputStyle("otp")}
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
                {loading ? "⏳ Verifying…" : "✓ Verify & Sign In"}
              </button>

               <button
                type="button"
                onClick={async () => {
                  // Flipping needsOtp alone left otpCode + a leftover banner and
                  // kept Clerk mid second-factor -- password form then looked /
                  // behaved odd. Soft-reset UI state; next Sign In calls
                  // signIn.create() again and starts a fresh attempt.
                  try {
                    await signOut();
                  } catch (signOutErr) {
                    console.error("Clerk sign-out failed on back-to-login:", signOutErr);
                  }
                  setNeedsOtp(false);
                  setOtpCode("");
                  setError(null);
                  setLoading(false);
                }}
                style={{ background: "none", border: "none", color: T.textDim, fontSize: "13px", marginTop: "12px", width: "100%", cursor: "pointer" }}
              >
                ← Back to Login
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  </div>
  );
}
