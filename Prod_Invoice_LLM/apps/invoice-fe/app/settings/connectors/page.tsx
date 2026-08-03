"use client";

/**
 * Feature 7: Connectors Page — /settings/connectors
 *
 * Configures connection statuses and displays the FolderTreeExplorer when browsing directories.
 */

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, HardDrive, Cpu, Loader2, CheckCircle } from "lucide-react";
import IntegrationCard from "@/components/connectors/IntegrationCard";
import FolderTreeExplorer from "@/components/connectors/FolderTreeExplorer";
import { useAuth } from "@/hooks/useAuth";

// Local storage keys to persist mapped folder names for demo purposes
const STORAGE_KEYS = {
  google_drive: { inbound: "map_gdrive_in", outbound: "map_gdrive_out" },
  salesforce: { inbound: "map_sf_in", outbound: "map_sf_out" },
};

interface ConnectionStatuses {
  google_drive: "Active" | "Inactive" | "Not Configured";
  salesforce: "Active" | "Inactive" | "Not Configured";
}

export default function ConnectorsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  // FE Gap 99 (sub-finding): `isAdmin` was hardcoded `true` on both cards
  // below -- a gate wired to always pass. Now the real role from GET /auth/me.
  const { role: authRole } = useAuth();
  const isAdmin = authRole === "Admin";
  const justConnected = searchParams.get("connected");

  const [statuses, setStatuses] = useState<ConnectionStatuses | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isConnecting, setIsConnecting] = useState<Record<string, boolean>>({});
  
  // Folder mapping selections
  const [mappings, setMappings] = useState({
    google_drive: { inbound: "", outbound: "" },
    salesforce: { inbound: "", outbound: "" },
  });

  // Active explorer state
  const [explorer, setExplorer] = useState<{
    provider: "google_drive" | "salesforce";
    direction: "inbound" | "outbound";
  } | null>(null);

  // --- Load connection statuses on mount ---
  const loadStatuses = async () => {
    try {
      const res = await fetch("/api/connectors/status");
      if (!res.ok) throw new Error("Failed to load statuses");
      const data = await res.json();
      setStatuses({
        google_drive: data.google_drive || "Not Configured",
        salesforce: data.salesforce || "Not Configured",
      });
    } catch (err) {
      console.error("Failed to load connector status", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadStatuses();
    
    // Load local mappings
    if (typeof window !== "undefined") {
      setMappings({
        google_drive: {
          inbound: localStorage.getItem(STORAGE_KEYS.google_drive.inbound) || "",
          outbound: localStorage.getItem(STORAGE_KEYS.google_drive.outbound) || "",
        },
        salesforce: {
          inbound: localStorage.getItem(STORAGE_KEYS.salesforce.inbound) || "",
          outbound: localStorage.getItem(STORAGE_KEYS.salesforce.outbound) || "",
        },
      });
    }

    // Strip ?connected= from the URL after reading it, so a refresh doesn't
    // keep re-showing the confirmation banner.
    if (justConnected) {
      router.replace("/settings/connectors");
    }

    // This page is also what renders inside the OAuth popup itself once
    // Google/Salesforce redirects back (see handleConnect below) -- if we're
    // running inside a popup (window.opener set) and just connected
    // successfully, show the banner briefly then close automatically so the
    // user lands back on the main app window without an extra manual step.
    if (justConnected && typeof window !== "undefined" && window.opener) {
      const timer = setTimeout(() => window.close(), 1200);
      return () => clearTimeout(timer);
    }
  }, []);

  // --- OAuth trigger: opens the provider's real consent screen in a popup
  // instead of navigating the main window away, so the user never loses
  // their place in the app. A true <iframe> embed isn't possible here --
  // Google/Salesforce both block being framed (X-Frame-Options/CSP) to
  // prevent clickjacking on their login pages -- a popup is the closest
  // equivalent that still keeps the main window in place. ---
  const handleConnect = async (provider: string) => {
    setIsConnecting((prev) => ({ ...prev, [provider]: true }));
    try {
      const resUrl = await fetch(`/api/connectors/auth-url/${provider}`);
      if (!resUrl.ok) throw new Error("Failed to get auth URL");
      const { auth_url } = await resUrl.json();

      const popup = window.open(
        auth_url,
        "connector_oauth",
        "width=520,height=680,menubar=no,toolbar=no,location=yes,status=no"
      );

      if (!popup) {
        // Popup blocked by the browser -- fall back to a full-page redirect
        // rather than silently failing with no way to connect at all.
        window.location.href = auth_url;
        return;
      }

      // Poll for the popup closing (either the user cancelled, or it
      // auto-closed itself after a successful connect -- see the effect
      // above) and refresh this window's status either way.
      const pollInterval = setInterval(() => {
        if (popup.closed) {
          clearInterval(pollInterval);
          setIsConnecting((prev) => ({ ...prev, [provider]: false }));
          loadStatuses();
        }
      }, 500);
    } catch (err) {
      console.error("Connection failed", err);
      setIsConnecting((prev) => ({ ...prev, [provider]: false }));
    }
  };

  // --- Disconnect provider ---
  const handleDisconnect = async (provider: string) => {
    setIsConnecting((prev) => ({ ...prev, [provider]: true }));
    try {
      const res = await fetch(`/api/connectors/${provider}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to disconnect connector");

      setStatuses((prev) => {
        if (!prev) return prev;
        return { ...prev, [provider]: "Not Configured" };
      });
      // Clear mappings
      localStorage.removeItem(STORAGE_KEYS[provider as keyof typeof STORAGE_KEYS].inbound);
      localStorage.removeItem(STORAGE_KEYS[provider as keyof typeof STORAGE_KEYS].outbound);
      setMappings((prev) => ({
        ...prev,
        [provider]: { inbound: "", outbound: "" },
      }));
      setExplorer(null);
    } catch (err) {
      console.error("Disconnection failed", err);
    } finally {
      setIsConnecting((prev) => ({ ...prev, [provider]: false }));
    }
  };

  // --- Update directory mapping ---
  const handleUpdateFolderMapping = (
    provider: "google_drive" | "salesforce",
    direction: "inbound" | "outbound",
    folderName: string | null
  ) => {
    const val = folderName || "";
    localStorage.setItem(STORAGE_KEYS[provider][direction], val);
    setMappings((prev) => ({
      ...prev,
      [provider]: {
        ...prev[provider],
        [direction]: val,
      },
    }));
    setExplorer(null);
  };

  if (isLoading || !statuses) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-xs gap-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        Checking connector statuses…
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-auto font-sans">
      {/* Header */}
      <header className="h-16 border-b border-[#222D3D] bg-[#0F172A]/70 backdrop-blur-md px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href="/settings"
            className="w-9 h-9 rounded-xl bg-slate-500/10 border border-slate-500/20 flex items-center justify-center text-slate-300 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-base font-semibold text-white tracking-wide">Third-Party Connectors</h1>
            <p className="text-xs text-slate-400">Map Google Drive and Salesforce documents to service pipelines</p>
          </div>
        </div>
      </header>

      {justConnected && (
        <div className="max-w-4xl w-full mx-auto px-6 pt-4">
          <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-lg text-xs">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />
            <span>Connected to {justConnected.replace("_", " ")}.</span>
          </div>
        </div>
      )}

      {/* Main Grid */}
      <main className="flex-1 px-6 py-8 max-w-4xl w-full mx-auto grid grid-cols-1 md:grid-cols-2 gap-6 items-start">

        {/* Google Drive Card */}
        <IntegrationCard
          provider="google_drive"
          label="Google Drive"
          status={statuses.google_drive}
          icon={HardDrive}
          isAdmin={isAdmin}
          inboundFolder={mappings.google_drive.inbound}
          outboundFolder={mappings.google_drive.outbound}
          onUpdateFolder={(dir, folder) => handleUpdateFolderMapping("google_drive", dir, folder)}
          onConnect={() => handleConnect("google_drive")}
          onDisconnect={() => handleDisconnect("google_drive")}
          isConnecting={isConnecting["google_drive"] || false}
          onBrowse={(dir) => setExplorer({ provider: "google_drive", direction: dir })}
        />

        {/* Salesforce Card */}
        <IntegrationCard
          provider="salesforce"
          label="Salesforce Files"
          status={statuses.salesforce}
          icon={Cpu}
          isAdmin={isAdmin}
          inboundFolder={mappings.salesforce.inbound}
          outboundFolder={mappings.salesforce.outbound}
          onUpdateFolder={(dir, folder) => handleUpdateFolderMapping("salesforce", dir, folder)}
          onConnect={() => handleConnect("salesforce")}
          onDisconnect={() => handleDisconnect("salesforce")}
          isConnecting={isConnecting["salesforce"] || false}
          onBrowse={(dir) => setExplorer({ provider: "salesforce", direction: dir })}
        />

        {/* Dynamic Explorer Drawer / Section */}
        {explorer && (
          <div className="col-span-1 md:col-span-2 pt-4">
            <FolderTreeExplorer
              provider={explorer.provider}
              direction={explorer.direction}
              onFolderSelected={(folder) =>
                handleUpdateFolderMapping(explorer.provider, explorer.direction, folder)
              }
              onClose={() => setExplorer(null)}
            />
          </div>
        )}
      </main>
    </div>
  );
}
