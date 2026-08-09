"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import {
  Sparkles,
  ArrowRight,
  ChevronDown,
  ShieldCheck,
  Zap,
  Cpu,
  CheckCircle2,
  Lock,
  RotateCcw,
  Mail,
  Bot,
} from "lucide-react";

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

export function Hero() {
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

  // 2. Scroll-Driven 3D Interactive Parallax & Dynamic Tilt
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
        
        {/* Headline, single CTA and flow-diagram centrepiece (Gap 163) */}
        <div className="text-center max-w-5xl mx-auto">

          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-[rgba(255,255,255,0.08)] bg-white/[0.04] backdrop-blur-md text-xs font-semibold text-[#22D3EE] shadow-[0_0_20px_rgba(34,211,238,0.2)]">
            <Sparkles className="w-4 h-4 text-[#22D3EE] animate-spin" style={{ animationDuration: "8s" }} />
            <span>AI-Powered Finance Workspace</span>
          </div>

          {/* Single-line serif headline. `whitespace-nowrap` only from lg up so
              smaller viewports may still wrap; the step up to text-6xl is held
              back to xl because at 60px this string is ~1040px wide and would
              overflow the container at exactly the lg breakpoint (1024px). */}
          <h1 className="mt-4 text-3xl sm:text-5xl xl:text-6xl font-bold tracking-tight leading-[1.2] lg:whitespace-nowrap">
            <span className="animated-hero-heading inline-block">Invoices, understood automatically</span>
          </h1>

          <p className="mt-2 text-sm sm:text-base text-[#94A3B8] max-w-xl mx-auto leading-relaxed">
            From inbox to verified data — no manual keying.
          </p>

          {/* One primary CTA plus a quiet scroll cue down to the pipeline demo */}
          <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-5">
            <Link
              href="/login"
              className="btn-primary-gradient w-full sm:w-auto text-base px-8 py-3.5 flex items-center justify-center gap-3 group"
            >
              <span>Start Free Trial</span>
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </Link>
            <a
              href="#pipeline-demo"
              className="group flex items-center gap-2 text-sm font-semibold text-[#94A3B8] hover:text-[#22D3EE] transition-colors duration-200"
            >
              <span>See how it flows</span>
              <ChevronDown
                className="w-4 h-4 animate-bounce group-hover:text-[#22D3EE]"
                style={{ animationDuration: "2.2s" }}
              />
            </a>
          </div>

          {/* Before/after transform: a concrete invoice, not an abstract
              diagram -- replaces Gap 163's flow diagram + separate outcome
              strip with one visual that shows the actual value in one
              glance. Deliberately static (not tied to selectedInvoice below)
              -- this is a fixed, illustrative example, not another live demo. */}
          <div className="mt-9 grid grid-cols-1 lg:grid-cols-[1fr_auto_1fr] items-center gap-5 max-w-4xl mx-auto">

            {/* Before: what arrives */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-md overflow-hidden text-left shadow-[0_20px_50px_rgba(0,0,0,0.35)]">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/10">
                <span className="text-[11px] font-bold uppercase tracking-wider text-[#64748B]">What arrives</span>
                <span className="h-1.5 w-1.5 rounded-full bg-[#64748B]" />
              </div>
              <div className="flex items-center gap-1.5 px-4 py-2 border-b border-white/5 text-[11px] text-[#64748B]">
                <Mail className="w-3 h-3" />
                via email or connected apps
              </div>
              <div className="relative m-4 -rotate-1 rounded-sm bg-[#F4F1E9] p-5 text-[#2b2b28] shadow-[0_6px_20px_rgba(0,0,0,0.35)]">
                <span className="absolute top-14 right-4 rotate-6 rounded border border-[#b3413a] px-1.5 py-0.5 font-mono text-[9px] tracking-wide text-[#b3413a] opacity-70">
                  RECEIVED
                </span>
                <div className="mb-2 flex justify-between text-[10px] text-[#6b6a60]">
                  <span>INV-9842</span>
                  <span>PDF · 340KB</span>
                </div>
                <div className="mb-0.5 text-[15px] font-bold tracking-tight">TechCorp Solutions Inc.</div>
                <div className="mb-3 text-[10px] text-[#8a8878]">Invoice · Net 30 · attached to email</div>
                <div className="flex justify-between border-b border-dotted border-[#c9c6b6] py-1 text-[10px] text-[#4a4940]">
                  <span>Server Rack Module x4</span>
                  <span>$18,720.00</span>
                </div>
                <div className="flex justify-between border-b border-dotted border-[#c9c6b6] py-1 text-[10px] text-[#9c9a8c] line-through decoration-[#b3413a] decoration-wavy">
                  <span>Gigabit Switch 48-Port</span>
                  <span>$7,880.??</span>
                </div>
                <div className="flex justify-between border-b border-dotted border-[#c9c6b6] py-1 text-[10px] text-[#4a4940]">
                  <span>Installation Service</span>
                  <span>$4,200.00</span>
                </div>
                <div className="flex justify-between py-1 text-[10px] text-[#4a4940]">
                  <span>Tax</span>
                  <span>$11,700.00</span>
                </div>
                <div className="mt-2 flex justify-between border-t border-[#4a4940] pt-2 text-xs font-bold">
                  <span>Total Due</span>
                  <span>$42,5??.00</span>
                </div>
              </div>
            </div>

            {/* AI Engine core */}
            <div className="flex flex-row items-center justify-center gap-3 py-2 lg:flex-col">
              <div className="hidden h-8 w-px bg-gradient-to-b from-transparent to-white/10 lg:block" />
              <div className="relative flex items-center justify-center">
                <div className="pointer-events-none absolute h-20 w-20 rounded-full bg-[#3B82F6]/25 blur-2xl" />
                <div
                  className="pointer-events-none absolute h-[76px] w-[76px] rounded-full border border-dashed border-white/15 animate-spin"
                  style={{ animationDuration: "22s" }}
                />
                <div className="relative h-[64px] w-[64px] rounded-full border border-[#22D3EE]/45 bg-[#050816]/85 backdrop-blur-md flex items-center justify-center shadow-[0_0_30px_rgba(34,211,238,0.3)]">
                  <Cpu className="w-4 h-4 text-[#22D3EE]" />
                </div>
              </div>
              <div className="text-center">
                <div className="text-[11px] font-bold tracking-wide text-[#22D3EE]">AI Engine</div>
                <div className="font-mono text-[9px] text-[#64748B]">4 agents, 6 sec</div>
              </div>
              <div className="hidden h-8 w-px bg-gradient-to-t from-transparent to-white/10 lg:block" />
            </div>

            {/* After: what you get */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-md overflow-hidden text-left shadow-[0_20px_50px_rgba(0,0,0,0.35)]">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/10">
                <span className="text-[11px] font-bold uppercase tracking-wider text-[#10B981]">What you get</span>
                <span className="h-1.5 w-1.5 rounded-full bg-[#10B981] shadow-[0_0_8px_#10B981]" />
              </div>
              <div className="flex items-center gap-1.5 px-4 py-2 border-b border-white/5 text-[11px] text-[#64748B]">
                <Zap className="w-3 h-3" />
                synced to your systems via webhooks
              </div>
              <div className="p-4">
                <div className="flex items-baseline justify-between border-b border-white/5 py-2">
                  <span className="text-[11px] text-[#64748B]">Vendor</span>
                  <span className="text-[13px] font-semibold text-white">TechCorp Solutions Inc.</span>
                </div>
                <div className="flex items-baseline justify-between border-b border-white/5 py-2">
                  <span className="text-[11px] text-[#64748B]">Invoice #</span>
                  <span className="font-mono text-xs text-white">INV-9842</span>
                </div>
                <div className="flex items-baseline justify-between border-b border-white/5 py-2">
                  <span className="text-[11px] text-[#64748B]">PO Match</span>
                  <span className="font-mono text-xs text-white">PO-88219 ✓</span>
                </div>
                <div className="flex items-baseline justify-between py-2">
                  <span className="text-[11px] text-[#64748B]">Total</span>
                  <span className="text-[13px] font-semibold text-white">$42,500.00</span>
                </div>
                <div className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-[#10B981]/30 bg-[#10B981]/10 px-2.5 py-1.5 text-[11px] font-bold text-[#10B981]">
                  <CheckCircle2 className="w-3 h-3" />
                  Verified · 99.8% precision
                </div>
              </div>
            </div>

          </div>

          {/* Trust-signal row -- last element of the above-the-fold block */}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[11px] text-[#64748B]">
            <span className="flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-[#10B981]" />
              VNet-isolated tenant
            </span>
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-[#3B82F6]" />
              AES-256 encrypted storage
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#22D3EE]" />
              No card required to start
            </span>
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
