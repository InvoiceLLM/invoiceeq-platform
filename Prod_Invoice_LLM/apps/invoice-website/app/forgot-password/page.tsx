"use client";

import React, { useState } from "react";
import { useSignIn } from "@clerk/nextjs";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { Header } from "@/components/marketing/Header";

/* Design tokens (match login/signup) */
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
  brandPanel: { flex: "1 1 45%", display: "flex", flexDirection: "column", justifyContent: "center", padding: "64px 56px", position: "relative", zIndex: 1 },
  logoRow: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "56px" },
  logoIcon: { width: "40px", height: "40px", borderRadius: "10px", background: "linear-gradient(135deg, #10B981 0%, #3B82F6 100%)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "20px", fontWeight: 700, color: "#fff", flexShrink: 0 },
  logoText: { fontSize: "20px", fontWeight: 700, letterSpacing: "-0.3px", background: "linear-gradient(90deg, #E2E8F0 0%, #94A3B8 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  headline: { fontSize: "40px", fontWeight: 800, lineHeight: 1.15, letterSpacing: "-1px", marginBottom: "20px", color: T.textPrimary },
  headlineAccent: { background: "linear-gradient(90deg, #3B82F6 0%, #10B981 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  subtext: { fontSize: "16px", color: T.textMuted, lineHeight: 1.65, maxWidth: "380px", marginBottom: "48px" },
  vDivider: { width: "1px", flexShrink: 0, zIndex: 1, background: "linear-gradient(to bottom, transparent, #222D3D 20%, #222D3D 80%, transparent)" },
  formPanel: { flex: "1 1 55%", display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 48px", zIndex: 1 },
  card: { width: "100%", maxWidth: "420px", background: T.panel, backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)", border: `1px solid ${T.border}`, borderRadius: "20px", padding: "40px", boxShadow: "0 24px 64px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)" },
  cardHeader: { marginBottom: "28px", textAlign: "center" },
  avatarIcon: { width: "56px", height: "56px", borderRadius: "14px", background: "linear-gradient(135deg, rgba(59,130,246,0.15) 0%, rgba(16,185,129,0.15) 100%)", border: "1px solid rgba(59,130,246,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "26px", margin: "0 auto 16px" },
  cardTitle: { fontSize: "26px", fontWeight: 700, color: T.textPrimary, letterSpacing: "-0.5px", marginBottom: "6px" },
  cardSubtitle: { fontSize: "14px", color: T.textDim },
  sectionLabel: { fontSize: "11px", fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: "#475569", marginBottom: "10px", marginTop: "4px" },
  inputWrap: { position: "relative", marginBottom: "10px" },
  inputIcon: { position: "absolute", left: "13px", top: "50%", transform: "translateY(-50%)", fontSize: "14px", opacity: 0.5, pointerEvents: "none" },
  input: { width: "100%", boxSizing: "border-box", background: "rgba(15, 20, 30, 0.60)", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "12px 14px 12px 38px", fontSize: "14px", color: T.textPrimary, outline: "none", transition: "border-color 0.2s, box-shadow 0.2s" },
  inputFocusBlue: { borderColor: T.blue, boxShadow: "0 0 0 3px rgba(59,130,246,0.13)" },
  successBox: { display: "flex", alignItems: "flex-start", gap: "8px", background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.25)", borderRadius: "10px", padding: "12px 14px", fontSize: "13px", color: T.green, marginTop: "6px", marginBottom: "6px", lineHeight: 1.5 },
  errorBox: { display: "flex", alignItems: "flex-start", gap: "8px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "10px", padding: "10px 14px", fontSize: "13px", color: T.red, marginTop: "6px", marginBottom: "6px" },
  btn: { width: "100%", background: "linear-gradient(135deg, #3B82F6 0%, #2563EB 100%)", border: "none", borderRadius: "10px", padding: "13px", fontSize: "15px", fontWeight: 600, color: "#fff", cursor: "pointer", marginTop: "20px", letterSpacing: "0.2px", transition: "opacity 0.2s", boxShadow: "0 4px 20px rgba(59,130,246,0.25)" },
  dividerRow: { display: "flex", alignItems: "center", gap: "12px", margin: "20px 0" },
  dividerLine: { flex: 1, height: "1px", background: T.border },
  dividerText: { fontSize: "12px", color: T.textDim, flexShrink: 0 },
  linkRow: { textAlign: "center", marginTop: "20px", fontSize: "13px", color: T.textDim },
  link: { color: T.green, textDecoration: "none", fontWeight: 600 },
};

export default function ForgotPasswordPage() {
  const { isLoaded, signIn } = useSignIn();

  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [step, setStep] = useState<"request" | "verify">("request");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState<string | null>(null);

  const inputStyle = (id: string) => ({ ...S.input, ...(focused === id ? S.inputFocusBlue : {}) });

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;

    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      await signIn.create({
        strategy: "reset_password_email_code",
        identifier: email,
      });

      setSuccess("✓ Password reset code sent! Check your email and enter the code below.");
      setStep("verify");
    } catch (err: any) {
      setError(
        err?.errors?.[0]?.longMessage ||
          err?.message ||
          "Could not send reset code. Please check the email address and try again."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;

    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await signIn.attemptFirstFactor({
        strategy: "reset_password_email_code",
        code,
        password: newPassword,
      });

      if (result.status === "complete") {
        setSuccess("✓ Password reset complete! Redirecting to login...");
        setTimeout(() => {
          window.location.href = "/login";
        }, 2000);
      } else {
        setError(`Unexpected status: ${result.status}. Please try again or contact support.`);
        setLoading(false);
      }
    } catch (err: any) {
      setError(
        err?.errors?.[0]?.longMessage ||
          err?.message ||
          "Invalid code or password. Please try again."
      );
      setLoading(false);
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
            Reset your <span style={S.headlineAccent}>password.</span>
          </h1>
          <p style={S.subtext}>
            Enter your email address and we&apos;ll send you a verification code to reset your password.
          </p>
        </div>

        <div style={S.vDivider} />

        <div style={S.formPanel}>
          <div style={S.card}>
            <div style={S.cardHeader}>
              <div style={S.avatarIcon}>🔑</div>
              <h2 style={S.cardTitle}>Password Reset</h2>
              <p style={S.cardSubtitle}>
                {step === "request" ? "Enter your email to continue" : "Enter code and new password"}
              </p>
            </div>

            {step === "request" ? (
              <form onSubmit={handleRequestReset}>
                <div style={S.sectionLabel}>Email Address</div>

                <div style={S.inputWrap}>
                  <span style={S.inputIcon}>✉️</span>
                  <input
                    type="email"
                    name="email"
                    autoComplete="email"
                    inputMode="email"
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

                {error && (
                  <div style={S.errorBox}>
                    <span>⚠️</span>
                    <span>{error}</span>
                  </div>
                )}

                {success && (
                  <div style={S.successBox}>
                    <span>✉️</span>
                    <span>{success}</span>
                  </div>
                )}

                <button type="submit" disabled={loading} style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}>
                  {loading ? "⏳ Sending code…" : "→ Send Reset Code"}
                </button>
              </form>
            ) : (
              <form onSubmit={handleResetPassword}>
                <div style={S.sectionLabel}>Verification Code</div>
                <div style={{ fontSize: "13px", color: T.textMuted, marginBottom: "12px" }}>
                  We sent a 6-digit code to <strong>{email}</strong>.
                </div>

                <div style={S.inputWrap}>
                  <span style={S.inputIcon}>🔑</span>
                  {/* Gap 161: without an explicit autoComplete the browser treated this
                      (the form's first text input) as the identifier field and filled it
                      with the saved email. "one-time-code" pins it to the real purpose. */}
                  <input
                    type="text"
                    name="reset-code"
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    placeholder="Enter 6-digit code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    onFocus={() => setFocused("code")}
                    onBlur={() => setFocused(null)}
                    style={inputStyle("code")}
                    required
                    autoFocus
                  />
                </div>

                <div style={S.sectionLabel}>New Password</div>

                <div style={S.inputWrap}>
                  <span style={S.inputIcon}>🔒</span>
                  <input
                    type={showNewPassword ? "text" : "password"}
                    name="new-password"
                    autoComplete="new-password"
                    placeholder="New password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    onFocus={() => setFocused("password")}
                    onBlur={() => setFocused(null)}
                    style={{ ...inputStyle("password"), paddingRight: "40px" }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                    style={{
                      position: "absolute",
                      right: "12px",
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
                    aria-label={showNewPassword ? "Hide password" : "Show password"}
                    tabIndex={0}
                  >
                    {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>

                {error && (
                  <div style={S.errorBox}>
                    <span>⚠️</span>
                    <span>{error}</span>
                  </div>
                )}

                {success && (
                  <div style={S.successBox}>
                    <span>✓</span>
                    <span>{success}</span>
                  </div>
                )}

                <button type="submit" disabled={loading} style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}>
                  {loading ? "⏳ Resetting password…" : "✓ Reset Password"}
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setStep("request");
                    setCode("");
                    setNewPassword("");
                    setError(null);
                    setSuccess(null);
                  }}
                  style={{
                    background: "none",
                    border: "none",
                    color: T.textDim,
                    fontSize: "13px",
                    marginTop: "12px",
                    width: "100%",
                    cursor: "pointer",
                  }}
                >
                  ← Didn&apos;t receive a code?
                </button>
              </form>
            )}

            <div style={S.dividerRow}>
              <div style={S.dividerLine} />
              <span style={S.dividerText}>Remembered your password?</span>
              <div style={S.dividerLine} />
            </div>

            <div style={S.linkRow}>
              <Link href="/login" style={S.link}>
                ← Back to Login
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
