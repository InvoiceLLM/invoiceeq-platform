"use client";

import React, { useState } from "react";
import { Plus, X, Tag } from "lucide-react";

interface TagSelectorProps {
  tags: string[];
  onChange: (tags: string[]) => void;
}

export default function TagSelector({ tags = [], onChange }: TagSelectorProps) {
  const [inputVal, setInputVal] = useState("");

  const handleAddTag = () => {
    let cleanTag = inputVal.trim();
    if (!cleanTag) return;

    // Ensure it starts with #
    if (!cleanTag.startsWith("#")) {
      cleanTag = `#${cleanTag}`;
    }

    // Only add if it doesn't already exist
    if (!tags.includes(cleanTag)) {
      const newTags = [...tags, cleanTag];
      onChange(newTags);
    }
    
    setInputVal("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddTag();
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    const newTags = tags.filter((t) => t !== tagToRemove);
    onChange(newTags);
  };

  return (
    <div className="glass-panel p-4 rounded-xl space-y-3">
      {/* Header Info.
          FE Gap 113 item 2: this panel was roughly twice the height it needed
          to be. The description is now a single small-font line sitting under
          the title (was a full-size `text-xs` sentence on its own block), and
          padding/spacing dropped a step (p-5/space-y-4 -> p-4/space-y-3). */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 text-white">
          <Tag className="w-4 h-4 text-accent-blue" />
          <h3 className="text-sm font-semibold tracking-wide">Batch Ingestion Tags</h3>
        </div>
        <p className="text-[11px] text-slate-500">Labels applied to this batch.</p>
      </div>

      {/* Input controls */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type="text"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type tag (e.g. Q1-2026) and hit Enter"
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] transition-all"
          />
        </div>
        <button
          onClick={handleAddTag}
          type="button"
          className="flex items-center justify-center p-2 rounded-lg bg-accent-blue/15 hover:bg-accent-blue/25 border border-accent-blue/30 hover:border-accent-blue/50 text-[#3B82F6] transition-all"
          title="Add Tag"
        >
          <Plus className="w-4.5 h-4.5" />
        </button>
      </div>

      {/* Tag Chips List.
          FE Gap 113 item 2: the "No active tags defined. Invoices will use
          default indexing." empty state is gone, and the row itself is only
          rendered once there is at least one chip -- an empty chip row already
          communicates "no tags" without occupying a line of its own. */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tags.map((tag) => (
            <div
              key={tag}
              className="flex items-center gap-1 bg-[#1E293B] border border-[#222D3D] hover:bg-[#334155] rounded-full px-3 py-1 text-xs text-slate-300 transition-all select-none group"
            >
              <span>{tag}</span>
              <button
                type="button"
                onClick={() => handleRemoveTag(tag)}
                className="text-slate-500 hover:text-white rounded-full p-0.5 focus:outline-none transition-colors"
                title={`Remove ${tag}`}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
