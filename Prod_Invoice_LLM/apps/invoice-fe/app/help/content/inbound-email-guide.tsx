import React from "react";
import { HelpSection } from "./trainer-guide";
import { Mail, ShieldCheck, CheckCircle2 } from "lucide-react";

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-300 leading-relaxed">{children}</p>;
}

export const INBOUND_EMAIL_HELP_SECTIONS: HelpSection[] = [
  {
    id: "inbound-email-overview",
    title: "Inbound Email Ingestion Guide",
    keywords: ["inbound", "email", "alias", "allowed senders", "ingestion", "attachment"],
    searchText: "inbound email alias allowed senders ingestion attachment pdf allowlist forward",
    body: (
      <>
        <P>
          The <strong>Inbound Email Ingestion</strong> feature allows vendors, suppliers, and team members to submit invoices directly to your workspace by sending an email with PDF attachments to your dedicated workspace alias.
        </P>

        <div className="space-y-2 mt-3">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">How It Works</h4>
          <ol className="space-y-1.5 text-xs text-slate-300 list-decimal pl-5">
            <li>Copy your unique workspace email alias from <strong>Settings → Email</strong> (e.g., <code className="text-blue-300">your-tenant@invoices.invoice-ai.com</code>).</li>
            <li>Add allowed sender email addresses (e.g. <code className="text-emerald-300">billing@vendor.com</code>) to your <strong>Allowed Senders List</strong>.</li>
            <li>When an email arrives from an approved sender, attached PDF invoices are automatically extracted and queued in the Ingestion pipeline.</li>
          </ol>
        </div>

        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-200 mt-4 space-y-1">
          <p className="font-semibold">Security Note on Sender Allowlisting:</p>
          <p>Emails sent from addresses NOT listed on your Allowed Senders List are automatically blocked to prevent unauthorized document ingestion or spam.</p>
        </div>
      </>
    ),
  },
];
