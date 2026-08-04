"use client";

/**
 * FE Gap 113 item 7: the "Pending" half of the Status Ledger -- files the user
 * has selected but not yet dispatched.
 *
 * This is the list that used to live inside DropZone.tsx as "Selected Queue
 * (N)", directly under the drop target, where it was easy to miss. Nothing
 * about selection or validation moved with it: DropZone still owns the file
 * input, the PDF/25MB checks and the duplicate filter, and still writes the
 * same `files` array. This component only *renders* that array, in the ledger
 * column, above the live extraction rows -- so one panel shows the whole
 * lifecycle: pending -> processing -> completed.
 *
 * Row markup (icon / truncated name / mono size / remove) and the Clear Queue
 * control are carried over unchanged so the list reads identically to before,
 * just in its new home.
 */

import React from "react";
import { FileText, Trash2, Clock } from "lucide-react";

interface PendingLedgerProps {
  files: File[];
  onChange: (files: File[]) => void;
}

const formatFileSize = (bytes: number) => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
};

export default function PendingLedger({ files = [], onChange }: PendingLedgerProps) {
  if (files.length === 0) return null;

  const handleRemoveFile = (indexToRemove: number) => {
    onChange(files.filter((_, idx) => idx !== indexToRemove));
  };

  return (
    <div className="glass-panel rounded-xl border border-[#222D3D] overflow-hidden">
      <div className="px-4 py-3 border-b border-[#222D3D] flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Clock className="w-3.5 h-3.5 text-slate-500 shrink-0" />
          <h3 className="text-[11px] font-bold text-slate-300 uppercase tracking-wider truncate">
            Pending ({files.length})
          </h3>
        </div>
        <button
          type="button"
          onClick={() => onChange([])}
          className="text-[10px] text-rose-400 hover:underline shrink-0"
        >
          Clear Queue
        </button>
      </div>

      <div className="divide-y divide-[#222D3D]/30 max-h-48 overflow-y-auto px-4">
        {files.map((file, idx) => (
          <div
            key={`${file.name}-${idx}`}
            className="flex items-center justify-between gap-2 py-2 group text-xs text-slate-300"
          >
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <FileText className="w-4 h-4 text-accent-blue flex-shrink-0" />
              <span className="truncate font-semibold text-slate-200 group-hover:text-white transition-colors">
                {file.name}
              </span>
              <span className="text-[10px] text-slate-500 font-mono shrink-0">
                ({formatFileSize(file.size)})
              </span>
            </div>

            <button
              type="button"
              onClick={() => handleRemoveFile(idx)}
              className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors shrink-0"
              title="Remove file"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
