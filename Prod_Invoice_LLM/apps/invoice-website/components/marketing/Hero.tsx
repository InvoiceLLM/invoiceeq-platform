"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import {
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Zap,
  Cpu,
  FileCheck,
  CheckCircle2,
  Lock,
  RotateCcw,
  Database,
  Play,
  ScanLine,
  MessageSquareText,
  BrainCircuit,
  Bot,
  ShieldAlert,
  Workflow,
} from "lucide-react";

interface HeroProps {
  onOpenFlowsModal?: () => void;
}

interface SampleInvoice {
  id: string;
  vendor: string;
  amount: string;
  poNumber: string;
  lineItemsCount: number;
  confidence: string;
  status: "VERIFIED" | "MATCHED" | "AUDITED";
  rawJson: string;
  taxBreakdown: { item: string; rate: string; tax: string; total: string }[];
}

const SAMPLE_INVOICES: SampleInvoice[] = [
  {
    id: "INV-9842",
    vendor: "TechCorp Solutions Inc",
    amount: "$42,500.00",
    poNumber: "PO-88219",
    lineItemsCount: 4,
    confidence: "99.8%",
    status: "VERIFIED",
    rawJson: JSON.stringify(
      {
        invoice_number: "INV-9842",
        vendor_name: "TechCorp Solutions Inc",
        total_amount: 42500.0,
        currency: "USD",
        po_number: "PO-88219",
        line_items_matched: 4,
        consensus_score: 0.998,
        routing: "AUTOMATED_APPROVAL",
      },
      null,
      2
    ),
    taxBreakdown: [
      { item: "Server Rack Modules x4", rate: "$8,500.00", tax: "8%", total: "$36,720.00" },
      { item: "Gigabit Switch 48-Port", rate: "$5,780.00", tax: "0%", total: "$5,780.00" },
    ],
  },
  {
    id: "FRT-1048",
    vendor: "Global Freight Logistics",
    amount: "$18,750.50",
    poNumber: "PO-91042",
    lineItemsCount: 2,
    confidence: "99.4%",
    status: "MATCHED",
    rawJson: JSON.stringify(
      {
        invoice_number: "FRT-1048",
        vendor_name: "Global Freight Logistics",
        total_amount: 18750.5,
        currency: "USD",
        po_number: "PO-91042",
        line_items_matched: 2,
        consensus_score: 0.994,
        routing: "AUTOMATED_APPROVAL",
      },
      null,
      2
    ),
    taxBreakdown: [
      { item: "Air Cargo Transit (EU->US)", rate: "$14,000.00", tax: "10%", total: "$15,400.00" },
      { item: "Customs Brokerage Duty", rate: "$3,350.50", tax: "0%", total: "$3,350.50" },
    ],
  },
  {
    id: "SUB-7721",
    vendor: "Azure Cloud Enterprise Services",
    amount: "$9,200.00",
    poNumber: "PO-77011",
    lineItemsCount: 3,
    confidence: "99.9%",
    status: "VERIFIED",
    rawJson: JSON.stringify(
      {
        invoice_number: "SUB-7721",
        vendor_name: "Azure Cloud Enterprise Services",
        total_amount: 9200.0,
        currency: "USD",
        po_number: "PO-77011",
        line_items_matched: 3,
        consensus_score: 0.999,
        routing: "AUTOMATED_APPROVAL",
      },
      null,
      2
    ),
    taxBreakdown: [
      { item: "Container Apps Cluster Usage", rate: "$5,200.00", tax: "0%", total: "$5,200.00" },
      { item: "PostgreSQL Flexible Instance", rate: "$4,000.00", tax: "0%", total: "$4,000.00" },
    ],
  },
];

const HERO_CAPABILITIES = [
  {
    name: "NOVA",
    subtitle: "Smart Invoice Extraction",
    icon: ScanLine,
    tooltip: "Reads PDFs and converts invoice details into structured data.",
    gradient: "from-[#3B82F6] to-[#22D3EE]",
    activeBorder: "border-[#22D3EE]/70 shadow-[0_0_25px_rgba(34,211,238,0.45)] bg-[#22D3EE]/15 text-white",
  },
  {
    name: "SENTINEL",
    subtitle: "Anomaly & Duplicate Detection",
    icon: ShieldCheck,
    tooltip: "Flags calculation errors, suspicious values and duplicate invoices.",
    gradient: "from-[#10B981] to-[#14B8A6]",
    activeBorder: "border-[#10B981]/70 shadow-[0_0_25px_rgba(16,185,129,0.45)] bg-[#10B981]/15 text-white",
  },
  {
    name: "SAGE",
    subtitle: "Chat With Your Invoices",
    icon: MessageSquareText,
    tooltip: "Answers invoice and finance questions in natural language.",
    gradient: "from-[#8B5CF6] to-[#3B82F6]",
    activeBorder: "border-[#8B5CF6]/70 shadow-[0_0_25px_rgba(139,92,246,0.45)] bg-[#8B5CF6]/15 text-white",
  },
  {
    name: "EVOLVE",
    subtitle: "Learns From Corrections",
    icon: BrainCircuit,
    tooltip: "Uses auditor corrections to improve future extraction.",
    gradient: "from-[#6366F1] to-[#8B5CF6]",
    activeBorder: "border-[#6366F1]/70 shadow-[0_0_25px_rgba(99,102,241,0.45)] bg-[#6366F1]/15 text-white",
  },
];

export function Hero({ onOpenFlowsModal }: HeroProps) {
  const [selectedInvoice, setSelectedInvoice] = useState<SampleInvoice>(SAMPLE_INVOICES[0]);
  const [activeStep, setActiveStep] = useState<number>(3);
  const [inspectorTab, setInspectorTab] = useState<"SUMMARY" | "JSON">("SUMMARY");
  const [isProcessing, setIsProcessing] = useState<boolean>(false);

  const cardRef = useRef<HTMLDivElement>(null);
  const [rotateX, setRotateX] = useState<number>(-8);
  const [rotateY, setRotateY] = useState<number>(10);
  const [scrollTiltX, setScrollTiltX] = useState<number>(0);
  const [scrollScale, setScrollScale] = useState<number>(0.96);
  const [isHovered, setIsHovered] = useState<boolean>(false);
  const [highlightedPillIndex, setHighlightedPillIndex] = useState<number>(0);

  // 1. Initial Page Load 3D Opening Animation (Entrance Wave)
  useEffect(() => {
    const introTimer1 = setTimeout(() => {
      setRotateX(4);
      setRotateY(-5);
      setScrollScale(1);
    }, 200);

    const introTimer2 = setTimeout(() => {
      setRotateX(0);
      setRotateY(0);
    }, 900);

    return () => {
      clearTimeout(introTimer1);
      clearTimeout(introTimer2);
    };
  }, []);

  // 2. Sequential 1.5s Staggered Highlight Wave for Hero Capability Cards
  useEffect(() => {
    const pillTimer = setInterval(() => {
      setHighlightedPillIndex((prev) => (prev + 1) % 4);
    }, 1500);

    return () => clearInterval(pillTimer);
  }, []);

  // 3. Scroll-Driven 3D Interactive Parallax & Dynamic Tilt
  useEffect(() => {
    const handleScroll = () => {
      if (!cardRef.current) return;
      const rect = cardRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight || 800;
      
      const centerOffset = rect.top + rect.height / 2 - viewportHeight / 2;
      const tilt = Math.max(-10, Math.min(10, (centerOffset / viewportHeight) * 14));
      const distFromCenter = Math.abs(centerOffset) / viewportHeight;
      const scale = Math.max(0.96, 1 - distFromCenter * 0.04);

      setScrollTiltX(tilt);
      setScrollScale(scale);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();

    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    setIsHovered(true);
    const rect = cardRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const mouseX = e.clientX - centerX;
    const mouseY = e.clientY - centerY;

    const rX = -(mouseY / (rect.height / 2)) * 7;
    const rY = (mouseX / (rect.width / 2)) * 7;

    setRotateX(rX);
    setRotateY(rY);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    setRotateX(0);
    setRotateY(0);
  };

  const runLiveSimulation = (invoice: SampleInvoice) => {
    setSelectedInvoice(invoice);
    setIsProcessing(true);
    setActiveStep(0);

    const interval = setInterval(() => {
      setActiveStep((prev) => {
        if (prev >= 3) {
          clearInterval(interval);
          setIsProcessing(false);
          return 3;
        }
        return prev + 1;
      });
    }, 600);
  };

  return (
    <section className="relative overflow-hidden pt-6 pb-20 lg:pt-8 lg:pb-28">
      {/* Blurred Glowing Circles Behind Heading */}
      <div className="pointer-events-none absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 flex items-center justify-center -z-10">
        <div className="w-[450px] h-[450px] rounded-full bg-[#3B82F6]/15 blur-[140px] animate-pulse-beam" />
        <div className="w-[400px] h-[400px] rounded-full bg-[#8B5CF6]/15 blur-[140px] -ml-24 -mt-20" />
        <div className="w-[420px] h-[420px] rounded-full bg-[#22D3EE]/15 blur-[140px] -mr-24 -mb-20" />
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Main Title & Subtitle */}
        <div className="text-center max-w-4xl mx-auto space-y-6">
          
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-[rgba(255,255,255,0.08)] bg-white/[0.04] backdrop-blur-md text-xs font-semibold text-[#22D3EE] shadow-[0_0_20px_rgba(34,211,238,0.2)]">
            <Sparkles className="w-4 h-4 text-[#22D3EE] animate-spin" style={{ animationDuration: "8s" }} />
            <span>AI-Powered Finance Workspace</span>
          </div>

          {/* Executive Corporate Hero Heading */}
          <h1 className="text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.25]">
            <span className="animated-hero-heading inline-block">Automated Invoice Intelligence</span>
          </h1>

          {/* 4 Hero Feature Capability Cards (NOVA, SENTINEL, SAGE, EVOLVE) */}
          <div className="pt-2 grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-4xl mx-auto text-xs">
            {HERO_CAPABILITIES.map((cap, idx) => {
              const Icon = cap.icon;
              const isHighlight = highlightedPillIndex === idx;

              return (
                <div
                  key={cap.name}
                  onClick={() => setHighlightedPillIndex(idx)}
                  className={`group relative flex flex-col items-center justify-center p-3 rounded-xl border transition-all duration-300 cursor-pointer ${
                    isHighlight
                      ? `-translate-y-1.5 scale-[1.03] ${cap.activeBorder} z-20`
                      : "bg-white/5 border-white/10 text-[#CBD5E1] hover:text-white hover:-translate-y-1 hover:border-white/20"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div
                      className={`p-1.5 rounded-lg bg-gradient-to-br ${cap.gradient} text-white transition-all duration-300 ${
                        isHighlight ? "scale-110 rotate-6 shadow-md" : "group-hover:rotate-6"
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                    <div className="text-left">
                      <span className="font-extrabold text-white text-xs block leading-tight">
                        {cap.name}
                      </span>
                      <span className="text-[10px] text-[#94A3B8] font-medium block leading-tight truncate">
                        {cap.subtitle}
                      </span>
                    </div>
                  </div>

                  {/* Tooltip Popup on Hover */}
                  <div className="pointer-events-none absolute left-1/2 -bottom-12 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-all duration-300 z-30 w-52 p-2 rounded-lg bg-[#0A1124] border border-white/20 text-[10px] text-[#CBD5E1] text-center shadow-xl backdrop-blur-md">
                    {cap.tooltip}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Subheading: Max 2 lines on desktop */}
          <p className="text-base sm:text-lg text-[#94A3B8] max-w-2xl mx-auto leading-relaxed pt-1">
            Extract, verify and understand every invoice using intelligent AI agents — inside your own secure enterprise workspace.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
            <Link
              href="/login"
              className="btn-primary-gradient w-full sm:w-auto text-base px-8 py-3.5 flex items-center justify-center gap-3 group"
            >
              <span>Start Free Trial</span>
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </Link>
            <a
              href="#pipeline-demo"
              className="btn-secondary-glass w-full sm:w-auto text-base px-8 py-3.5 flex items-center justify-center gap-2"
            >
              <Play className="w-4 h-4 text-[#22D3EE] fill-[#22D3EE]" />
              <span>Simulate Pipeline</span>
            </a>
            <button
              onClick={() => {
                if (onOpenFlowsModal) {
                  onOpenFlowsModal();
                } else {
                  const el = document.getElementById("architecture-flows");
                  el?.scrollIntoView({ behavior: "smooth" });
                }
              }}
              className="btn-secondary-glass w-full sm:w-auto text-base px-6 py-3.5 flex items-center justify-center gap-2 group border-[#22D3EE]/30 hover:border-[#22D3EE]"
            >
              <Workflow className="w-4 h-4 text-[#22D3EE] group-hover:rotate-12 transition-transform" />
              <span>Architecture Flow</span>
            </button>
          </div>

        </div>

        {/* INTERACTIVE PIPELINE DEMO & CONSOLE */}
        <div id="pipeline-demo" className="mt-14 max-w-5xl mx-auto perspective-1000">
          <div
            ref={cardRef}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            style={{
              transform: `perspective(1000px) rotateX(${
                isHovered ? rotateX : rotateX + scrollTiltX
              }deg) rotateY(${rotateY}deg) scale(${scrollScale})`,
              transition: isHovered
                ? "transform 0.15s cubic-bezier(0.2, 0.8, 0.2, 1)"
                : "transform 0.6s cubic-bezier(0.16, 1, 0.3, 1)",
            }}
            className="preserve-3d rounded-2xl glass-card-enterprise p-5 sm:p-7 relative overflow-hidden"
          >
            {/* Console Header Bar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-5 border-b border-[rgba(255,255,255,0.08)] gap-3">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-rose-500/80" />
                  <div className="w-3 h-3 rounded-full bg-amber-500/80" />
                  <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
                </div>
                <span className="text-xs font-mono text-[#94A3B8] ml-2">workspace.invoice-ai.internal</span>
              </div>

              {/* Sample Invoice Selector */}
              <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0">
                <span className="text-xs text-[#94A3B8] font-medium shrink-0">Sample Invoice:</span>
                {SAMPLE_INVOICES.map((inv) => (
                  <button
                    key={inv.id}
                    onClick={() => runLiveSimulation(inv)}
                    className={`text-xs px-3 py-1.5 rounded-lg border font-mono transition-all duration-200 shrink-0 ${
                      selectedInvoice.id === inv.id
                        ? "bg-[#3B82F6]/20 text-[#22D3EE] border-[#3B82F6]/50 shadow-[0_0_12px_rgba(59,130,246,0.3)]"
                        : "bg-white/5 text-[#94A3B8] border-white/10 hover:text-white"
                    }`}
                  >
                    {inv.id}
                  </button>
                ))}
              </div>
            </div>

            {/* 4 CUSTOMER-FRIENDLY PIPELINE STAGES */}
            <div className="py-6 border-b border-[rgba(255,255,255,0.08)]">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 relative">
                
                {/* Stage 1: Secure Upload */}
                <div
                  className={`p-3.5 rounded-xl border transition-all duration-300 relative ${
                    activeStep >= 0
                      ? "bg-[#3B82F6]/10 border-[#3B82F6]/50 text-white shadow-[0_0_20px_rgba(59,130,246,0.2)]"
                      : "bg-white/5 border-white/10 text-[#94A3B8]"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-semibold mb-1">
                    <span>1. Secure Upload</span>
                    {activeStep >= 0 && <CheckCircle2 className="w-3.5 h-3.5 text-[#22D3EE]" />}
                  </div>
                  <p className="text-[11px] text-[#94A3B8]">Encrypted Ingestion</p>
                  <div className="mt-2 text-[10px] font-mono text-[#3B82F6]">AES-256 Storage</div>
                </div>

                {/* Stage 2: NOVA Extraction */}
                <div
                  className={`p-3.5 rounded-xl border transition-all duration-300 relative ${
                    activeStep >= 1
                      ? "bg-[#3B82F6]/10 border-[#3B82F6]/50 text-white shadow-[0_0_20px_rgba(59,130,246,0.2)]"
                      : "bg-white/5 border-white/10 text-[#94A3B8]"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-semibold mb-1">
                    <span>2. NOVA Extraction</span>
                    {activeStep >= 1 && <CheckCircle2 className="w-3.5 h-3.5 text-[#22D3EE]" />}
                  </div>
                  <p className="text-[11px] text-[#94A3B8]">Fields & Line Items</p>
                  <div className="mt-2 text-[10px] font-mono text-[#22D3EE]">Smart Parsing</div>
                </div>

                {/* Stage 3: SENTINEL Review */}
                <div
                  className={`p-3.5 rounded-xl border transition-all duration-300 relative ${
                    activeStep >= 2
                      ? "bg-[#8B5CF6]/10 border-[#8B5CF6]/50 text-white shadow-[0_0_20px_rgba(139,92,246,0.2)]"
                      : "bg-white/5 border-white/10 text-[#94A3B8]"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-semibold mb-1">
                    <span>3. SENTINEL Review</span>
                    {activeStep >= 2 && <CheckCircle2 className="w-3.5 h-3.5 text-[#8B5CF6]" />}
                  </div>
                  <p className="text-[11px] text-[#94A3B8]">Errors & Duplicate Checks</p>
                  <div className="mt-2 text-[10px] font-mono text-[#8B5CF6]">Risk Score {selectedInvoice.confidence}</div>
                </div>

                {/* Stage 4: Verified Result */}
                <div
                  className={`p-3.5 rounded-xl border transition-all duration-300 relative ${
                    activeStep >= 3
                      ? "bg-[#10B981]/10 border-[#10B981]/50 text-white shadow-[0_0_20px_rgba(16,185,129,0.2)]"
                      : "bg-white/5 border-white/10 text-[#94A3B8]"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-semibold mb-1">
                    <span>4. Verified Result</span>
                    {activeStep >= 3 && <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981]" />}
                  </div>
                  <p className="text-[11px] text-[#94A3B8]">Ready for Approval</p>
                  <div className="mt-2 text-[10px] font-mono text-[#10B981]">{selectedInvoice.status}</div>
                </div>

              </div>
            </div>

            {/* INSPECTOR DRAWER */}
            <div className="mt-5 grid grid-cols-1 lg:grid-cols-12 gap-5">
              
              <div className="lg:col-span-5 p-4 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[#050816]/80 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider">Active Sample</span>
                  <span className="text-xs px-2.5 py-0.5 rounded bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/30 font-semibold">
                    {selectedInvoice.status}
                  </span>
                </div>

                <div>
                  <h4 className="text-xl font-bold text-white">{selectedInvoice.vendor}</h4>
                  <p className="text-xs font-mono text-[#94A3B8] mt-0.5">Invoice #{selectedInvoice.id} • PO #{selectedInvoice.poNumber}</p>
                </div>

                {/* SAGE Ready Status Chip */}
                {activeStep >= 3 && (
                  <div className="p-2.5 rounded-xl bg-[#8B5CF6]/15 border border-[#8B5CF6]/40 text-xs font-semibold text-[#C084FC] flex items-center justify-between shadow-[0_0_20px_rgba(139,92,246,0.25)]">
                    <span className="flex items-center gap-2">
                      <Bot className="w-4 h-4 text-[#8B5CF6] animate-bounce" style={{ animationDuration: "2s" }} />
                      <span>SAGE Ready — Ask questions about this invoice</span>
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-[#8B5CF6]/30 border border-[#8B5CF6]/50 text-white font-mono shrink-0 ml-2">
                      Active
                    </span>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3 pt-2">
                  <div className="p-2.5 rounded-lg bg-white/5 border border-white/10">
                    <span className="text-[10px] text-[#94A3B8] uppercase">Extracted Total</span>
                    <p className="text-lg font-bold text-[#22D3EE] font-mono">{selectedInvoice.amount}</p>
                  </div>
                  <div className="p-2.5 rounded-lg bg-white/5 border border-white/10">
                    <span className="text-[10px] text-[#94A3B8] uppercase">Field Precision</span>
                    <p className="text-lg font-bold text-[#3B82F6] font-mono">{selectedInvoice.confidence}</p>
                  </div>
                </div>

                <button
                  onClick={() => runLiveSimulation(selectedInvoice)}
                  disabled={isProcessing}
                  className="w-full btn-secondary-glass text-xs py-2.5 flex items-center justify-center gap-2"
                >
                  <RotateCcw className={`w-3.5 h-3.5 text-[#22D3EE] ${isProcessing ? "animate-spin" : ""}`} />
                  <span>{isProcessing ? "Processing..." : "Re-Run Extraction Test"}</span>
                </button>
              </div>

              <div className="lg:col-span-7 p-4 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[#050816]/80 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between border-b border-[rgba(255,255,255,0.08)] pb-3">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setInspectorTab("SUMMARY")}
                        className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-all ${
                          inspectorTab === "SUMMARY"
                            ? "bg-[#3B82F6]/20 text-[#22D3EE] border border-[#3B82F6]/40"
                            : "text-[#94A3B8] hover:text-white"
                        }`}
                      >
                        Line Items Breakdown
                      </button>
                      <button
                        onClick={() => setInspectorTab("JSON")}
                        className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-all ${
                          inspectorTab === "JSON"
                            ? "bg-[#3B82F6]/20 text-[#22D3EE] border border-[#3B82F6]/40"
                            : "text-[#94A3B8] hover:text-white"
                        }`}
                      >
                        Agent JSON Consensus
                      </button>
                    </div>

                    <span className="text-[11px] text-[#94A3B8] font-mono hidden sm:inline">LangGraph Active</span>
                  </div>

                  {inspectorTab === "SUMMARY" && (
                    <div className="mt-3 space-y-2">
                      <div className="text-[13px] font-semibold text-[#94A3B8] tracking-[0.3px] grid grid-cols-12 px-2 pb-1 border-b border-white/10 items-center">
                        <span className="col-span-6">Description</span>
                        <span className="col-span-2 text-right">Rate</span>
                        <span className="col-span-2 text-right">Tax</span>
                        <span className="col-span-2 text-right">Total</span>
                      </div>
                      {selectedInvoice.taxBreakdown.map((row, idx) => (
                        <div
                          key={idx}
                          className="text-[13px] font-normal leading-[1.5] grid grid-cols-12 px-2 py-1.5 rounded bg-white/5 text-[#CBD5E1] border border-white/10 items-center"
                        >
                          <span className="col-span-6 truncate text-white">{row.item}</span>
                          <span className="col-span-2 text-right text-[#94A3B8] tabular-nums font-mono">{row.rate}</span>
                          <span className="col-span-2 text-right text-[#3B82F6] tabular-nums font-mono">{row.tax}</span>
                          <span className="col-span-2 text-right text-[#22D3EE] font-semibold tabular-nums font-mono">{row.total}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {inspectorTab === "JSON" && (
                    <div className="mt-3 p-3 rounded-lg bg-[#050816] border border-white/10 font-mono text-xs text-[#22D3EE] overflow-x-auto max-h-[160px]">
                      <pre>{selectedInvoice.rawJson}</pre>
                    </div>
                  )}
                </div>

                <div className="pt-3 border-t border-[rgba(255,255,255,0.08)] flex items-center justify-between text-[11px] text-[#94A3B8]">
                  <span className="flex items-center gap-1.5">
                    <Lock className="w-3 h-3 text-[#10B981]" />
                    VNet Isolated Tenant Sandbox
                  </span>
                  <span className="text-[#94A3B8] font-mono">Status 200 OK</span>
                </div>

              </div>

            </div>

          </div>
        </div>

      </div>
    </section>
  );
}
