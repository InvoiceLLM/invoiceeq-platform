// =============================================================================
// FILE: components/chat/SqlAuditDrawer.tsx
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: When the backend query agent takes the SQL execution path it
//   returns `generated_sql` in the ChatMessage payload.  Auditors and finance
//   users need to be able to verify that the AI's numeric answer (e.g. total
//   spend) was produced by a real, deterministic database query — not a
//   hallucinated figure.  This component surfaces that query in a collapsible
//   drawer below the assistant bubble.
//   Design decisions:
//   • Collapsed by default — most users only want the answer; auditors who
//     need verification can expand it.
//   • Copy-to-clipboard — makes it easy to paste the SQL into a DB tool
//     for independent verification.
//   • Pulse indicator on the header — signals that there is live audit data
//     attached to this message.
//   Styling matches spec in feature_5_chat.md:
//     bg-[#0B0F19] text-[#10B981] border border-[#222D3D] font-mono rounded-lg p-3
// =============================================================================

"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, ClipboardCopy, Check } from "lucide-react";

interface SqlAuditDrawerProps {
  sql: string; // The raw SQL string returned by the backend query agent
}

export default function SqlAuditDrawer({ sql }: SqlAuditDrawerProps) {
  // isOpen: controls whether the SQL code block is visible.
  // Starts collapsed so it doesn't visually dominate the chat stream.
  const [isOpen, setIsOpen] = useState(false);

  // copied: tracks clipboard state to show a 2-second "Copied!" confirmation.
  // Avoids adding a third-party toast library just for this one interaction.
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      // Auto-reset the "Copied!" label after 2s so it's ready for re-use
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API may be unavailable in some browser security contexts;
      // fail silently rather than throwing an unhandled error.
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-[#222D3D] overflow-hidden">
      {/* ── Accordion Toggle Header ──────────────────────────────────────── */}
      {/* WHY button not div: native <button> gives keyboard accessibility
          (Enter/Space to toggle) and the correct aria role for free. */}
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className="
          w-full flex items-center justify-between
          px-4 py-2.5
          bg-[#0F172A]/80 hover:bg-[#1E293B]/60
          text-xs font-mono text-slate-400 hover:text-slate-200
          transition-colors duration-150
          focus:outline-none
        "
        aria-expanded={isOpen}       // Screen reader knows the expanded state
        aria-controls="sql-audit-body" // Associates the button with its panel
      >
        <span className="flex items-center gap-2">
          {/* Pulsing emerald dot — signals live audit data is available */}
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          Executed SQL Query &amp; Data Sources
        </span>
        {/* Chevron direction indicates whether the panel is open or closed */}
        {isOpen ? (
          <ChevronUp className="w-3.5 h-3.5 shrink-0" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 shrink-0" />
        )}
      </button>

      {/* ── Collapsible SQL Code Block ───────────────────────────────────── */}
      {/* WHY conditional render instead of CSS hidden: avoids rendering a
          large <pre> block in the DOM when collapsed — keeps the message list
          lean, especially for threads with many SQL messages. */}
      {isOpen && (
        <div id="sql-audit-body" className="relative">
          {/* Copy Button — positioned absolute so it doesn't disturb the SQL layout */}
          <button
            onClick={handleCopy}
            title="Copy SQL to clipboard"
            className="
              absolute top-2.5 right-3 z-10
              flex items-center gap-1
              text-[10px] text-slate-400 hover:text-emerald-400
              transition-colors duration-150
              focus:outline-none
            "
          >
            {/* Toggle between copy icon and checkmark based on clipboard state */}
            {copied ? (
              <>
                <Check className="w-3 h-3" />
                <span>Copied!</span>
              </>
            ) : (
              <>
                <ClipboardCopy className="w-3 h-3" />
                <span>Copy</span>
              </>
            )}
          </button>

          {/* WHY <pre><code>: semantic HTML for machine-readable code blocks.
              whitespace-pre-wrap preserves SQL indentation while allowing the
              block to wrap on narrow screens. */}
          <pre
            className="
              bg-[#0B0F19] text-[#10B981] border-t border-[#222D3D]
              font-mono rounded-b-lg p-4 pt-8
              text-xs leading-relaxed overflow-x-auto
              whitespace-pre-wrap break-words
            "
          >
            <code>{sql}</code>
          </pre>
        </div>
      )}
    </div>
  );
}
