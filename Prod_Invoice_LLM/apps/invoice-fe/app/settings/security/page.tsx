"use client";

import React, { useState } from "react";
import { ShieldCheck, Key, Lock, Eye, CheckCircle2, Copy, Check, RefreshCw, FileText } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

export default function SecuritySettingsPage() {
  usePageHeader({
    title: "Security & Access Control",
    subtitle: "Manage API credentials, tenant isolation parameters, and security policies",
    backHref: "/settings",
  });

  const { tenantId, role } = useAuth();
  const isAdmin = role === "Admin";
  const [apiKey, setApiKey] = useState("inv_live_9f8a3b2c1d0e4f5a6b7c8d9e0f");
  const [copiedKey, setCopiedKey] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);

  const handleCopyKey = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard.writeText(apiKey);
      setCopiedKey(true);
      setTimeout(() => setCopiedKey(false), 2000);
    }
  };

  const handleRegenerateKey = () => {
    if (!isAdmin) return;
    setIsGenerating(true);
    setTimeout(() => {
      const newKey = "inv_live_" + Array.from({ length: 24 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
      setApiKey(newKey);
      setIsGenerating(false);
    }, 600);
  };

  const roleMatrix = [
    { role: "Admin", load: true, audit: true, train: true, settings: true, desc: "Full administrative access and key management" },
    { role: "Auditor", load: false, audit: true, train: true, settings: false, desc: "Review, approve, and train extraction models" },
    { role: "Loader", load: true, audit: false, train: false, settings: false, desc: "Upload and batch ingest documents" },
    { role: "Viewer", load: false, audit: false, train: false, settings: false, desc: "Read-only access to metrics and reports" },
  ];

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      <main className="flex-1 px-6 py-8 max-w-4xl w-full mx-auto space-y-6">

        {/* API Credentials */}
        <section aria-labelledby="api-keys-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <Key className="w-5 h-5" />
            </div>
            <div>
              <h2 id="api-keys-heading" className="font-semibold text-sm text-white">API Authentication Key</h2>
              <p className="text-xs text-slate-400">Use this token to authenticate programmatic REST API requests</p>
            </div>
          </div>

          <div className="flex items-center gap-3 bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 pl-4">
            <span className="font-mono text-xs text-slate-200 truncate flex-1">{apiKey}</span>
            <button
              onClick={handleCopyKey}
              className="p-2 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white border border-[#222D3D] transition-all flex items-center justify-center shrink-0"
              title="Copy Key"
            >
              {copiedKey ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
            </button>
            {isAdmin && (
              <button
                onClick={handleRegenerateKey}
                disabled={isGenerating}
                className="px-3 py-2 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-semibold flex items-center gap-1.5 transition-all disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isGenerating ? "animate-spin" : ""}`} />
                Rotate Key
              </button>
            )}
          </div>
        </section>

        {/* Tenant Isolation Status */}
        <section aria-labelledby="tenant-security-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Lock className="w-5 h-5" />
            </div>
            <div>
              <h2 id="tenant-security-heading" className="font-semibold text-sm text-white">Tenant Isolation & Data Encryption</h2>
              <p className="text-xs text-slate-400">Row-level security enforcement and data isolation posture</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Isolation Mode</span>
              <p className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" /> Multi-Tenant Row Security
              </p>
            </div>
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Encryption at Rest</span>
              <p className="text-xs font-semibold text-white">AES-256 GCM</p>
            </div>
            <div className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3.5 space-y-1">
              <span className="text-[10px] uppercase font-mono text-slate-500 tracking-wider">Active Role</span>
              <p className="text-xs font-semibold text-blue-400">{role || "Viewer"}</p>
            </div>
          </div>
        </section>

        {/* Role Access Matrix */}
        <section aria-labelledby="role-matrix-heading" className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-4 shadow-lg">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 id="role-matrix-heading" className="font-semibold text-sm text-white">Role-Based Access Control (RBAC) Matrix</h2>
              <p className="text-xs text-slate-400">Configured permissions for each role level</p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-[#222D3D] text-slate-400 font-mono text-[10px] uppercase">
                  <th className="py-2.5 px-3">Role</th>
                  <th className="py-2.5 px-3 text-center">Ingest</th>
                  <th className="py-2.5 px-3 text-center">Audit</th>
                  <th className="py-2.5 px-3 text-center">Trainer</th>
                  <th className="py-2.5 px-3 text-center">Settings</th>
                  <th className="py-2.5 px-3">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222D3D]/50 text-slate-300">
                {roleMatrix.map((item) => (
                  <tr key={item.role} className="hover:bg-slate-900/30">
                    <td className="py-3 px-3 font-semibold text-white font-mono">{item.role}</td>
                    <td className="py-3 px-3 text-center">{item.load ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-center">{item.audit ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-center">{item.train ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-center">{item.settings ? <span className="text-emerald-400 font-bold">✓</span> : <span className="text-slate-600">—</span>}</td>
                    <td className="py-3 px-3 text-slate-400 text-[11px]">{item.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
