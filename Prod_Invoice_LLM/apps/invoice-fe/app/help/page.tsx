"use client";

import React, { useMemo, useState } from "react";
import { Search, GraduationCap, ChevronRight } from "lucide-react";
import { HELP_SECTIONS as TRAINER_HELP_SECTIONS, type HelpSection } from "./content/trainer-guide";
import { AUDITOR_HELP_SECTIONS } from "./content/auditor-guide";

const HELP_SECTIONS: HelpSection[] = [
  ...TRAINER_HELP_SECTIONS,
  ...AUDITOR_HELP_SECTIONS,
];

export default function HelpPage() {
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

  // Keep the active section valid as the filtered list changes; default to the
  // first match so searching always shows something instead of a blank pane.
  const activeSection =
    filteredSections.find((s) => s.id === activeId) ?? filteredSections[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-white tracking-wide flex items-center gap-2">
          <GraduationCap className="w-6 h-6 text-blue-400" />
          Help Center
        </h1>
        <p className="text-xs text-slate-400">
          Step-by-step guides for using the platform, with screenshots from the real app.
        </p>
      </div>

      {/* Search bar — client-side filter over section title/keywords/body text.
          A chat-style "ask a question" assistant would need a new backend
          endpoint (LLM over this guide content); scoped out for now — search
          covers the same "find the right section fast" need without that. */}
      <div className="relative max-w-xl">
        <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search help topics (e.g. 'confidence', 'commit', 'stuck')..."
          className="w-full bg-[#151B26] border border-[#222D3D] rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-600/60 focus:ring-1 focus:ring-blue-600/20"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left: topic list */}
        <div className="lg:col-span-1 space-y-1">
          {filteredSections.length === 0 && (
            <p className="text-xs text-slate-500 p-3">No topics match "{query}".</p>
          )}
          {filteredSections.map((s) => (
            <button
              key={s.id}
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
              Nothing matches that search.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
