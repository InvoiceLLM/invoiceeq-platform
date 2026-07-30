"use client";

/**
 * Ingestion tab entry point for connector-sourced files: once an admin has
 * connected Google Drive/Salesforce in Settings (a tenant-wide connection,
 * not per-user -- see TenantConnection), any user browses/imports through
 * this bar instead of going back to Settings. Reuses FolderTreeExplorer
 * as-is; this component's only job is showing which providers are live and
 * opening the explorer scoped to the current tab's direction.
 */

import React, { useEffect, useState } from "react";
import { HardDrive, Cpu } from "lucide-react";
import FolderTreeExplorer from "@/components/connectors/FolderTreeExplorer";

type Provider = "google_drive" | "salesforce";
type Direction = "inbound" | "outbound";

interface ConnectionStatuses {
  google_drive: "Active" | "Inactive" | "Not Configured";
  salesforce: "Active" | "Inactive" | "Not Configured";
}

const PROVIDER_META: Record<Provider, { label: string; icon: React.ComponentType<any> }> = {
  google_drive: { label: "Google Drive", icon: HardDrive },
  salesforce: { label: "Salesforce", icon: Cpu },
};

export default function ConnectorBrowseBar({ direction }: { direction: Direction }) {
  const [statuses, setStatuses] = useState<ConnectionStatuses | null>(null);
  const [browsing, setBrowsing] = useState<Provider | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/connectors/status")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) setStatuses(data);
      })
      .catch(() => {
        // No connectors configured / status endpoint unreachable -- fine,
        // the bar just renders nothing below.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const activeProviders = (Object.keys(PROVIDER_META) as Provider[]).filter(
    (p) => statuses?.[p] === "Active"
  );

  if (activeProviders.length === 0) return null;

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] text-slate-500">Load from:</span>
        {activeProviders.map((provider) => {
          const { label, icon: Icon } = PROVIDER_META[provider];
          return (
            <button
              key={provider}
              onClick={() => setBrowsing(provider)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-[#151B26] border border-[#222D3D] text-slate-300 hover:border-blue-500/40 hover:text-white transition-colors"
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          );
        })}
      </div>

      {browsing && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6">
          <div className="w-full max-w-2xl">
            <FolderTreeExplorer
              provider={browsing}
              direction={direction}
              onFolderSelected={() => setBrowsing(null)}
              onClose={() => setBrowsing(null)}
            />
          </div>
        </div>
      )}
    </>
  );
}
