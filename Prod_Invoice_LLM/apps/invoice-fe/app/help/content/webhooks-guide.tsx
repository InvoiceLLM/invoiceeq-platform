import React from "react";
import { HelpSection } from "./trainer-guide";
import { Webhook, ShieldCheck, Zap } from "lucide-react";

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-300 leading-relaxed">{children}</p>;
}

function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3 text-xs font-mono text-emerald-400 overflow-x-auto">
      {code}
    </pre>
  );
}

export const WEBHOOKS_HELP_SECTIONS: HelpSection[] = [
  {
    id: "webhooks-overview",
    title: "Developer Webhooks Guide",
    keywords: ["webhooks", "api", "events", "http", "callback", "integration"],
    searchText: "webhooks developer api events http callback integration endpoint payload signature",
    body: (
      <>
        <P>
          <strong>Developer Webhooks</strong> allow your external backend services to receive real-time HTTP POST notifications whenever an invoice event occurs in Invoice AI (e.g. invoice ingested, extracted, or approved).
        </P>
        <P>
          Instead of constantly polling the REST API for updates, webhooks push data to your designated <strong>Target URL</strong> instantly as status changes occur.
        </P>

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Subscribed Events</h4>
          <ul className="space-y-1 text-xs text-slate-300 list-disc pl-5">
            <li><code className="text-blue-300">invoice.ingested</code> — Fired when a new PDF is queued for processing</li>
            <li><code className="text-blue-300">invoice.extracted</code> — Fired when OCR & AI extraction complete</li>
            <li><code className="text-blue-300">invoice.audit_required</code> — Fired when an exception requires auditor review</li>
            <li><code className="text-blue-300">invoice.approved</code> — Fired when an auditor approves or marks paid</li>
          </ul>
        </div>

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Payload Structure</h4>
          <CodeBlock
            code={`{
  "event": "invoice.extracted",
  "tenant_id": "tenant_123",
  "timestamp": "2026-08-07T12:00:00Z",
  "data": {
    "invoice_id": "inv_99",
    "invoice_number": "INV-2026-001",
    "grand_total": 1250.00,
    "status": "COMPLETED"
  }
}`}
          />
        </div>
      </>
    ),
  },
];
