"use client";

import React, { useState, useRef } from "react";
import Link from "next/link";
import { Header } from "@/components/marketing/Header";
import {
  Mail,
  Copy,
  Check,
  Send,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  Zap,
  Shield,
  Clock,
  Activity,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

const CATEGORIES = [
  { value: "SALES",             label: "Sales & Enterprise Demo" },
  { value: "TECHNICAL_SUPPORT", label: "Technical Support & Integration" },
  { value: "BILLING",           label: "Billing & Subscription" },
  { value: "PARTNERSHIP",       label: "Partnership" },
  { value: "GENERAL",           label: "General Question" },
] as const;

type Urgency = "LOW" | "NORMAL" | "URGENT";

const URGENCY_OPTIONS: { value: Urgency; label: string; description: string; colour: string }[] = [
  { value: "LOW",    label: "Low / Inquiry",    description: "< 24 hours",  colour: "#10B981" },
  { value: "NORMAL", label: "Normal",           description: "< 12 hours",  colour: "#3B82F6" },
  { value: "URGENT", label: "Urgent / Blocker", description: "< 2 hours",   colour: "#EF4444" },
];

const SUPPORT_EMAIL = "Application@infinevocloud.com";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CopyEmailButton() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(SUPPORT_EMAIL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback — execCommand
      const el = document.createElement("textarea");
      el.value = SUPPORT_EMAIL;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      id="copy-support-email-btn"
      onClick={handleCopy}
      className="flex items-center gap-2 text-[#22D3EE] hover:text-white transition-colors duration-200 group"
      aria-label="Copy support email address"
    >
      <span className="text-sm font-mono">{SUPPORT_EMAIL}</span>
      {copied ? (
        <Check className="w-4 h-4 text-[#10B981]" />
      ) : (
        <Copy className="w-4 h-4 opacity-60 group-hover:opacity-100" />
      )}
    </button>
  );
}

function InfoCard({
  icon: Icon,
  title,
  value,
  colour = "#22D3EE",
}: {
  icon: React.ElementType;
  title: string;
  value: React.ReactNode;
  colour?: string;
}) {
  return (
    <div className="flex items-start gap-3 p-4 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)]">
      <div
        className="h-8 w-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
        style={{ background: `${colour}20`, border: `1px solid ${colour}40` }}
      >
        <Icon className="w-4 h-4" style={{ color: colour }} />
      </div>
      <div>
        <p className="text-xs text-[#64748B] mb-0.5">{title}</p>
        <div className="text-sm text-[#E2E8F0]">{value}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ContactPage() {
  // Form state
  const [name, setName]           = useState("");
  const [email, setEmail]         = useState("");
  const [category, setCategory]   = useState("SALES");
  const [company, setCompany]     = useState("");
  const [urgency, setUrgency]     = useState<Urgency>("NORMAL");
  const [message, setMessage]     = useState("");
  const [hpField, setHpField]     = useState("");

  // UI state
  const [loading, setLoading]     = useState(false);
  const [success, setSuccess]     = useState<{ refId: string } | null>(null);
  const [error, setError]         = useState<string | null>(null);
  const [errors, setErrors]       = useState<Record<string, string>>({});
  const formRef                   = useRef<HTMLFormElement>(null);

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  const validate = () => {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Full name is required";
    if (!email.trim()) {
      errs.email = "Work email is required";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errs.email = "Please enter a valid email address";
    }
    if (!message.trim()) errs.message = "Message is required";
    if (message.length > 5000) errs.message = "Message must be under 5000 characters";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!validate()) return;

    setLoading(true);
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, category, company, urgency, message, hp_field: hpField }),
      });

      if (!res.ok) {
        if (res.status === 429) {
          throw new Error("You've sent too many messages. Please wait a few minutes and try again.");
        }
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `Request failed (${res.status})`);
      }

      const data = await res.json();
      setSuccess({ refId: data.ticket_number || data.reference_id || `REF-${Date.now()}` });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setSuccess(null);
    setError(null);
    setErrors({});
    setName(""); setEmail(""); setCategory("SALES");
    setCompany(""); setUrgency("NORMAL"); setMessage(""); setHpField("");
  };

  // ---------------------------------------------------------------------------
  // Render: success state
  // ---------------------------------------------------------------------------

  if (success) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header />
        <main
          id="contact-success"
          className="flex-1 bg-[#050816] flex items-center justify-center px-4 py-24"
        >
          <div className="max-w-lg w-full text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[#10B981]/20 border border-[#10B981]/40 mb-6">
              <CheckCircle className="w-8 h-8 text-[#10B981]" />
            </div>
            <h1 className="text-2xl font-bold text-white mb-3">Inquiry Received!</h1>
            <p className="text-[#94A3B8] text-sm mb-8">
              Your message has been dispatched to our team. We&apos;ll respond as fast as possible.
            </p>

            <div className="bg-[#0F1629] border border-[#22D3EE]/30 rounded-2xl p-6 mb-8 text-left">
              <p className="text-xs text-[#64748B] mb-1 uppercase tracking-wider">Reference Number</p>
              <p className="text-2xl font-mono font-bold text-[#22D3EE] mb-3">{success.refId}</p>
              <p className="text-sm text-[#94A3B8]">
                Sent to:{" "}
                <span className="text-[#22D3EE] font-mono text-xs">{SUPPORT_EMAIL}</span>
              </p>
            </div>

            <div className="flex gap-3 justify-center">
              <button
                id="send-another-btn"
                onClick={handleReset}
                className="px-6 py-2.5 bg-[#22D3EE]/10 hover:bg-[#22D3EE]/20 border border-[#22D3EE]/30 text-[#22D3EE] rounded-xl text-sm font-medium transition-all duration-200"
              >
                Send Another Message
              </button>
              <Link
                href="/"
                className="px-6 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-[#94A3B8] rounded-xl text-sm font-medium transition-all duration-200"
              >
                Back to Home
              </Link>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: form
  // ---------------------------------------------------------------------------

  const inputClass = (field: string) =>
    `w-full px-4 py-3 rounded-xl bg-[#0B1120] border text-[#E2E8F0] placeholder-[#475569] text-sm outline-none transition-all duration-200 focus:shadow-[0_0_0_3px_rgba(34,211,238,0.15)] ${
      errors[field]
        ? "border-[#EF4444]/60 focus:border-[#EF4444]"
        : "border-[rgba(255,255,255,0.1)] focus:border-[#22D3EE]/60"
    }`;

  return (
    <div className="flex flex-col min-h-screen">
      <title>Contact Us — Invoice AI</title>
      <Header />

      <main id="contact-page" className="flex-1 bg-[#050816] text-white">
        {/* ------------------------------------------------------------------ */}
        {/* Hero header */}
        {/* ------------------------------------------------------------------ */}
        <section className="pt-28 pb-16 px-4 text-center relative overflow-hidden">
          {/* Background glows */}
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-[#3B82F6]/10 blur-[120px] rounded-full" />
            <div className="absolute top-20 right-1/4 w-[300px] h-[200px] bg-[#22D3EE]/8 blur-[80px] rounded-full" />
          </div>

          <div className="relative z-10 max-w-2xl mx-auto">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-[#22D3EE]/30 bg-[#22D3EE]/10 text-[#22D3EE] text-xs font-semibold tracking-wider mb-6">
              <Zap className="w-3 h-3" />
              DIRECT CUSTOMER &amp; ENTERPRISE INQUIRIES
            </div>
            <h1 className="text-4xl sm:text-5xl font-bold mb-4 bg-gradient-to-r from-white via-[#93C5FD] to-[#22D3EE] bg-clip-text text-transparent leading-tight">
              Contact Our Engineering
              <br className="hidden sm:block" /> &amp; Sales Team
            </h1>
            <p className="text-[#94A3B8] text-base sm:text-lg leading-relaxed">
              Questions about multi-tenant AI pipelines, automated OCR extraction, custom
              trainer sandboxes, or dedicated cloud deployment? We&apos;re here to help.
            </p>
          </div>
        </section>

        {/* ------------------------------------------------------------------ */}
        {/* Split grid: info card + form */}
        {/* ------------------------------------------------------------------ */}
        <section className="max-w-6xl mx-auto px-4 pb-24">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">

            {/* ---- Left: contact metadata ---- */}
            <aside className="lg:col-span-2 space-y-4">
              {/* Header card */}
              <div className="p-6 rounded-2xl border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] backdrop-blur-sm">
                <h2 className="text-sm font-semibold text-[#94A3B8] uppercase tracking-wider mb-4">
                  Official Contact
                </h2>
                <div className="space-y-4">
                  <InfoCard
                    icon={Mail}
                    title="Support Inbox"
                    value={<CopyEmailButton />}
                  />
                  <InfoCard
                    icon={Clock}
                    title="Response SLA"
                    value={
                      <span className="text-[#E2E8F0]">
                        &lt; 2h Urgent &nbsp;·&nbsp; &lt; 24h Standard
                      </span>
                    }
                    colour="#3B82F6"
                  />
                  <InfoCard
                    icon={Shield}
                    title="Security"
                    value="SOC2 Type II · Azure Isolated VNet"
                    colour="#10B981"
                  />
                  <InfoCard
                    icon={Activity}
                    title="Platform Status"
                    value={
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-[#10B981] animate-pulse" />
                        <span className="text-[#10B981] text-xs">Operational · 99.99% Uptime</span>
                      </span>
                    }
                    colour="#10B981"
                  />
                </div>
              </div>

              {/* What happens next */}
              <div className="p-5 rounded-2xl border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)]">
                <h3 className="text-xs font-semibold text-[#64748B] uppercase tracking-wider mb-3">
                  What happens next
                </h3>
                {[
                  "Your message is immediately dispatched to our engineering inbox",
                  "You'll receive a reference ID and auto-acknowledgement",
                  "A member of the team responds within the agreed SLA",
                ].map((step, i) => (
                  <div key={i} className="flex items-start gap-3 mb-3 last:mb-0">
                    <div className="w-5 h-5 rounded-full bg-[#22D3EE]/20 border border-[#22D3EE]/40 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <span className="text-[#22D3EE] text-[10px] font-bold">{i + 1}</span>
                    </div>
                    <p className="text-xs text-[#94A3B8] leading-relaxed">{step}</p>
                  </div>
                ))}
              </div>
            </aside>

            {/* ---- Right: form ---- */}
            <div className="lg:col-span-3">
              <div className="p-8 rounded-2xl border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] backdrop-blur-sm">
                <h2 className="text-lg font-semibold text-white mb-6">Send us a message</h2>

                {error && (
                  <div className="flex items-center gap-3 p-4 rounded-xl bg-[#EF4444]/10 border border-[#EF4444]/30 mb-6">
                    <AlertCircle className="w-5 h-5 text-[#EF4444] flex-shrink-0" />
                    <p className="text-sm text-[#FCA5A5]">{error}</p>
                  </div>
                )}

                <form
                  ref={formRef}
                  id="contact-form"
                  onSubmit={handleSubmit}
                  className="space-y-5"
                  noValidate
                >
                  {/* Honeypot field for bot detection (hidden from real users) */}
                  <input
                    type="text"
                    name="hp_field"
                    tabIndex={-1}
                    autoComplete="off"
                    aria-hidden="true"
                    style={{ position: "absolute", left: "-9999px", opacity: 0, height: 0, width: 0, pointerEvents: "none" }}
                    value={hpField}
                    onChange={(e) => setHpField(e.target.value)}
                  />

                  {/* Name + Email */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-[#94A3B8] mb-1.5" htmlFor="contact-name">
                        Full Name <span className="text-[#EF4444]">*</span>
                      </label>
                      <input
                        id="contact-name"
                        type="text"
                        autoComplete="name"
                        placeholder="Your full name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className={inputClass("name")}
                      />
                      {errors.name && <p className="text-xs text-[#EF4444] mt-1">{errors.name}</p>}
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-[#94A3B8] mb-1.5" htmlFor="contact-email">
                        Work Email <span className="text-[#EF4444]">*</span>
                      </label>
                      <input
                        id="contact-email"
                        type="email"
                        autoComplete="email"
                        inputMode="email"
                        placeholder="you@company.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        className={inputClass("email")}
                      />
                      {errors.email && <p className="text-xs text-[#EF4444] mt-1">{errors.email}</p>}
                    </div>
                  </div>

                  {/* Category + Company */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-[#94A3B8] mb-1.5" htmlFor="contact-category">
                        Inquiry Category
                      </label>
                      <div className="relative">
                        <select
                          id="contact-category"
                          value={category}
                          onChange={(e) => setCategory(e.target.value)}
                          className={`${inputClass("category")} appearance-none pr-10 cursor-pointer`}
                        >
                          {CATEGORIES.map((c) => (
                            <option key={c.value} value={c.value}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#475569] pointer-events-none" />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-[#94A3B8] mb-1.5" htmlFor="contact-company">
                        Company / Organization
                      </label>
                      <input
                        id="contact-company"
                        type="text"
                        autoComplete="organization"
                        placeholder="Optional"
                        value={company}
                        onChange={(e) => setCompany(e.target.value)}
                        className={inputClass("company")}
                      />
                    </div>
                  </div>

                  {/* Urgency pills */}
                  <div>
                    <label className="block text-xs font-medium text-[#94A3B8] mb-2">
                      Urgency Level
                    </label>
                    <div className="flex gap-2 flex-wrap" role="group" aria-label="Urgency level">
                      {URGENCY_OPTIONS.map((opt) => {
                        const active = urgency === opt.value;
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            id={`urgency-${opt.value.toLowerCase()}`}
                            onClick={() => setUrgency(opt.value)}
                            style={
                              active
                                ? {
                                    borderColor: `${opt.colour}60`,
                                    background: `${opt.colour}18`,
                                    color: opt.colour,
                                  }
                                : {}
                            }
                            className={`px-4 py-2 rounded-xl border text-xs font-medium transition-all duration-200 ${
                              active
                                ? "shadow-[0_0_12px_rgba(0,0,0,0.3)]"
                                : "border-[rgba(255,255,255,0.1)] text-[#94A3B8] hover:border-white/20 hover:text-white bg-transparent"
                            }`}
                          >
                            {opt.label}
                            <span className="ml-1.5 opacity-70 text-[10px]">
                              ({opt.description})
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Message */}
                  <div>
                    <div className="flex justify-between items-center mb-1.5">
                      <label className="block text-xs font-medium text-[#94A3B8]" htmlFor="contact-message">
                        Message <span className="text-[#EF4444]">*</span>
                      </label>
                      <span
                        className={`text-xs ${message.length > 4800 ? "text-[#EF4444]" : "text-[#475569]"}`}
                      >
                        {message.length}/5000
                      </span>
                    </div>
                    <textarea
                      id="contact-message"
                      rows={6}
                      placeholder="Describe your question, use case, or issue in as much detail as possible…"
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      className={`${inputClass("message")} resize-y min-h-[120px]`}
                    />
                    {errors.message && (
                      <p className="text-xs text-[#EF4444] mt-1">{errors.message}</p>
                    )}
                  </div>

                  {/* Submit */}
                  <button
                    id="contact-submit-btn"
                    type="submit"
                    disabled={loading}
                    className="w-full flex items-center justify-center gap-2 py-3.5 px-6 rounded-xl bg-gradient-to-r from-[#3B82F6] to-[#22D3EE] text-white font-semibold text-sm hover:opacity-90 active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed transition-all duration-200 shadow-[0_4px_20px_rgba(34,211,238,0.25)]"
                  >
                    {loading ? (
                      <>
                        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Dispatching…
                      </>
                    ) : (
                      <>
                        <Send className="w-4 h-4" />
                        Send Message &amp; Dispatch to {SUPPORT_EMAIL}
                      </>
                    )}
                  </button>

                  <p className="text-xs text-[#475569] text-center">
                    By submitting, you agree to our{" "}
                    <Link href="/privacy" className="text-[#22D3EE] hover:underline">
                      Privacy Policy
                    </Link>
                    . We never share your data.
                  </p>
                </form>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
