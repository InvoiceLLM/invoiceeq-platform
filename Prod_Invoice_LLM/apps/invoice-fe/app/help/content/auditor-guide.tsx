import React from "react";
import { HelpSection } from "./trainer-guide";

import { ImageIcon } from "lucide-react";

function Shot({ src, alt, caption }: { src: string; alt: string; caption?: string }) {
  const [hasError, setHasError] = React.useState(false);

  return (
    <figure className="rounded-xl overflow-hidden border border-[#222D3D] bg-[#0B0F19]">
      {!hasError ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={src}
          alt={alt}
          onError={() => setHasError(true)}
          className="w-full block object-cover max-h-[420px]"
        />
      ) : (
        <div className="flex flex-col items-center justify-center p-8 bg-[#0F172A]/90 text-slate-400 gap-2 border-b border-[#222D3D]">
          <ImageIcon className="w-8 h-8 text-purple-400/60" />
          <span className="text-xs font-semibold text-slate-300">{alt}</span>
          <span className="text-[10px] text-slate-500 font-mono">Platform User Guide Preview Asset</span>
        </div>
      )}
      {caption && (
        <figcaption className="text-[11px] text-slate-500 px-3 py-2 border-t border-[#222D3D]">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-300 leading-relaxed">{children}</p>;
}

function Callout({ tone, children }: { tone: "info" | "warn"; children: React.ReactNode }) {
  const cls =
    tone === "warn"
      ? "bg-amber-500/10 border-amber-500/25 text-amber-200"
      : "bg-blue-500/10 border-blue-500/25 text-blue-200";
  return <div className={`text-xs rounded-lg border px-3 py-2.5 ${cls}`}>{children}</div>;
}

export const AUDITOR_HELP_SECTIONS: HelpSection[] = [
  {
    id: "auditor-overview",
    title: "What is the Auditor Console (Reviewer)?",
    keywords: ["auditor", "reviewer", "review", "console", "flagged", "reviewer console"],
    searchText: "auditor console reviewer review flagged invoice confidence warnings exceptions reviewer console",
    body: (
      <>
        <P>
          The <strong>Auditor Console</strong> (also referred to as the <strong>Reviewer Console</strong>) is the primary workspace for reviewing invoices that have been flagged during the extraction process. When the AI encounters low-confidence fields, missing data, or arithmetic mismatches, the invoice is marked as <code className="text-blue-300">AUDIT_REQUIRED</code>.
        </P>
        <P>
          The console provides a split-screen view: the original document on the left (with visual bounding boxes overlaying the extracted data) and an interactive metadata inspector and alert console on the right.
        </P>
        <Shot
          src="/help/auditor/24_auditor_initial.png"
          alt="Auditor console initial view"
          caption="The Auditor Console — document viewer on the left, alerts and metadata inspector on the right."
        />
      </>
    ),
  },
  {
    id: "auditor-corrections",
    title: "Making Field Corrections",
    keywords: ["edit", "correct", "fix", "field", "metadata", "reviewer"],
    searchText: "edit field correct metadata tracking dirty save fix reviewer console",
    body: (
      <>
        <P>
          If the extraction engine misread a field, you can correct it directly in the metadata inspector. Just click on any field to make it editable.
        </P>
        <P>
          Fields below a 60% confidence threshold will display an amber warning icon. When you edit a field, it is highlighted to indicate an unsaved change. Once you save or dismiss alerts, your corrections are recorded in the system.
        </P>
        <Shot
          src="/help/auditor/25_auditor_field_dirty.png"
          alt="Editing a field in the Auditor Console"
          caption="Clicking to edit a field highlights it. The system tracks these changes to feed them back to the AI Trainer."
        />
        <Callout tone="info">
          The system tracks all corrections and uses them to identify patterns. If you keep correcting the same field, the system will suggest creating an automated rule!
        </Callout>
      </>
    ),
  },
  {
    id: "auditor-rule-suggestions",
    title: "Rule Suggestions (Trainer Handoff)",
    keywords: ["suggested rule", "trainer", "automation", "banner", "recurring"],
    searchText: "suggested rule trainer automation banner recurring correction learning",
    body: (
      <>
        <P>
          The Auditor Console isn't just for manual review — it's the feedback engine for the AI Trainer. When the backend detects a recurring correction pattern (e.g., you've corrected the Tax Amount for the same vendor 3 times), the system proactively suggests a rule.
        </P>
        <P>
          You will see a purple "Want to save this as a rule?" banner appear in the Alert Console. Clicking <strong>Open Trainer</strong> immediately transitions you into the Trainer sandbox, pre-seeded with your correction, allowing you to instantly automate the fix for all future invoices.
        </P>
        <Shot
          src="/help/auditor/27_trainer_preseeded.png"
          alt="Trainer session pre-seeded from auditor correction"
          caption="Clicking the rule suggestion banner brings you straight to the Trainer with the context already loaded."
        />
      </>
    ),
  },
  {
    id: "auditor-outbound",
    title: "Outbound AR Invoice Review",
    keywords: ["outbound", "AR", "accounts receivable", "outbound review", "reviewer"],
    searchText: "outbound AR accounts receivable outbound review reviewer console confirm send mark paid",
    body: (
      <>
        <P>
          Under the <strong>Outbound Review</strong> tab, team members can audit accounts receivable (AR) invoices that your staff has issued.
        </P>
        <P>
          Unlike inbound bills, outbound invoices do not email external customers directly. Instead, when an outbound invoice is processed, it enters the outbound audit queue. The reviewer can double-check the extracted values and choose to:
        </P>
        <ul className="space-y-1.5 text-xs text-slate-300 list-disc pl-5">
          <li><strong>Confirm Send:</strong> Marks the invoice as officially sent in the ledger and triggers email notifications to the list of staff AR email addresses.</li>
          <li><strong>Mark Paid:</strong> Marks the outbound invoice as paid and updates your accounts receivable summaries.</li>
        </ul>
      </>
    ),
  },
];
