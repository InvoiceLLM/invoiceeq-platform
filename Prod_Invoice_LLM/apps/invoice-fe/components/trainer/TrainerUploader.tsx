"use client";

import React, { useState } from "react";
import {
  UploadCloud,
  Building2,
  FileText,
  ChevronDown,
  Sparkles,
  X,
} from "lucide-react";
import { TrainerScope, VendorOption } from "@/lib/trainer-service";

/**
 * Feature 6 Component: TrainerUploader (Tasks 6.2 – 6.4)
 * Collapsed inline layout for the consolidated Trainer header control bar.
 */

interface TrainerUploaderProps {
  scope: TrainerScope;
  vendors: VendorOption[];
  selectedVendorName?: string;
  onSelectVendor: (vendorName: string) => void;
  onUploadFile: (file: File) => void;
  onClearFile?: () => void;
  isUploading?: boolean;
  activeFileName?: string;
}

export default function TrainerUploader({
  scope,
  vendors,
  selectedVendorName,
  onSelectVendor,
  onUploadFile,
  onClearFile,
  isUploading = false,
  activeFileName,
}: TrainerUploaderProps) {
  const [dragActive, setDragActive] = useState(false);

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
    e.target.value = "";
  };

  // ── SCOPE 2: Existing Vendor Dropdown ──
  if (scope === "existing_vendor") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5 shrink-0">
          <Building2 className="w-3.5 h-3.5" />
          Grounding Vendor:
        </span>
        <div className="relative w-48 sm:w-64">
          <select
            value={selectedVendorName || ""}
            onChange={(e) => onSelectVendor(e.target.value)}
            className="w-full bg-[#111827]/80 border border-[#1E2D45] text-white text-xs rounded-xl px-3 py-2 appearance-none focus:outline-none focus:border-emerald-500/60 pr-8 transition-colors cursor-pointer"
          >
            <option value="" disabled>
              — Choose Vendor —
            </option>
            {vendors.map((v) => (
              <option key={v.id} value={v.name}>
                {v.name} ({v.invoiceCount})
              </option>
            ))}
          </select>
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
        </div>
      </div>
    );
  }

  // ── SCOPE 1 (Global) & SCOPE 3 (New Vendor) ──
  return (
    <div
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
      className={`
        flex items-center gap-2 px-2 py-1 rounded-xl transition-all duration-200 border border-transparent
        ${dragActive ? "border-blue-500/50 bg-blue-500/5" : ""}
      `}
    >
      {activeFileName ? (
        <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1.5 rounded-lg text-[11px] text-emerald-400">
          <FileText className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate max-w-[130px] font-semibold">{activeFileName}</span>
          {onClearFile && (
            <button
              type="button"
              onClick={onClearFile}
              className="text-emerald-400/60 hover:text-red-400 hover:bg-red-500/10 p-0.5 rounded transition-colors"
              title="Clear sample document"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
      ) : (
        <span className="text-[11px] text-slate-500 hidden md:inline">
          {scope === "global" ? "Optional sample document:" : "Upload sample invoice:"}
        </span>
      )}

      <label className="cursor-pointer flex items-center justify-center gap-1.5 bg-[#111827]/80 hover:bg-[#1E293B] text-white text-[11px] font-semibold px-3 py-2 rounded-xl border border-[#1E2D45] hover:border-blue-500/40 transition-all shadow-sm">
        <Sparkles className="w-3 h-3 text-blue-400" />
        <span>{activeFileName ? "Change PDF" : "Browse PDF"}</span>
        <input
          type="file"
          accept=".pdf,application/pdf"
          onChange={handleFileChange}
          disabled={isUploading}
          className="hidden"
        />
      </label>
    </div>
  );
}
