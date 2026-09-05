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

export const INBOUND_EMAIL_HELP_SECTIONS: HelpSection[] = [
  {
    id: "inbound-email-overview",
    title: "Inbound Email Ingestion Guide",
    keywords: ["inbound", "email", "mailbox", "authorized", "ingestion", "attachment"],
    searchText: "inbound email mailbox authorized senders ingestion attachment pdf image photo scan allowlist forward invoiceeq",
    body: (
      <>
        <P>
          All workspaces share one app mailbox:{" "}
          <code className="text-blue-300">invoices@invoiceeq.app</code>. AP addresses on your{" "}
          <strong>inbound authorized set</strong> can email vendor invoices there (PDF or image attachments); the app routes them to your workspace as inbound.
        </P>

        <Shot
          src="/help/email/01-inbound-email-flow.svg"
          alt="Inbound Email Ingestion Architecture Flow"
          caption="Inbound email flow: Vendor email -> SendGrid Inbound Parse -> Sender allowlist verification -> AI extraction pipeline."
        />

        <div className="space-y-2 mt-3">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">How It Works</h4>
          <ol className="space-y-1.5 text-xs text-slate-300 list-decimal pl-5">
            <li>Copy the mailbox from <strong>Settings → Email</strong>.</li>
            <li>Add AP addresses to <strong>Inbound authorized emails</strong>.</li>
            <li>Send/forward supplier invoices (PDF or image attachments) from those addresses to the mailbox.</li>
            <li>
              Ops: SendGrid Inbound Parse Destination URL must be the public website host
              (<code className="text-blue-300">…/api/v1/email/mailintegration</code>), not the internal API — GoDaddy MX + Parse host settings are still required for live receive.
            </li>
          </ol>
        </div>

        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-200 mt-4 space-y-1">
          <p className="font-semibold">Why one shared address works:</p>
          <p>
            Tenant and direction come from the sender&apos;s registered email, not from a per-tenant To address. Unregistered senders are ignored.
          </p>
        </div>

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Staff notifications</h4>
          <P>
            After processing, the submitter (or inbound set) can get a Completed / Audit pending email. When an auditor Marks Paid or Rejects, they multi-select registered inbound addresses to notify — the app never emails your vendors or customers.
          </P>
        </div>
      </>
    ),
  },
];
