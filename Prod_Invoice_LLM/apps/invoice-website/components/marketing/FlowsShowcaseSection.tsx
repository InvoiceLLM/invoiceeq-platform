"use client";

import React from "react";
import {
  Play,
  ExternalLink,
  Workflow,
  Sparkles,
  ArrowRight,
  Database,
  Cpu,
  Bot,
  ShieldCheck,
} from "lucide-react";
import { appHref } from "../../lib/billingPlans";

interface FlowsShowcaseSectionProps {
  onOpenModal: (flowId?: string) => void;
}

const FEATURED_FLOWS = [
  {
    id: "inbound",
    title: "Inbound Document Pipeline",
    badge: "Inbound Flow",
    description: "Azure Storage ingestion → Document Intelligence OCR → Complexity Classification → Consensus → PO Match.",
    icon: Database,
    accent: "border-[#3B82F6]/40 bg-[#3B82F6]/10 text-[#3B82F6]",
  },
  {
    id: "outbound",
    title: "Outbound Vendor Flow",
    badge: "Vendor Flow - New",
    description: "Automated vendor invoice generation, queueing, approval workflows, and ledger synchronization.",
    icon: Cpu,
    accent: "border-[#10B981]/40 bg-[#10B981]/10 text-[#10B981]",
  },
  {
    id: "chat",
    title: "Conversational RAG Agent",
    badge: "Interactive Chat",
    description: "Natural-language query processing with vector embeddings and instant invoice reference lookup.",
    icon: Bot,
    accent: "border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6]",
  },
  {
    id: "vendor_chat",
    title: "Direction-Aware Rule Engine",
    badge: "Smart Context",
    description: "Dual-direction rule injection dynamically adjusting extraction rules for inbound vs outbound documents.",
    icon: ShieldCheck,
    accent: "border-[#22D3EE]/40 bg-[#22D3EE]/10 text-[#22D3EE]",
  },
];

export function FlowsShowcaseSection({ onOpenModal }: FlowsShowcaseSectionProps) {
  const flowsUrl = appHref("/flows");

  return (
    <section id="architecture-flows" className="py-20 relative border-t border-[rgba(255,255,255,0.08)] bg-[#050816]/70 backdrop-blur-md overflow-hidden">
      
      {/* Background Ambient Glow */}
      <div className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] bg-[#3B82F6]/10 blur-[150px] rounded-full -z-10" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.04] border border-[rgba(255,255,255,0.08)] text-xs font-semibold text-[#22D3EE] backdrop-blur-md shadow-[0_0_20px_rgba(34,211,238,0.15)]">
            <Workflow className="w-4 h-4 text-[#22D3EE]" />
            <span>Interactive Architecture Walkthrough</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            See Intelligent Agent Architecture <span className="animated-hero-heading inline-block">In Action</span>
          </h2>

          <p className="text-base sm:text-lg text-[#E2E8F0] leading-relaxed max-w-2xl mx-auto font-medium">
            See exactly how your invoices get checked and verified, step by step.
          </p>

          <p className="text-sm sm:text-base text-[#94A3B8] leading-relaxed max-w-2xl mx-auto">
            Cross-checked by multiple AI models for accuracy, with real-time text extraction and rules that adapt for invoices coming in or going out — across four live pipelines.
          </p>
        </div>

        {/* MAIN PREVIEW CARD CONTAINER */}
        <div className="max-w-5xl mx-auto rounded-2xl glass-card-enterprise p-6 sm:p-8 relative overflow-hidden border border-white/15 shadow-[0_0_40px_rgba(59,130,246,0.15)]">
          
          {/* Card Top Action Bar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-white/10">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-[#3B82F6] to-[#22D3EE] text-white shadow-[0_0_15px_rgba(34,211,238,0.4)]">
                <Sparkles className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Live System Flow Simulator</h3>
                <p className="text-xs text-[#94A3B8]">4 Animated Agent Flow Pipelines Ready for Execution</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Modal Trigger Button */}
              <button
                onClick={() => onOpenModal("inbound")}
                className="btn-primary-gradient px-5 py-2.5 text-xs font-bold flex items-center justify-center gap-2 group shadow-[0_0_20px_rgba(59,130,246,0.4)]"
              >
                <Play className="w-3.5 h-3.5 fill-white" />
                <span>Launch Live Simulator</span>
              </button>

              {/* Direct Full Tab External Link */}
              <a
                href={flowsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-secondary-glass px-4 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5"
              >
                <span>Full Tab</span>
                <ExternalLink className="w-3.5 h-3.5 text-[#22D3EE]" />
              </a>
            </div>
          </div>

          {/* 4 FLOW TILES GRID */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 py-6">
            {FEATURED_FLOWS.map((flow) => {
              const Icon = flow.icon;
              return (
                <div
                  key={flow.id}
                  onClick={() => onOpenModal(flow.id)}
                  className="group relative p-4 rounded-xl bg-white/[0.03] border border-white/10 hover:border-white/25 hover:bg-white/[0.06] transition-all duration-300 cursor-pointer flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="p-2 rounded-lg bg-white/5 border border-white/10 group-hover:scale-110 transition-transform">
                        <Icon className="w-4 h-4 text-[#22D3EE]" />
                      </div>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${flow.accent}`}>
                        {flow.badge}
                      </span>
                    </div>

                    <h4 className="text-sm font-bold text-white mb-1.5 group-hover:text-[#22D3EE] transition-colors">
                      {flow.title}
                    </h4>

                    <p className="text-xs text-[#94A3B8] leading-relaxed">
                      {flow.description}
                    </p>
                  </div>

                  <div className="pt-3 mt-3 border-t border-white/5 flex items-center justify-between text-[11px] text-[#22D3EE] font-semibold">
                    <span>Simulate {flow.badge}</span>
                    <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Interactive Simulation Banner Bar */}
          <div
            onClick={() => onOpenModal("inbound")}
            className="p-4 rounded-xl bg-gradient-to-r from-[#0A1124] via-[#050816] to-[#0A1124] border border-[#3B82F6]/30 flex flex-col sm:flex-row items-center justify-between gap-3 cursor-pointer hover:border-[#22D3EE]/50 transition-all duration-300 group"
          >
            <div className="flex items-center gap-3">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#10B981] opacity-75" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-[#10B981]" />
              </span>
              <span className="text-xs sm:text-sm font-semibold text-[#CBD5E1] group-hover:text-white transition-colors">
                Interactive Multi-Agent Flow Visualizer is ready. Click any pipeline card to launch its specific flow.
              </span>
            </div>

            <div className="flex items-center gap-2 text-xs font-bold text-[#22D3EE] group-hover:underline">
              <span>Open Interactive Modal</span>
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </div>
          </div>

        </div>

      </div>
    </section>
  );
}
