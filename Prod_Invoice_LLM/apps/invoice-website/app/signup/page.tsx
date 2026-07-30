"use client";

import React, { useState } from "react";
import { useSignUp } from "@clerk/nextjs";
import { useRouter } from "next/navigation";

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
  root: { minHeight: "100vh", background: T.bg, display: "flex", fontFamily: T.font, color: T.textPrimary, overflow: "hidden", position: "relative" },
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

  const inputStyle = (id: string) => ({ ...S.input, ...(focused === id ? S.inputFocus : {}) });
  const selectStyle = (id: string) => ({ ...S.select, ...(focused === id ? S.inputFocus : {}) });

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;
    if (password !== confirm) { setError("Passwords do not match"); return; }

    setLoading(true);
    setError(null);
    try {
      const result = await signUp.create({
        emailAddress: email,
        password,
        unsafeMetadata: { orgType, country, role: "admin,user" },
      });

      if (result.status === "complete") {
        await setActive({ session: result.createdSessionId });

        let orgId: string | null = null;
        try {
          await new Promise((r) => setTimeout(r, 200));
          // @ts-expect-error -- window.Clerk is the runtime Clerk client, not typed here
          const org = await window.Clerk.createOrganization({ name: orgName });
          orgId = org.id;
          // @ts-expect-error -- see above
          await window.Clerk.setActive({ organization: org.id });
        } catch (orgErr) {
          console.warn("Clerk Org creation failed (is Organizations enabled in Clerk Dashboard?)", orgErr);
        }

        try {
          // @ts-expect-error -- see above
          await window.Clerk.user.update({
            unsafeMetadata: { orgId, orgName, orgType, country, role: "admin,user" },
          });
        } catch (metaErr) {
          console.warn("Metadata update failed:", metaErr);
        }

        if (orgId && result.createdUserId) {
          try {
            const provisionResponse = await fetch("/api/auth/provision", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                clerk_org_id: orgId,
                org_name: orgName,
                admin_email: email,
                clerk_user_id: result.createdUserId,
              }),
            });
            if (!provisionResponse.ok) {
              const errorData = await provisionResponse.json().catch(() => ({}));
              console.warn("Tenant provisioning failed:", provisionResponse.status, errorData);
            }
          } catch (provisionErr) {
            console.warn("Backend provision call failed:", provisionErr);
          }
        }

        router.push("/login");
      } else {
        setError("Account created! Please check your Clerk dashboard settings to disable email verification for demo mode.");
      }
    } catch (err: any) {
      setError(err?.errors?.[0]?.longMessage || err?.message || "Signup failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
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
                  placeholder="Organisation name"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  onFocus={() => setFocused("orgName")}
                  onBlur={() => setFocused(null)}
                  style={inputStyle("orgName")}
                  required
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
                <span>{error}</span>
              </div>
            )}

            <button type="submit" disabled={loading} style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}>
              {loading ? "⏳ Creating organisation…" : "🚀 Create Organisation"}
            </button>
          </form>

          <div style={S.loginRow}>
            Already have an account? <a href="/login" style={S.loginLink}>Log in →</a>
          </div>
        </div>
      </div>
    </div>
  );
}
