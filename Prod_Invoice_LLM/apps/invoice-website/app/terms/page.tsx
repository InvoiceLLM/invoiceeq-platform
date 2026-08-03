"use client";

import React from "react";
import { Header } from "@/components/marketing/Header";
import { Scale, CheckCircle, HelpCircle, FileText } from "lucide-react";

export default function TermsPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16 relative z-10">
        
        {/* Ambient Top Light */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[500px] h-[250px] bg-[#3B82F6]/10 blur-[100px] rounded-full -z-10" />

        {/* Page Title */}
        <div className="text-center mb-12">
          <div className="inline-flex p-3 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 text-[#22D3EE] mb-4">
            <Scale className="w-8 h-8" />
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-5xl">
            Terms of Service
          </h1>
          <p className="mt-4 text-sm text-[#94A3B8]">
            Last updated: August 3, 2026
          </p>
        </div>

        {/* Glass Content Card */}
        <div className="glass-panel rounded-2xl border border-white/10 bg-[#0A1124]/40 backdrop-blur-[24px] p-6 sm:p-10 space-y-8 shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
          
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-[#22D3EE]" /> 1. Acceptance of Terms
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              By accessing and using the Invoice AI platform, you agree to comply with and be bound by these Terms of Service. If you are entering into these terms on behalf of a company, you represent that you have the authority to bind that entity.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <FileText className="w-5 h-5 text-[#10B981]" /> 2. Platform Usage and Restrictions
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              Our platform allows you to upload and parse invoice documents. You agree not to upload any malicious code, violate system security, or use the service to process unauthorized or illegal financial data.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <HelpCircle className="w-5 h-5 text-purple-400" /> 3. Service SLA and Support
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              We strive to maintain a 99.9% uptime SLA for our enterprise-tiered platform. Support requests can be made directly via our help portal, and critical response times are guaranteed within 4 hours for Pro accounts.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white">
              4. Termination
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              We reserve the right to suspend or terminate accounts that violate these terms or fail to pay outstanding subscription balances.
            </p>
          </section>

        </div>
      </main>
    </div>
  );
}
