import React from "react";
import { HelpSection } from "./trainer-guide";

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-300 leading-relaxed">{children}</p>;
}

export const OUTBOUND_EMAIL_HELP_SECTIONS: HelpSection[] = [
  {
    id: "outbound-email-overview",
    title: "Outbound Email Audit Guide",
    keywords: ["outbound", "email", "authorized", "audit", "AR", "invoiceeq"],
    searchText: "outbound email authorized set audit AR mailbox invoiceeq notifications",
    body: (
      <>
        <P>
          The same shared mailbox (<code className="text-blue-300">invoices@invoiceeq.app</code>) accepts your own outbound invoice PDFs for audit when the sender is on the{" "}
          <strong>outbound authorized set</strong>. Customer delivery from Confirm Send is still separate (not yet live).
        </P>

        <div className="space-y-2 mt-3">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Outbound set setup</h4>
          <ol className="space-y-1.5 text-xs text-slate-300 list-decimal pl-5">
            <li>Open <strong>Settings → Email</strong>.</li>
            <li>Add AR addresses under <strong>Outbound authorized emails</strong>.</li>
            <li>Email your own invoice PDFs to the shared mailbox from those addresses.</li>
            <li>Enable <strong>Send Invoices</strong> in Service Flow after at least one outbound address is registered (Pro Combined).</li>
          </ol>
        </div>
      </>
    ),
  },
];
