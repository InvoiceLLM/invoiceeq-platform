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
          className="w-full block object-contain max-h-[420px]"
        />
      ) : (
        <div className="flex flex-col items-center justify-center p-8 bg-[#0F172A]/90 text-slate-400 gap-2 border-b border-[#222D3D]">
          <ImageIcon className="w-8 h-8 text-emerald-400/60" />
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
  const borderCls = tone === "warn" ? "border-amber-500/20 bg-amber-500/5 text-amber-200" : "border-blue-500/20 bg-blue-500/5 text-blue-200";
  const icon = tone === "warn" ? <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" /> : <Info className="w-4 h-4 text-blue-400 flex-shrink-0" />;
  
  return (
    <div className={`p-3 border rounded-xl text-xs flex gap-2.5 items-start ${borderCls}`}>
      {icon}
      <div className="space-y-1">{children}</div>
    </div>
  );
}

export const AUTOPILOT_HELP_SECTIONS: HelpSection[] = [
  {
    id: "autopilot-overview",
    title: "Tenant Autopilot Sync Guide",
    keywords: ["autopilot", "sync", "automation", "deduplication", "scheduled sync", "cron", "ingestion"],
    searchText: "tenant autopilot sync automation deduplication scheduled sync cron folder sweep sync now ingestion",
    body: (
      <>
        <P>
          <strong>Tenant Autopilot</strong> automates the ingestion of supplier invoices from your Google Drive folders directly into your extraction pipeline.
        </P>
        
        <Shot
          src="/help/autopilot/01-autopilot-setup.svg"
          alt="Autopilot settings configuration view"
          caption="Configure target directories, deduplication guard, and sync intervals for your Google Drive source."
        />

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">How It Works</h4>
          <ol className="space-y-1.5 text-xs text-slate-300 list-decimal pl-5">
            <li>
              <strong>Connect Folder Source:</strong> Go to <strong>Settings → Connectors</strong> to authorize access to your Google Drive account via OAuth.
            </li>
            <li>
              <strong>Configure Target Folder:</strong> Use the folder browser browser component inside the Autopilot dashboard to select the specific directory to sweep.
            </li>
            <li>
              <strong>Define the Schedule:</strong> Set the automated cron execution sweep frequency (e.g., hourly, daily, or custom intervals).
            </li>
            <li>
              <strong>Save and Enable:</strong> Autopilot configs are safely stored inside `tenant_autopilot_configs` database and scheduled on Azure Container Apps Jobs scheduler.
            </li>
          </ol>
        </div>

        <div className="mt-4">
          <Callout tone="info">
            <p className="font-semibold">Manual Run Option:</p>
            <p>
              Need to process new invoices immediately? Click the **Sync Now** button inside the Autopilot dashboard to trigger a real-time folder sweep manually without waiting for the scheduled run.
            </p>
          </Callout>
        </div>

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Deduplication Ledger</h4>
          <P>
            To prevent duplicate processing and charges, Autopilot employs a two-layer validation guard against all synced files:
          </P>
          <ul className="space-y-1 text-xs text-slate-300 list-disc pl-5">
            <li><strong>File ID Matching:</strong> Skips files that share an identical cloud source identifier.</li>
            <li><strong>SHA-256 Content Hash Matching:</strong> Computes the SHA-256 hash of the document bytes and matches it against `tenant_autopilot_logs` to block identical file contents uploaded with different filenames.</li>
          </ul>
        </div>

        <div className="space-y-2 mt-4">
          <h4 className="text-xs font-semibold text-white uppercase tracking-wider">Notifications & Reports</h4>
          <P>
            When a background sync completes, the sync engine collects the results and dispatches emails via SendGrid to the list of configured email addresses (if `notify_emails` is populated). 
            If `send_approval_links` is enabled, the notification email includes direct deep-links to the Auditor Console for quick invoice verification.
          </P>
        </div>
      </>
    ),
  },
];
