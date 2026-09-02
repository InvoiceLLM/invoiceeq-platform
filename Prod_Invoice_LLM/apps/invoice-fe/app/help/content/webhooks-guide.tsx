import React from "react";
import { HelpSection } from "./trainer-guide";
import { Webhook, ShieldCheck, Zap, ImageIcon } from "lucide-react";

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
          className="w-full block object-contain max-h-[420px]"
        />
      ) : (
        <div className="flex flex-col items-center justify-center p-8 bg-[#0F172A]/90 text-slate-400 gap-2 border-b border-[#222D3D]">
          <ImageIcon className="w-8 h-8 text-blue-400/60" />
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

        <Shot
          src="/help/webhooks/01-webhook-architecture.svg"
          alt="Developer Webhooks Architecture Diagram"
          caption="Webhook delivery lifecycle: Event generation -> HMAC-SHA256 signature -> HTTPS POST with 3x exponential backoff."
        />

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Subscribed Events</h4>
          <ul className="space-y-1 text-xs text-slate-300 list-disc pl-5">
            <li><code className="text-blue-300">invoice.processing</code> — Fired when an inbound invoice enters the extraction pipeline</li>
            <li><code className="text-blue-300">invoice.completed</code> — Fired when an inbound invoice finishes extraction successfully</li>
            <li><code className="text-blue-300">invoice.audit_required</code> — Fired when an exception requires auditor review</li>
            <li><code className="text-blue-300">invoice.duplicate</code> — Fired when an uploaded invoice matches a previously ingested file</li>
            <li><code className="text-blue-300">invoice.approved</code> — Fired when an auditor marks an inbound invoice approved</li>
            <li><code className="text-blue-300">invoice.rejected</code> — Fired when an auditor rejects an inbound invoice</li>
            <li><code className="text-blue-300">outbound_invoice.sent</code> — Fired when an outbound invoice is dispatched to the recipient</li>
            <li><code className="text-blue-300">outbound_invoice.overdue</code> — Fired when an outbound invoice crosses its due date unpaid</li>
            <li><code className="text-blue-300">outbound_invoice.approved</code> — Fired when an outbound invoice is marked approved</li>
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
