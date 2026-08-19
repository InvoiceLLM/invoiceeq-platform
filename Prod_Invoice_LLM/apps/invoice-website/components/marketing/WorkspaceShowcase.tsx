"use client";

import React, { useState } from "react";
import {
  Building2,
  Lock,
  Users,
  FileCheck,
  CheckCircle2,
  UserCheck,
  ShieldAlert,
  Terminal,
  Play,
  Key,
  ShieldCheck,
} from "lucide-react";

interface TenantCard {
  id: string;
  name: string;
  domain: string;
  tenantId: string;
  invoicesProcessed: string;
  borderColor: string;
  badgeBg: string;
  accentColor: string;
  users: { name: string; email: string; role: "Admin" | "Auditor" | "Loader" }[];
}

const TENANT_DATA: TenantCard[] = [
  {
    id: "acme",
    name: "Acme Corp",
    domain: "@acme.com",
    tenantId: "t_acme_881920",
    invoicesProcessed: "1,240",
    borderColor: "border-[#10B981]/40",
    badgeBg: "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30",
    accentColor: "text-[#10B981]",
    users: [
      { name: "Sarah Jenkins", email: "sarah@acme.com", role: "Admin" },
      { name: "David Chen", email: "david@acme.com", role: "Auditor" },
      { name: "Alex Rivera", email: "alex@acme.com", role: "Loader" },
    ],
  },
  {
    id: "techfirm",
    name: "TechFirm Ltd",
    domain: "@techfirm.io",
    tenantId: "t_techfirm_441029",
    invoicesProcessed: "850",
    borderColor: "border-[#3B82F6]/40",
    badgeBg: "bg-[#3B82F6]/10 text-[#3B82F6] border-[#3B82F6]/30",
    accentColor: "text-[#3B82F6]",
    users: [
      { name: "Elena Rostova", email: "elena@techfirm.io", role: "Admin" },
      { name: "Marcus Vance", email: "marcus@techfirm.io", role: "Auditor" },
      { name: "Priya Sharma", email: "priya@techfirm.io", role: "Loader" },
    ],
  },
  {
    id: "globaltrade",
    name: "GlobalTrade Inc",
    domain: "@globaltrade.com",
    tenantId: "t_globaltrade_99104",
    invoicesProcessed: "3,410",
    borderColor: "border-[#8B5CF6]/40",
    badgeBg: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
    accentColor: "text-[#8B5CF6]",
    users: [
      { name: "James Wilson", email: "j.wilson@globaltrade.com", role: "Admin" },
      { name: "Linda Wu", email: "l.wu@globaltrade.com", role: "Auditor" },
      { name: "Tom Baker", email: "t.baker@globaltrade.com", role: "Loader" },
    ],
  },
];

export function WorkspaceShowcase() {
  const [activeTenantId, setActiveTenantId] = useState<string>("acme");
  const [probeResult, setProbeResult] = useState<string | null>(null);
  const [isTestingProbe, setIsTestingProbe] = useState<boolean>(false);

  const getRoleBadgeStyle = (role: string) => {
    switch (role) {
      case "Admin":
        return "bg-[#6366F1]/15 text-[#6366F1] border-[#6366F1]/30";
      case "Auditor":
        return "bg-[#22D3EE]/15 text-[#22D3EE] border-[#22D3EE]/30";
      case "Loader":
        return "bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30";
      default:
        return "bg-white/5 text-[#CBD5E1] border-white/10";
    }
  };

  const runSecurityProbe = () => {
    setIsTestingProbe(true);
    setProbeResult(null);

    setTimeout(() => {
      setIsTestingProbe(false);
      setProbeResult(
        "PROBE FAILED (SECURITY SUCCESS): Tenant isolation check blocked query attempt across boundary. Result: HTTP 403 Forbidden - Tenant Scope Violation."
      );
    }, 700);
  };

  return (
    <section id="features" className="py-24 relative border-t border-[rgba(255,255,255,0.08)] scroll-mt-[65px]">
      {/* Section Divider Header Line */}
      <div className="glowing-divider-line mb-16" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.04] border border-[rgba(255,255,255,0.08)] text-xs font-medium text-[#22D3EE] backdrop-blur-md">
            <ShieldCheck className="w-4 h-4 text-[#22D3EE]" />
            <span>Strict Multi-Tenant Row Security</span>
          </div>

          <h2 className="text-xl sm:text-2xl font-semibold text-white tracking-tight section-title">
            Every Company Gets Their Own{" "}
            <span className="animated-hero-heading block sm:inline">Private Workspace</span>
          </h2>

          <p className="text-base sm:text-lg text-[#94A3B8]">
            Your invoices, users and AI context remain isolated from every other company.
          </p>

          {/* Company Selector Tabs */}
          <div className="flex items-center justify-center gap-3 pt-4 overflow-x-auto">
            {TENANT_DATA.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTenantId(t.id)}
                className={`text-xs sm:text-sm px-4 py-2 rounded-xl font-semibold border transition-all duration-300 flex items-center gap-2 ${
                  activeTenantId === t.id
                    ? "bg-[#3B82F6]/20 text-white border-[#3B82F6] shadow-[0_0_20px_rgba(59,130,246,0.4)]"
                    : "bg-white/5 text-[#94A3B8] border-white/10 hover:text-white"
                }`}
              >
                <Building2 className={`w-4 h-4 ${t.accentColor}`} />
                <span>{t.name}</span>
              </button>
            ))}
          </div>
        </div>

        {/* 3-COLUMN GLASSMORPHISM TENANT PROFILE CARDS */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8">
          {TENANT_DATA.map((tenant) => {
            const isActive = activeTenantId === tenant.id;

            return (
              <div
                key={tenant.name}
                onClick={() => setActiveTenantId(tenant.id)}
                className={`glass-card-enterprise p-6 flex flex-col justify-between cursor-pointer perspective-1000 preserve-3d transition-all duration-500 ${
                  isActive
                    ? `border-[#3B82F6] shadow-[0_0_40px_rgba(59,130,246,0.4)] -translate-y-2.5 scale-[1.02] z-10`
                    : "opacity-85 hover:opacity-100 hover:-translate-y-1.5 hover:scale-[1.01]"
                }`}
              >
                <div>
                  {/* Card Top Banner */}
                  <div className="flex items-center justify-between pb-4 border-b border-[rgba(255,255,255,0.08)]">
                    <div className="flex items-center gap-3">
                      <div className="p-2.5 rounded-xl bg-[#050816] border border-[rgba(255,255,255,0.08)] text-white">
                        <Building2 className={`w-5 h-5 ${tenant.accentColor}`} />
                      </div>
                      <div>
                        <h3 className="font-bold text-white text-lg">{tenant.name}</h3>
                        <p className="text-xs font-mono text-[#94A3B8]">{tenant.domain}</p>
                      </div>
                    </div>
                    <span className={`text-xs px-2.5 py-1 rounded-full border font-medium ${tenant.badgeBg}`}>
                      Isolated
                    </span>
                  </div>

                  {/* Tenant Keys & Metrics */}
                  <div className="my-5 p-3.5 rounded-xl bg-[#050816]/70 border border-[rgba(255,255,255,0.08)] space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[#94A3B8] flex items-center gap-1.5">
                        <Key className="w-3.5 h-3.5 text-[#94A3B8]" />
                        Tenant ID Key:
                      </span>
                      <span className="font-mono text-[#CBD5E1] font-semibold">{tenant.tenantId}</span>
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1 border-t border-white/10">
                      <span className="text-[#94A3B8] flex items-center gap-1.5">
                        <FileCheck className={`w-3.5 h-3.5 ${tenant.accentColor}`} />
                        Invoices Processed:
                      </span>
                      <span className="font-mono text-white font-bold">{tenant.invoicesProcessed}</span>
                    </div>
                  </div>

                  {/* Members & Roles List */}
                  <div className="space-y-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8] flex items-center gap-1.5">
                      <Users className="w-3.5 h-3.5 text-[#94A3B8]" />
                      Assigned Workspace Members
                    </p>
                    <div className="space-y-2">
                      {tenant.users.map((user) => (
                        <div
                          key={user.email}
                          className="flex items-center justify-between p-2.5 rounded-lg bg-[#050816]/50 border border-[rgba(255,255,255,0.08)] text-xs"
                        >
                          <div className="flex items-center gap-2">
                            <UserCheck className="w-3.5 h-3.5 text-[#94A3B8]" />
                            <span className="text-white font-medium">{user.name}</span>
                          </div>
                          <span className={`px-2 py-0.5 rounded border text-[11px] font-semibold ${getRoleBadgeStyle(user.role)}`}>
                            {user.role}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Footer Note */}
                <div className="mt-6 pt-4 border-t border-[rgba(255,255,255,0.08)] flex items-center justify-between text-xs text-[#94A3B8]">
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981]" />
                    Row Level Security (RLS)
                  </span>
                  <span className="font-mono text-[11px] text-[#94A3B8]">SOC2 Vault</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* SECURITY PROBE TESTER CARD */}
        <div className="mt-14 max-w-4xl mx-auto">
          <div className="glass-card-enterprise p-6 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[rgba(255,255,255,0.08)]">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-[#3B82F6]/10 border border-[#3B82F6]/30 text-[#22D3EE]">
                  <ShieldAlert className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="text-base font-bold text-white">Live Data Isolation Probe Simulator</h4>
                  <p className="text-xs text-[#94A3B8]">Test if an authenticated user from `@techfirm.io` can query invoices belonging to `@acme.com`.</p>
                </div>
              </div>

              <button
                onClick={runSecurityProbe}
                disabled={isTestingProbe}
                className="btn-primary-gradient text-xs px-5 py-2.5 flex items-center justify-center gap-2 shrink-0"
              >
                <Play className={`w-3.5 h-3.5 fill-white ${isTestingProbe ? "animate-spin" : ""}`} />
                <span>{isTestingProbe ? "Testing Isolation Probe..." : "Run Security Probe Test"}</span>
              </button>
            </div>

            {/* Probe Result Feed */}
            {probeResult && (
              <div className="p-4 rounded-xl bg-[#050816] border border-[#22D3EE]/40 text-xs font-mono text-[#22D3EE] flex items-start gap-3 shadow-[0_0_20px_rgba(34,211,238,0.2)]">
                <Terminal className="w-4 h-4 text-[#22D3EE] shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-bold text-[#22D3EE]">SECURITY GUARD BLOCK VERIFIED</p>
                  <p className="text-[#CBD5E1]">{probeResult}</p>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between text-xs text-[#94A3B8] pt-1">
              <span className="flex items-center gap-1.5">
                <Lock className="w-3.5 h-3.5 text-[#10B981]" />
                Database Scoped Tenant Policy Active
              </span>
              <span className="font-mono text-[#22D3EE] font-semibold">100% Data Isolation</span>
            </div>
          </div>
        </div>

      </div>
    </section>
  );
}
