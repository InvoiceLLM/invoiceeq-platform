"use client";

import React, { useEffect } from "react";
import { X, ExternalLink, Activity, Sparkles } from "lucide-react";
import { appHref } from "../../lib/billingPlans";

interface FlowsModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialFlowId?: string;
}

export function FlowsModal({ isOpen, onClose, initialFlowId }: FlowsModalProps) {
  const flowsUrl = appHref(`/flows${initialFlowId ? `?flow=${initialFlowId}` : ""}`);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };

    if (isOpen) {
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", handleKeyDown);
    } else {
      document.body.style.overflow = "unset";
    }

    return () => {
      document.body.style.overflow = "unset";
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 md:p-6 bg-black/85 backdrop-blur-xl animate-in fade-in duration-200">
      
      {/* Modal Container */}
      <div className="relative w-full max-w-7xl h-[92vh] rounded-2xl bg-[#050816] border border-white/20 shadow-[0_0_50px_rgba(34,211,238,0.25)] flex flex-col overflow-hidden">
        
        {/* Header Bar */}
        <div className="px-4 sm:px-6 py-3.5 border-b border-white/10 bg-[#0A1124]/90 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-[#3B82F6] to-[#22D3EE] text-white shadow-[0_0_15px_rgba(34,211,238,0.4)]">
              <Activity className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base sm:text-lg font-bold text-white tracking-tight">
                  System Architecture & Agent Flow Simulator
                </h3>
                <span className="hidden sm:inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-[#22D3EE]/15 border border-[#22D3EE]/30 text-[#22D3EE]">
                  <Sparkles className="w-3 h-3" /> Live Simulator
                </span>
              </div>
              <p className="text-xs text-[#94A3B8] hidden sm:block">
                Interactive real-time visualization of Inbound, Outbound, Chat & Rule Injection pipelines
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Open Full Screen in New Tab */}
            <a
              href={flowsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-[#CBD5E1] hover:text-white flex items-center gap-1.5 transition-all"
              title="Open full page in new tab"
            >
              <span className="hidden xs:inline">Open Full Tab</span>
              <ExternalLink className="w-3.5 h-3.5 text-[#22D3EE]" />
            </a>

            {/* Close Button */}
            <button
              onClick={onClose}
              className="p-2 rounded-lg bg-white/5 hover:bg-white/15 border border-white/10 text-slate-400 hover:text-white transition-all"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Live Iframe Viewport */}
        <div className="relative flex-1 bg-[#050816] overflow-hidden">
          <iframe
            src={flowsUrl}
            title="System Flow Visualization"
            className="w-full h-full border-none"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          />
        </div>

        {/* Modal Footer Info Bar */}
        <div className="px-4 py-2 border-t border-white/10 bg-[#0A1124]/90 flex items-center justify-between text-[11px] text-[#94A3B8]">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#10B981] animate-ping" />
            <span>Interactive Simulator Active • Click controls or node cards inside the visualizer</span>
          </span>
          <span className="font-mono hidden sm:inline text-[#22D3EE]">
            {flowsUrl}
          </span>
        </div>

      </div>

    </div>
  );
}
