"use client";

/**
 * Feature 7 — IntegrationCard.tsx
 *
 * Configures connection toggle (OAuth flow) and independent AP/AR folder mapping
 * for a connector provider (Google Drive / Salesforce).
 */

import React, { useState } from "react";
import {
  FolderOpen,
  Link2,
  Link2Off,
  CheckCircle,
  AlertTriangle,
  FolderSync,
  ChevronRight,
  Loader2,
} from "lucide-react";

interface IntegrationCardProps {
  provider: "google_drive" | "salesforce";
  label: string;
  status: "Active" | "Inactive" | "Not Configured";
  icon: React.ComponentType<any>;
  isAdmin: boolean;
  inboundFolder: string | null;
  outboundFolder: string | null;
  onUpdateFolder: (direction: "inbound" | "outbound", folderName: string | null) => void;
  onConnect: () => void;
  onDisconnect: () => void;
  isConnecting: boolean;
  onBrowse: (direction: "inbound" | "outbound") => void;
}

export default function IntegrationCard({
  provider,
  label,
  status,
  icon: ProviderIcon,
  isAdmin,
  inboundFolder,
  outboundFolder,
  onUpdateFolder,
  onConnect,
  onDisconnect,
  isConnecting,
  onBrowse,
}: IntegrationCardProps) {
  const isConnected = status === "Active";

  return (
    <div className="bg-[#151B26] border border-[#222D3D] rounded-2xl p-5 space-y-5 flex flex-col justify-between transition-all duration-300 hover:border-slate-700 shadow-lg">
      
      {/* Header Info */}
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-[#1E293B] border border-[#222D3D] flex items-center justify-center text-slate-100">
              <ProviderIcon className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-white">{label}</h3>
              <p className="text-[11px] text-slate-400">
                {provider === "google_drive" ? "Google workspace document library" : "Salesforce PO & accounts files"}
              </p>
            </div>
          </div>

          {/* Status Badge */}
          <span
            className={`text-[10px] px-2.5 py-1 rounded-full font-medium flex items-center gap-1.5 shrink-0 ${
              isConnected
                ? "bg-[#10B981]/10 text-emerald-400 border border-[#10B981]/25"
                : status === "Inactive"
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/25"
                : "bg-slate-800 text-slate-400 border border-slate-700/50"
            }`}
          >
            {isConnected ? (
              <CheckCircle className="w-3.5 h-3.5" />
            ) : status === "Inactive" ? (
              <AlertTriangle className="w-3.5 h-3.5" />
            ) : null}
            {status}
          </span>
        </div>

        <p className="text-xs text-slate-500 leading-relaxed">
          Securely map document folders to automatically import vendor invoices or export customer billing files directly to your cloud store.
        </p>
      </div>

      {/* Directory Mappings Configuration */}
      {isConnected && (
        <div className="space-y-3 bg-[#0F141F] border border-[#1E293B] rounded-xl p-4.5">
          <h4 className="text-[10px] text-slate-500 font-mono tracking-wider uppercase mb-1">Folder Mappings</h4>

          {/* Inbound (AP) */}
          <div className="flex items-center justify-between gap-3 border-b border-[#1E293B]/40 pb-3">
            <div className="space-y-0.5">
              <div className="flex items-center gap-1.5">
                <FolderOpen className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-xs text-slate-300 font-medium">Inbound AP</span>
              </div>
              <p className="text-[10px] text-slate-500">Imports supplier PDFs</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono truncate max-w-[120px] bg-[#151B26] px-2 py-1 rounded border border-[#222D3D]">
                {inboundFolder || "Not Mapped"}
              </span>
              {isAdmin && (
                <button
                  onClick={() => onBrowse("inbound")}
                  className="p-1.5 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white transition-colors"
                  title="Browse Inbound Folder"
                  aria-label="Browse Inbound Folder"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          {/* Outbound (AR) */}
          <div className="flex items-center justify-between gap-3 pt-1">
            <div className="space-y-0.5">
              <div className="flex items-center gap-1.5">
                <FolderSync className="w-3.5 h-3.5 text-violet-400" />
                <span className="text-xs text-slate-300 font-medium">Outbound AR</span>
              </div>
              <p className="text-[10px] text-slate-500">Exports verified customer invoices</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono truncate max-w-[120px] bg-[#151B26] px-2 py-1 rounded border border-[#222D3D]">
                {outboundFolder || "Not Mapped"}
              </span>
              {isAdmin && (
                <button
                  onClick={() => onBrowse("outbound")}
                  className="p-1.5 rounded-lg bg-[#1E293B] hover:bg-[#2D3F55] text-slate-400 hover:text-white transition-colors"
                  title="Browse Outbound Folder"
                  aria-label="Browse Outbound Folder"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Connection Buttons */}
      <div className="pt-2 border-t border-[#1E293B]/40 flex gap-3">
        {isConnected ? (
          <button
            onClick={onDisconnect}
            disabled={!isAdmin || isConnecting}
            className="w-full py-2.5 rounded-xl border border-red-500/20 hover:border-red-500/40 hover:bg-red-500/5 text-red-400 disabled:opacity-50 text-xs font-semibold flex items-center justify-center gap-2 transition-all"
          >
            <Link2Off className="w-4 h-4" />
            Disconnect
          </button>
        ) : (
          <button
            onClick={onConnect}
            disabled={!isAdmin || isConnecting}
            className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-all shadow-md shadow-blue-900/10"
          >
            {isConnecting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Link2 className="w-4 h-4" />
            )}
            Connect Account
          </button>
        )}
      </div>
    </div>
  );
}
