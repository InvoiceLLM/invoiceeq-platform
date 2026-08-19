import React from "react";
import { HelpSection } from "./trainer-guide";
import { ImageIcon, AlertCircle, Info } from "lucide-react";

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
    <pre className="bg-[#0B0F19] border border-[#222D3D] rounded-xl p-3 text-xs font-mono text-emerald-400 overflow-x-auto my-2">
      {code}
    </pre>
  );
}

export const SETTINGS_HELP_SECTIONS: HelpSection[] = [
  {
    id: "settings-overview",
    title: "Platform Settings Guide",
    keywords: ["settings", "organisation", "security", "permissions", "roles", "members", "api key", "webhooks", "billing"],
    searchText: "platform settings guide organisation security permissions roles members api key webhooks billing webhook signatures hmac md5",
    body: (
      <>
        <P>
          Configure and manage your workspace settings, security access, automated integrations, and subscription billing.
        </P>

        <div className="space-y-4 mt-4">
          {/* Section 1: Organisation & Security */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-white uppercase tracking-wider">1. Organisation & Security</h4>
            <P>
              Manage your team members and roles inside your Clerk Organization under the <strong>Settings → Organisation</strong> tab:
            </P>
            <ul className="space-y-1 text-xs text-slate-300 list-disc pl-5">
              <li><strong>Admin:</strong> Full administrative control, including billing subscription changes, user invites, webhook registrations, and template commits.</li>
              <li><strong>Auditor:</strong> Can edit extracted fields, verify data, and approve/reject invoices inside the Auditor Console.</li>
              <li><strong>Viewer:</strong> Read-only access to view processed invoices, extraction sheets, dashboards, and reporting logs.</li>
            </ul>
            <P>
              <strong>Data Isolation:</strong> All data is strictly isolated per tenant using multi-tenant organization IDs. No user from another organization can access your documents or rules.
            </P>
          </div>

          {/* Section 2: Email Routing */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-white uppercase tracking-wider">2. Inbound & Outbound Email Sets</h4>
            <P>
              In the <strong>Settings → Email</strong> tab, manage lists of authorized email addresses that are allowed to ingest invoices via the shared mailbox (<code className="text-blue-300">invoices@invoiceeq.app</code>):
            </P>
            <ul className="space-y-1 text-xs text-slate-300 list-disc pl-5">
              <li><strong>Inbound Set:</strong> Registered AP addresses allowed to email vendor bills to the shared mailbox. Email addresses not on this list are silently ignored.</li>
              <li><strong>Outbound Set:</strong> Registered AR addresses allowed to send outbound invoices to the shared mailbox. Invoices sent from these addresses undergo Outbound Audit review.</li>
            </ul>
          </div>

          {/* Section 3: Connectors & Webhooks */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-white uppercase tracking-wider">3. Webhooks & Custom Connectors</h4>
            <P>
              In the <strong>Settings → Connectors</strong> tab, register webhooks to receive real-time HTTP POST notifications of invoice events (e.g. `invoice.completed`, `invoice.approved`).
            </P>
            <P>
              <strong>Verifying Webhook Signatures:</strong> Every webhook POST contains a header named <code className="text-blue-300">X-InvoiceAI-Signature</code>. You must compute the HMAC SHA-256 signature of the raw request payload using your configured Secret Token to verify request authenticity:
            </P>
            <CodeBlock
              code={`# Python example of Webhook Signature Verification
import hmac
import hashlib

computed = hmac.new(
    SECRET_TOKEN.encode('utf-8'),
    raw_request_body,
    hashlib.sha256
).hexdigest()

assert computed == request.headers.get("X-InvoiceAI-Signature")`}
            />
          </div>

          {/* Section 4: API Keys & API Usage */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-white uppercase tracking-wider">4. API Keys & API Integration</h4>
            <P>
              Generate read/write API keys under the <strong>Settings → API Keys</strong> tab.
            </P>
            <P>
              <strong>How to call the API:</strong> Authenticate your REST requests by passing the key in the <code className="text-blue-300">X-API-Key</code> header:
            </P>
            <CodeBlock
              code={`GET /api/v1/invoices HTTP/1.1
Host: api.invoiceeq.app
X-API-Key: YOUR_API_KEY_HERE`}
            />
            <P>
              <strong>Cross-Service LOP Leave Data Sync:</strong> For integration with external systems (like the HRMS/Payroll sync), the plain API key (e.g., <code className="text-blue-300">12345AB</code>) is hashed using MD5 before transmission. Both systems verify the hash on every cross-service LOP data exchange to prevent exposing the plain key.
            </P>
          </div>

          {/* Section 5: Billing & Subscriptions */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-white uppercase tracking-wider">5. Billing & Subscription Tiers</h4>
            <P>
              Track usage limits and upgrade plans under the <strong>Settings → Billing</strong> tab:
            </P>
            <ul className="space-y-1 text-xs text-slate-300 list-disc pl-5">
              <li><strong>Free Tier:</strong> Limited to 50 invoice ingestions per month, standard templates, and basic dashboard access.</li>
              <li><strong>Pro Plan:</strong> Unlimited inbound invoice ingestion, full AI Trainer Sandbox access, custom rules, and webhook subscriptions.</li>
              <li><strong>Pro Combined (Pro + AR):</strong> Adds full accounts receivable (outbound AR) invoicing, Outbound Audit review console, and notification automation.</li>
            </ul>
            <P>
              Upgrading is secure and managed via a PayU billing checkout session, which automatically updates your active tenant entitlement tier.
            </P>
          </div>
        </div>
      </>
    ),
  },
];
