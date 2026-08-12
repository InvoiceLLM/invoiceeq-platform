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
            <li><code className="text-blue-300">invoice.processing</code> — Fired when an inbound invoice enters the extraction pipeline</li>
            <li><code className="text-blue-300">invoice.completed</code> — Fired when an inbound invoice finishes extraction successfully</li>
            <li><code className="text-blue-300">invoice.audit_required</code> — Fired when an exception requires auditor review</li>
            <li><code className="text-blue-300">invoice.duplicate</code> — Fired when an uploaded invoice matches a previously ingested file</li>
            <li><code className="text-blue-300">invoice.paid</code> — Fired when an auditor marks an inbound invoice paid</li>
            <li><code className="text-blue-300">invoice.rejected</code> — Fired when an auditor rejects an inbound invoice</li>
            <li><code className="text-blue-300">outbound_invoice.sent</code> — Fired when an outbound invoice is dispatched to the recipient</li>
            <li><code className="text-blue-300">outbound_invoice.overdue</code> — Fired when an outbound invoice crosses its due date unpaid</li>
            <li><code className="text-blue-300">outbound_invoice.paid</code> — Fired when an outbound invoice is marked paid</li>
          </ul>
        </div>

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Payload Structure</h4>
          <CodeBlock
            code={`{
  "event": "invoice.completed",
  "tenant_id": "tenant_123",
  "timestamp": "2026-08-07T12:00:00Z",
  "data": {
    "invoice_id": "inv_99",
    "vendor_name": "Acme Supplies",
    "grand_total": 1250.00,
    "currency": "USD",
    "status": "COMPLETED"
  }
}`}
          />
          <p className="text-xs text-slate-500">
            <code className="text-blue-300">currency</code> is an ISO-4217 code (e.g. <code className="text-blue-300">"INR"</code>) — always check it alongside <code className="text-blue-300">grand_total</code> rather than assuming USD.
          </p>
        </div>
      </>
    ),
  },
];
