"use client";

/**
 * Ingestion tab entry point for connector-sourced files: once an admin has
 * connected Google Drive/Salesforce in Settings (a tenant-wide connection,
 * not per-user -- see TenantConnection), any user browses/imports through
 * this bar instead of going back to Settings. Reuses FolderTreeExplorer
 * as-is; this component's only job is showing which providers are live and
 * opening the explorer scoped to the current tab's direction.
 *
 * FE Gap 113 item 4: this bar used to `return null` whenever no provider was
 * Active, so the entire "Load from:" row vanished and the capability was
 * undiscoverable -- a user had no way to learn from this screen that files can
 * come from Drive/Salesforce at all. It now always renders every provider:
 * Active ones as a live "Browse ->" button, everything else greyed out behind
 * a lock with a direct link to /settings/connectors.
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { HardDrive, Cpu, Lock } from "lucide-react";
import FolderTreeExplorer from "@/components/connectors/FolderTreeExplorer";
import {
  FolderShortcut,
  readFolderShortcut,
  writeFolderShortcut,
} from "@/lib/connectorFolderShortcut";

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

const ALL_PROVIDERS = Object.keys(PROVIDER_META) as Provider[];

export default function ConnectorBrowseBar({ direction }: { direction: Direction }) {
  const [statuses, setStatuses] = useState<ConnectionStatuses | null>(null);
  // Tracked separately from `statuses` because a failed/unreachable status call
  // also has to resolve to the locked state -- otherwise a null `statuses` would
  // be indistinguishable from "still checking" and the row would sit in the
  // loading style forever.
  const [isChecking, setIsChecking] = useState(true);
  const [browsing, setBrowsing] = useState<Provider | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/connectors/status")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled) return;
        if (data) setStatuses(data);
        setIsChecking(false);
      })
      .catch(() => {
        // No connectors configured / status endpoint unreachable -- the row
        // still renders, every provider simply shows as not connected.
        if (!cancelled) setIsChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] text-slate-500">Load from:</span>
        {ALL_PROVIDERS.map((provider) => {
          const { label, icon: Icon } = PROVIDER_META[provider];
          const isActive = statuses?.[provider] === "Active";

          if (isActive) {
            return (
              <button
                key={provider}
                onClick={() => setBrowsing(provider)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-[#151B26] border border-[#222D3D] text-slate-300 hover:border-blue-500/40 hover:text-white transition-colors"
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
                <span className="text-accent-blue">Browse &rarr;</span>
              </button>
            );
          }

          // While the status call is still in flight the provider is shown
          // muted but *without* the lock/Connect link, so a connected tenant
          // never sees a "not connected" claim flash before the real answer
          // arrives.
          return (
            <span
              key={provider}
              title={
                isChecking
                  ? `Checking ${label} connection...`
                  : `${label} is not connected for this tenant`
              }
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-[#151B26]/60 border border-[#222D3D] text-slate-500 select-none"
            >
              {!isChecking && <Lock className="w-3 h-3 shrink-0" />}
              <Icon className="w-3.5 h-3.5 shrink-0" />
              {label}
              {!isChecking && (
                <Link
                  href="/settings/connectors"
                  className="text-slate-400 underline underline-offset-2 hover:text-white transition-colors"
                >
                  Connect in Settings
                </Link>
              )}
            </span>
          );
        })}
      </div>

      {browsing && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6">
          <div className="w-full max-w-2xl">
            {/* FE Gap 165: this screen is the reason the Settings "mapping" was
                decorative -- it opened the explorer at Root every time and never
                read the saved folder. It now opens at the saved default folder
                for this provider + direction, and honours a new default set
                from here (same localStorage shortcut, so the two screens agree). */}
            <FolderTreeExplorer
              provider={browsing}
              direction={direction}
              initialFolder={readFolderShortcut(browsing, direction)}
              onFolderSelected={(folder: FolderShortcut) => {
                writeFolderShortcut(browsing, direction, folder);
                setBrowsing(null);
              }}
              onClose={() => setBrowsing(null)}
            />
          </div>
        </div>
      )}
    </>
  );
}
