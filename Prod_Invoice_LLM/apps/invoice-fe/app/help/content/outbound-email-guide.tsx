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
          <ImageIcon className="w-8 h-8 text-amber-400/60" />
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

export const OUTBOUND_EMAIL_HELP_SECTIONS: HelpSection[] = [
  {
    id: "outbound-email-overview",
    title: "Outbound Email Audit Guide",
    keywords: ["outbound", "email", "authorized", "audit", "AR", "invoiceeq"],
    searchText: "outbound email authorized set audit AR mailbox invoiceeq notifications pdf image photo scan",
    body: (
      <>
        <P>
          The same shared mailbox (<code className="text-blue-300">invoices@invoiceeq.app</code>) accepts your own outbound invoices (PDF or image) for audit when the sender is on the{" "}
          <strong>outbound authorized set</strong>. The app <strong>never emails your customers</strong> — Confirm Send only marks the invoice Sent and can notify selected AR addresses on that set.
        </P>

        <Shot
          src="/help/email/02-outbound-email-flow.svg"
          alt="Outbound AR Invoice Audit & Confirmation Flow"
          caption="Outbound flow: AR ingestion -> Arithmetic check -> Auditor Confirm Send -> Internal staff notification."
        />

        <div className="space-y-2 mt-3">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Outbound set setup</h4>
          <ol className="space-y-1.5 text-xs text-slate-300 list-decimal pl-5">
            <li>Open <strong>Settings → Email</strong>.</li>
            <li>Add AR addresses under <strong>Outbound authorized emails</strong>.</li>
            <li>Email your own invoices (PDF or image) to the shared mailbox from those addresses.</li>
            <li>Enable <strong>Send Invoices</strong> in Service Flow after at least one outbound address is registered (Pro Combined).</li>
            <li>On outbound review, multi-select who should get a staff notification before Confirm Send or Mark Paid.</li>
          </ol>
        </div>
      </>
    ),
  },
];
