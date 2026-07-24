"use client";

import React, { useState } from "react";
import {
  UploadCloud,
  Building2,
  FileText,
  CheckCircle2,
  ChevronDown,
  Sparkles,
  X,
} from "lucide-react";
import { TrainerScope, VendorOption } from "@/lib/trainer-service";

/**
 * Feature 6 Component: TrainerUploader (Tasks 6.2 – 6.4)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This component renders document/vendor input controls conditioned on the selected scope:
 *
 *   - Scope 2 ('existing_vendor'): Vendor dropdown that seeds sandbox from a real production invoice.
 *   - Scope 3 ('new_vendor'): Drag-and-drop PDF uploader for cold-start vendor rule sessions.
 *   - Scope 1 ('global'): Optional sample PDF dropzone for visual grounding (chat-only is also fine).
 *
 * Design: Premium glassmorphism card with animated drag-glow border, colored scope status icons,
 * and a compact badge strip showing the active file status.
 */

interface TrainerUploaderProps {
  /** Active rule scope */
  scope: TrainerScope;
  /** List of production vendors available for Scope 2 dropdown selection */
  vendors: VendorOption[];
  /** Name of the currently selected production vendor */
  selectedVendorName?: string;
  /** Callback fired when user picks a vendor from the dropdown */
  onSelectVendor: (vendorName: string) => void;
  /** Callback fired when user uploads a fresh sample PDF file */
  onUploadFile: (file: File) => void;
  /** Optional loading state flag */
  isUploading?: boolean;
  /** Name of the currently loaded active file */
  activeFileName?: string;
}

export default function TrainerUploader({
  scope,
  vendors,
  selectedVendorName,
  onSelectVendor,
  onUploadFile,
  isUploading = false,
  activeFileName,
}: TrainerUploaderProps) {
  const [dragActive, setDragActive] = useState(false);

  // ── Drag-and-Drop Event Handlers ──────────────────────────────────────────
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file && (file.type === "application/pdf" || file.name.endsWith(".pdf"))) {
      onUploadFile(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onUploadFile(file);
    // Reset input so re-selecting same file still fires
    e.target.value = "";
  };

  // ── SCOPE 2: Existing Vendor Dropdown ─────────────────────────────────────
  if (scope === "existing_vendor") {
    return (
      <div className="bg-[#0D131F]/80 backdrop-blur-sm border border-[#1E2D45] rounded-2xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-lg shadow-black/20">
        {/* Label Block */}
        <div className="flex items-center gap-3">
          {/* Emerald icon bubble */}
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-center text-emerald-400 shadow-md shadow-emerald-500/10">
            <Building2 className="w-5 h-5" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-white leading-tight">
              Select Production Vendor
            </h4>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Seeds sandbox from an already-extracted production invoice.
            </p>
          </div>
        </div>

        {/* Vendor Dropdown Select with custom chevron */}
        <div className="relative w-full sm:w-72">
          <select
            value={selectedVendorName || ""}
            onChange={(e) => onSelectVendor(e.target.value)}
            className="w-full bg-[#111827] border border-[#1E2D45] text-white text-sm rounded-xl px-4 py-2.5 appearance-none focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/20 cursor-pointer pr-10 transition-colors"
          >
            <option value="" disabled>
              — Choose Vendor —
            </option>
            {vendors.map((v) => (
              <option key={v.id} value={v.name}>
                {v.name} ({v.invoiceCount} invoices)
              </option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3.5 pointer-events-none" />
        </div>
      </div>
    );
  }

  // ── SCOPE 1 (Global) & SCOPE 3 (New Vendor): PDF Drag-and-Drop Dropzone ───
  return (
    <div
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
      className={`
        relative bg-[#0D131F]/80 backdrop-blur-sm border rounded-2xl p-4
        flex flex-col sm:flex-row items-center justify-between gap-4
        transition-all duration-200 shadow-lg shadow-black/20 overflow-hidden
        ${dragActive
          /* Active drag: vivid blue glow border + tinted bg */
          ? "border-blue-500/70 bg-blue-500/8 shadow-blue-500/10"
          : activeFileName
          /* File loaded: emerald success state */
          ? "border-emerald-500/40 bg-emerald-500/5"
          /* Default idle */
          : "border-[#1E2D45] hover:border-blue-500/40"
        }
      `}
    >
      {/* Ambient drag pulse glow overlay */}
      {dragActive && (
        <div className="absolute inset-0 bg-blue-500/5 pointer-events-none rounded-2xl border-2 border-dashed border-blue-500/40 animate-pulse" />
      )}

      {/* ── Left Info Block ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3.5 relative">
        {/* Icon bubble — changes to success check when file loaded */}
        <div
          className={`w-10 h-10 rounded-xl flex items-center justify-center shadow-md transition-colors ${
            activeFileName
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 shadow-emerald-500/10"
              : "bg-blue-500/10 text-blue-400 border border-blue-500/25 shadow-blue-500/10"
          }`}
        >
          {activeFileName ? (
            <CheckCircle2 className="w-5 h-5" />
          ) : (
            <UploadCloud className="w-5 h-5" />
          )}
        </div>

        <div>
          {activeFileName ? (
            /* File successfully loaded: show filename + status */
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <FileText className="w-4 h-4 text-emerald-400 shrink-0" />
                <span className="truncate max-w-[200px]">{activeFileName}</span>
              </div>
              <p className="text-[11px] text-emerald-400/80 mt-0.5">
                Sample document loaded — sandbox ready
              </p>
            </div>
          ) : (
            /* Empty: prompt for upload */
            <div>
              <h4 className="text-sm font-semibold text-white leading-tight">
                {scope === "global"
                  ? "Optional Sample Document Grounding"
                  : "Upload Sample Invoice PDF"}
              </h4>
              <p className="text-[11px] text-slate-400 mt-0.5">
                {scope === "global"
                  ? "Drag & drop a sample PDF to visually ground global rules, or proceed chat-only."
                  : "Upload a sample PDF for cold-starting rules for this new vendor."}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Right Action: Browse / Change button ───────────────────── */}
      <div className="flex items-center gap-2 w-full sm:w-auto shrink-0">
        <label className="w-full sm:w-auto cursor-pointer flex items-center justify-center gap-2 bg-[#111827] hover:bg-[#1E293B] text-white text-xs font-medium px-4 py-2.5 rounded-xl border border-[#1E2D45] hover:border-blue-500/40 transition-all shadow-sm">
          <Sparkles className="w-3.5 h-3.5 text-blue-400" />
          <span>{activeFileName ? "Change PDF" : "Browse PDF"}</span>
          <input
            type="file"
            accept=".pdf,application/pdf"
            onChange={handleFileChange}
            disabled={isUploading}
            className="hidden"
          />
        </label>

        {/* Clear file button — visible only when a file is loaded */}
        {activeFileName && (
          <button
            type="button"
            title="Remove file"
            className="p-2 rounded-xl text-slate-400 hover:text-red-400 hover:bg-red-500/10 border border-[#1E2D45] transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
