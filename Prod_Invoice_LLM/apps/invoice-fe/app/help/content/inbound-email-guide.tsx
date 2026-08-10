import React from "react";
import { HelpSection } from "./trainer-guide";

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-300 leading-relaxed">{children}</p>;
}

export const INBOUND_EMAIL_HELP_SECTIONS: HelpSection[] = [
  {
    id: "inbound-email-overview",
    title: "Inbound Email Ingestion Guide",
    keywords: ["inbound", "email", "mailbox", "authorized", "ingestion", "attachment"],
    searchText: "inbound email mailbox authorized senders ingestion attachment pdf allowlist forward invoiceeq",
    body: (
      <>
        <P>
          All workspaces share one app mailbox:{" "}
          <code className="text-blue-300">invoices@invoiceeq.app</code>. AP addresses on your{" "}
          <strong>inbound authorized set</strong> can email vendor invoice PDFs there; the app routes them to your workspace as inbound.
        </P>

        <div className="space-y-2 mt-3">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">How It Works</h4>
          <ol className="space-y-1.5 text-xs text-slate-300 list-decimal pl-5">
            <li>Copy the mailbox from <strong>Settings → Email</strong>.</li>
            <li>Add AP addresses to <strong>Inbound authorized emails</strong>.</li>
            <li>Send/forward supplier PDF invoices from those addresses to the mailbox.</li>
          </ol>
        </div>

        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-200 mt-4 space-y-1">
          <p className="font-semibold">Why one shared address works:</p>
          <p>
            Tenant and direction come from the sender&apos;s registered email, not from a per-tenant To address. Unregistered senders are ignored.
          </p>
        </div>
      </>
    ),
  },
];
