"use client";

import React from "react";
import { Header } from "@/components/marketing/Header";
import { ShieldCheck, Lock, Eye, Server } from "lucide-react";

export default function PrivacyPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16 relative z-10">
        
        {/* Ambient Top Light */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[500px] h-[250px] bg-blue-500/10 blur-[100px] rounded-full -z-10" />

        {/* Page Title */}
        <div className="text-center mb-12">
          <div className="inline-flex p-3 rounded-2xl bg-blue-500/10 border border-blue-500/20 text-[#22D3EE] mb-4">
            <ShieldCheck className="w-8 h-8" />
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-5xl">
            Privacy Policy
          </h1>
          <p className="mt-4 text-sm text-[#94A3B8]">
            Last updated: August 3, 2026
          </p>
        </div>

        {/* Glass Content Card */}
        <div className="glass-panel rounded-2xl border border-white/10 bg-[#0A1124]/40 backdrop-blur-[24px] p-6 sm:p-10 space-y-8 shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
          
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Eye className="w-5 h-5 text-[#22D3EE]" /> 1. Information We Collect
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              We collect invoice documents and files uploaded to our platform for OCR extraction, metadata parsing, and RAG-based search indices. This includes grand totals, vendor details, and compliance-related line items.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Lock className="w-5 h-5 text-[#10B981]" /> 2. Data Isolation and Protection
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              All multi-tenant data is completely isolated. Data from one organization is never accessible by another user or company, backed by strict per-tenant structural boundaries and encryption-at-rest protocols.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Server className="w-5 h-5 text-purple-400" /> 3. Data Processing and Storage
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              Document storage and AI extraction processing are fully containerized and hosted securely on Azure AI and Azure Document Intelligence platforms. We do not sell or share your invoice data with third-party advertising companies.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-white">
              4. Contact Us
            </h2>
            <p className="text-xs sm:text-sm text-[#94A3B8] leading-relaxed">
              For any questions regarding this Privacy Policy or requests regarding your enterprise data, please reach out to our platform support team at support@invoiceai.com.
            </p>
          </section>

        </div>
      </main>
    </div>
  );
}
