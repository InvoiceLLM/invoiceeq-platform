"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  ScanLine,
  ShieldCheck,
  MessageSquareText,
  TrendingUp,
  Sparkles,
  Bot,
  ShieldAlert,
  BrainCircuit,
  ArrowUpRight,
} from "lucide-react";

interface AgentCapability {
  id: string;
  name: string;
  subtitle: string;
  description: string;
  icon: React.ElementType;
  hoverEffectType: "scan" | "shield" | "chat" | "graph";
  accentGradient: string;
  borderGlow: string;
  bgGlow: string;
  textColor: string;
  badgeBg: string;
}

const AGENTS_DATA: AgentCapability[] = [
  {
    id: "nova",
    name: "NOVA",
    subtitle: "Smart Invoice Extraction",
    description:
      "Reads invoices, captures line items and converts documents into structured business data.",
    icon: ScanLine,
    hoverEffectType: "scan",
    accentGradient: "from-[#3B82F6] via-[#06B6D4] to-[#22D3EE]",
    borderGlow: "group-hover:border-[#22D3EE]/70 group-hover:shadow-[0_0_30px_rgba(34,211,238,0.35)]",
    bgGlow: "bg-[#22D3EE]/15",
    textColor: "text-[#22D3EE]",
    badgeBg: "bg-[#22D3EE]/10 text-[#22D3EE] border-[#22D3EE]/30",
  },
  {
    id: "sentinel",
    name: "SENTINEL",
    subtitle: "Invoice Risk Detection",
    description:
      "Checks totals, tax values, confidence scores and duplicate invoices before approval.",
    icon: ShieldCheck,
    hoverEffectType: "shield",
    accentGradient: "from-[#10B981] via-[#14B8A6] to-[#34D399]",
    borderGlow: "group-hover:border-[#10B981]/70 group-hover:shadow-[0_0_30px_rgba(16,185,129,0.35)]",
    bgGlow: "bg-[#10B981]/15",
    textColor: "text-[#10B981]",
    badgeBg: "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30",
  },
  {
    id: "sage",
    name: "SAGE",
    subtitle: "Invoice Intelligence Chat",
    description:
      "Ask natural-language questions and receive answers from your invoice data with references.",
    icon: MessageSquareText,
    hoverEffectType: "chat",
    accentGradient: "from-[#6366F1] via-[#8B5CF6] to-[#A855F7]",
    borderGlow: "group-hover:border-[#8B5CF6]/70 group-hover:shadow-[0_0_30px_rgba(139,92,246,0.35)]",
    bgGlow: "bg-[#8B5CF6]/15",
    textColor: "text-[#8B5CF6]",
    badgeBg: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
  },
  {
    id: "evolve",
    name: "EVOLVE",
    subtitle: "Continuous Learning",
    description:
      "Learns from approved corrections and improves processing for similar vendor invoices.",
    icon: BrainCircuit,
    hoverEffectType: "graph",
    accentGradient: "from-[#8B5CF6] via-[#6366F1] to-[#3B82F6]",
    borderGlow: "group-hover:border-[#6366F1]/70 group-hover:shadow-[0_0_30px_rgba(99,102,241,0.35)]",
    bgGlow: "bg-[#6366F1]/15",
    textColor: "text-[#6366F1]",
    badgeBg: "bg-[#6366F1]/10 text-[#6366F1] border-[#6366F1]/30",
  },
];

function Agent3DCard({ agent }: { agent: AgentCapability }) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [rotateX, setRotateX] = useState(0);
  const [rotateY, setRotateY] = useState(0);
  const [isHovered, setIsHovered] = useState(false);
  const [isTouchDevice, setIsTouchDevice] = useState(false);

  useEffect(() => {
    // Detect touch device or reduced motion
    const touch = window.matchMedia("(pointer: coarse)").matches;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (touch || reducedMotion) {
      setIsTouchDevice(true);
    }
  }, []);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (isTouchDevice || !cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const mouseX = e.clientX - centerX;
    const mouseY = e.clientY - centerY;

    // Subtle 3D tilt max +-8deg
    const rX = -(mouseY / (rect.height / 2)) * 6;
    const rY = (mouseX / (rect.width / 2)) * 6;

    setRotateX(rX);
    setRotateY(rY);
  };

  const handleMouseEnter = () => {
    setIsHovered(true);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    setRotateX(0);
    setRotateY(0);
  };

  const IconComponent = agent.icon;

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        transform:
          isHovered && !isTouchDevice
            ? `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-6px) scale(1.02)`
            : "perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0px) scale(1)",
        transition: isHovered
          ? "transform 0.15s cubic-bezier(0.2, 0.8, 0.2, 1)"
          : "transform 0.5s cubic-bezier(0.16, 1, 0.3, 1)",
      }}
      className={`group relative rounded-2xl p-6 bg-[#050816]/80 backdrop-blur-xl border border-white/10 transition-all duration-300 flex flex-col justify-between overflow-hidden cursor-pointer ${agent.borderGlow}`}
    >
      {/* Background Radial Glow */}
      <div
        className={`pointer-events-none absolute -top-12 -right-12 w-44 h-44 rounded-full blur-3xl opacity-20 transition-opacity duration-500 group-hover:opacity-45 ${agent.bgGlow}`}
      />

      {/* Top Left Glass Specular Highlight Line */}
      <div className="pointer-events-none absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-white/20 to-transparent" />

      <div>
        {/* Card Header & Floating Icon */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div
              className={`p-3 rounded-xl bg-gradient-to-br ${agent.accentGradient} text-white shadow-lg transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3`}
            >
              <IconComponent className="w-5 h-5" />
            </div>
            <div>
              <span className="text-xl font-extrabold tracking-wide text-white block">
                {agent.name}
              </span>
              <span className={`text-[11px] font-semibold px-2 py-0.5 rounded border inline-block mt-0.5 ${agent.badgeBg}`}>
                {agent.subtitle}
              </span>
            </div>
          </div>
        </div>

        {/* Short Customer-Friendly Description */}
        <p className="text-xs text-[#94A3B8] leading-relaxed group-hover:text-[#CBD5E1] transition-colors duration-200 min-h-[40px]">
          {agent.description}
        </p>
      </div>

      {/* Micro Icon Interaction Indicator & Bottom Bar */}
      <div className="pt-5 mt-4 border-t border-[rgba(255,255,255,0.08)] flex items-center justify-between text-xs text-[#94A3B8]">
        <div className="flex items-center gap-1.5 font-medium">
          {agent.hoverEffectType === "scan" && (
            <span className="flex items-center gap-1.5 text-[#22D3EE]">
              <ScanLine className="w-3.5 h-3.5 animate-pulse" />
              <span>Auto-Extraction Engine</span>
            </span>
          )}
          {agent.hoverEffectType === "shield" && (
            <span className="flex items-center gap-1.5 text-[#10B981]">
              <ShieldAlert className="w-3.5 h-3.5" />
              <span>Risk & Duplicate Checks</span>
            </span>
          )}
          {agent.hoverEffectType === "chat" && (
            <span className="flex items-center gap-1.5 text-[#8B5CF6]">
              <Bot className="w-3.5 h-3.5 animate-bounce" style={{ animationDuration: "2s" }} />
              <span>Instant Conversational Q&A</span>
            </span>
          )}
          {agent.hoverEffectType === "graph" && (
            <span className="flex items-center gap-1.5 text-[#6366F1]">
              <TrendingUp className="w-3.5 h-3.5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
              <span>Self-Improving Model</span>
            </span>
          )}
        </div>
        <ArrowUpRight className="w-4 h-4 text-[#94A3B8] group-hover:text-white group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all" />
      </div>
    </div>
  );
}

export function AITeamSection() {
  return (
    <section className="py-20 relative border-t border-[rgba(255,255,255,0.08)] bg-[#050816]/60 backdrop-blur-md">
      {/* Glowing Divider Header Line */}
      <div className="glowing-divider-line mb-14" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-14">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.04] border border-[rgba(255,255,255,0.08)] text-xs font-semibold text-[#22D3EE] backdrop-blur-md shadow-[0_0_20px_rgba(34,211,238,0.15)]">
            <Sparkles className="w-4 h-4 text-[#22D3EE]" />
            <span>Integrated AI Agent Architecture</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight">
            Meet Your <span className="animated-hero-heading inline-block">AI Finance Team</span>
          </h2>

          <p className="text-base sm:text-lg text-[#94A3B8] leading-relaxed max-w-2xl mx-auto">
            Four intelligent capabilities work together to reduce manual invoice work and help your finance team focus only on important exceptions.
          </p>
        </div>

        {/* 4-COLUMN RESPONSIVE 3D CARD GRID */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {AGENTS_DATA.map((agent) => (
            <Agent3DCard key={agent.id} agent={agent} />
          ))}
        </div>

      </div>
    </section>
  );
}
