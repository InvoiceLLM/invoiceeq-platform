"use client";

import React, { useMemo, useState } from "react";
import { Search, ChevronRight, BookOpen, Bot, Sparkles, Ticket } from "lucide-react";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import { HELP_SECTIONS as TRAINER_HELP_SECTIONS, type HelpSection } from "./content/trainer-guide";
import { AUDITOR_HELP_SECTIONS } from "./content/auditor-guide";
import { WEBHOOKS_HELP_SECTIONS } from "./content/webhooks-guide";
import { INBOUND_EMAIL_HELP_SECTIONS } from "./content/inbound-email-guide";
import { OUTBOUND_EMAIL_HELP_SECTIONS } from "./content/outbound-email-guide";
import { AUTOPILOT_HELP_SECTIONS } from "./content/autopilot-guide";
import { SETTINGS_HELP_SECTIONS } from "./content/settings-guide";
import { SupportChatWindow } from "@/components/help/SupportChatWindow";
import { TicketHistoryPanel } from "@/components/help/TicketHistoryPanel";

const HELP_SECTIONS: HelpSection[] = [
  ...TRAINER_HELP_SECTIONS,
  ...AUDITOR_HELP_SECTIONS,
  ...AUTOPILOT_HELP_SECTIONS,
  ...INBOUND_EMAIL_HELP_SECTIONS,
  ...OUTBOUND_EMAIL_HELP_SECTIONS,
  ...SETTINGS_HELP_SECTIONS,
  ...WEBHOOKS_HELP_SECTIONS,
];

export default function HelpPage() {
  usePageHeader({
    title: "Help Center",
    subtitle: "Step-by-step guides for using the platform, with real app screenshots and AI support assistant.",
  });

  // Default view is 'guides' (Knowledge Base) as required by specification.
  // FE Gap 404: "tickets" tab added, default view unchanged.
  const [activeTab, setActiveTab] = useState<"guides" | "assistant" | "tickets">("guides");
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string>(HELP_SECTIONS[0].id);

  const normalizedQuery = query.trim().toLowerCase();

  const filteredSections: HelpSection[] = useMemo(() => {
    if (!normalizedQuery) return HELP_SECTIONS;
    return HELP_SECTIONS.filter((s) =>
      s.title.toLowerCase().includes(normalizedQuery) ||
      s.keywords.some((k) => k.toLowerCase().includes(normalizedQuery)) ||
      s.searchText.toLowerCase().includes(normalizedQuery)
    );
  }, [normalizedQuery]);

  const activeSection =
    filteredSections.find((s) => s.id === activeId) ?? filteredSections[0];

  return (
    <div className="space-y-6">
      {/* Top Mode / Tab Switcher */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-[#222D3D] pb-4">
        <div className="flex items-center gap-2 bg-[#0B0F17] p-1 rounded-xl border border-[#222D3D]" role="tablist">
          <button
            id="tab-btn-guides"
            role="tab"
            aria-selected={activeTab === "guides"}
            onClick={() => setActiveTab("guides")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all ${
              activeTab === "guides"
                ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                : "text-slate-400 hover:text-white hover:bg-white/5"
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Knowledge Base Guides</span>
          </button>
          <button
            id="tab-btn-assistant"
            role="tab"
            aria-selected={activeTab === "assistant"}
            onClick={() => setActiveTab("assistant")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all ${
              activeTab === "assistant"
                ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white shadow-md shadow-cyan-500/20"
                : "text-slate-400 hover:text-white hover:bg-white/5"
            }`}
          >
            <Bot className="w-3.5 h-3.5 text-cyan-400" />
            <span>AI Support Assistant</span>
            <span className="px-1.5 py-0.5 rounded text-[9px] bg-cyan-400/20 text-cyan-300 font-mono font-normal">
              Ask SAGE
            </span>
          </button>
          {/* FE Gap 404: Ticket History & Status tab */}
          <button
            id="tab-btn-tickets"
            role="tab"
            aria-selected={activeTab === "tickets"}
            onClick={() => setActiveTab("tickets")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all ${
              activeTab === "tickets"
                ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                : "text-slate-400 hover:text-white hover:bg-white/5"
            }`}
          >
            <Ticket className="w-3.5 h-3.5" />
            <span>My Tickets</span>
          </button>
        </div>

        {activeTab === "guides" && (
          <div className="relative w-full sm:w-80">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              id="help-guide-search"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search help guides (e.g. 'rules', 'audit', 'webhook')..."
              className="w-full bg-[#151B26] border border-[#222D3D] rounded-xl pl-10 pr-4 py-2 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-600/60 focus:ring-1 focus:ring-blue-600/20"
            />
          </div>
        )}
      </div>

      {/* Tab 1: Knowledge Base Guides (Default View) */}
      {activeTab === "guides" && (
        <div id="help-guides-container" className="grid grid-cols-1 lg:grid-cols-4 gap-6 animate-in fade-in duration-200">
          {/* Left: topic list */}
          <div className="lg:col-span-1 space-y-1">
            {filteredSections.length === 0 && (
              <p className="text-xs text-slate-500 p-3">No topics match "{query}".</p>
            )}
            {filteredSections.map((s) => (
              <button
                key={s.id}
                id={`guide-item-${s.id}`}
                onClick={() => setActiveId(s.id)}
                className={`w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium flex items-center justify-between gap-2 transition-colors ${
                  activeSection?.id === s.id
                    ? "bg-blue-600/15 text-blue-300 border border-blue-600/30"
                    : "text-slate-400 hover:text-white hover:bg-[#151B26] border border-transparent"
                }`}
              >
                <span>{s.title}</span>
                <ChevronRight className="w-3.5 h-3.5 shrink-0 opacity-60" />
              </button>
            ))}
          </div>

          {/* Right: article content */}
          <div className="lg:col-span-3">
            {activeSection ? (
              <article className="glass-panel bg-[#151B26] bg-opacity-75 border border-[#222D3D] rounded-xl p-6 space-y-5">
                <div>
                  <h2 className="text-lg font-bold text-white">{activeSection.title}</h2>
                  {activeSection.subtitle && (
                    <p className="text-xs text-slate-400 mt-1">{activeSection.subtitle}</p>
                  )}
                </div>
                <div className="space-y-5">{activeSection.body}</div>
              </article>
            ) : (
              <div className="glass-panel bg-[#151B26] bg-opacity-75 border border-[#222D3D] rounded-xl p-10 text-center text-sm text-slate-500">
                Select a topic from the list to view its guide.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: AI Support Assistant & Troubleshooting */}
      {activeTab === "assistant" && (
        <div id="help-assistant-container" className="animate-in fade-in duration-200">
          <SupportChatWindow />
        </div>
      )}

      {/* Tab 3 (FE Gap 404): Ticket History & Status */}
      {activeTab === "tickets" && (
        <div id="help-tickets-container" className="animate-in fade-in duration-200">
          <TicketHistoryPanel />
        </div>
      )}
    </div>
  );
}
