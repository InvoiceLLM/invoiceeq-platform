"use client";

import React, { useState, useRef, useEffect } from "react";
import { UploadCloud, FileText, Trash2, AlertCircle } from "lucide-react";

import {
  acceptedFormatsLabel,
  acceptedUploadExtensions,
  invalidFormatMessage,
  loadFeatureFlags,
  type FeatureFlags,
} from "@/lib/featureFlags";

interface DropZoneProps {
  files: File[];
  onChange: (files: File[]) => void;
  /**
   * FE Gap 113 item 7: the Receiving tab now renders the selected-but-not-yet-
   * submitted list as a "Pending" section inside the Status Ledger (see
   * PendingLedger.tsx) rather than buried under the drop target, where it was
   * easy to miss after dropping files. Set false there; the drop zone then
   * shows a one-line pointer at the ledger instead.
   *
   * Defaults to true so the Sending tab (Gap 97) keeps the exact layout it has
   * today -- selection/validation logic below is identical either way.
   */
  showQueue?: boolean;
}

const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25 MB

/**
 * FE Gap 378 / BE Feature 27 (G11 / task R5) — CLOSED 2026-09-03.
 *
 * This block previously explained why the accept list was pinned to `.pdf`: §4
 * requires the widening be gated on `ENABLE_GENERIC_EXTRACTION` "surfaced via
 * the existing config/feature endpoint, not hardcoded", and no such endpoint
 * existed. That was the blocker, and it was backend scope, not FE work.
 *
 * `GET /config/features` now exists (R5(a)), so the list is resolved at runtime
 * from the real backend flag via `lib/featureFlags.ts`.
 *
 * BOTH GUARDS READ THE SAME VALUE, which is the point §4 makes explicitly: the
 * `accept` attribute on the input and the suffix check in `processFiles` are
 * separate checks -- a drag-and-drop bypasses the picker entirely -- and if they
 * disagree a user drags a PNG past the picker and is rejected after selection.
 * One `acceptedExtensions` value feeds both.
 *
 * FE FEATURE 19 (BE Feature 28) moved the floor. Images are now converted to
 * PDF by the backend unconditionally, so the base list always carries the image
 * suffixes and a failed flag fetch degrades to that list rather than to `.pdf`
 * alone. Feature 27's flag path is untouched and unions on top of it. The copy
 * below reads from `acceptedFormatsLabel()` off the SAME array as the two
 * guards, so the words on screen cannot name a format the input rejects.
 */

export default function DropZone({ files = [], onChange, showQueue = true }: DropZoneProps) {
  // R5(b): resolved from the backend flag, fail-closed to PDF-only until it
  // answers. `loadFeatureFlags()` holds one in-flight promise per page load, so
  // several components mounting together make one request.
  const [featureFlags, setFeatureFlags] = useState<FeatureFlags | null>(null);
  useEffect(() => {
    let cancelled = false;
    void loadFeatureFlags().then((flags) => {
      if (!cancelled) setFeatureFlags(flags);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const acceptedExtensions = acceptedUploadExtensions(featureFlags);
  const formatsLabel = acceptedFormatsLabel(acceptedExtensions);

  const [isDragActive, setIsDragActive] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragActive(true);
    } else if (e.type === "dragleave") {
      setIsDragActive(false);
    }
  };

  const processFiles = (newFiles: FileList | null) => {
    if (!newFiles) return;
    setErrorMessage(null);

    const validFiles: File[] = [];
    const existingNames = new Set(files.map((f) => f.name));

    for (let i = 0; i < newFiles.length; i++) {
      const file = newFiles[i];

      // Validate format (guard 1 of 2 — the drag-and-drop path, which never
      // sees the `accept` attribute). Same `acceptedExtensions` as guard 2.
      const lowerName = file.name.toLowerCase();
      if (!acceptedExtensions.some((ext) => lowerName.endsWith(ext))) {
        // The message names what is ACTUALLY allowed rather than hardcoding
        // "PDF": a user told the wrong rule retries the wrong thing.
        setErrorMessage(invalidFormatMessage(acceptedExtensions));
        continue;
      }

      // Validate size
      if (file.size > MAX_FILE_SIZE) {
        setErrorMessage(`File ${file.name} exceeds the maximum allowed size of 25MB.`);
        continue;
      }

      // Avoid duplicates
      if (existingNames.has(file.name)) {
        continue;
      }

      validFiles.push(file);
    }

    if (validFiles.length > 0) {
      onChange([...files, ...validFiles]);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    processFiles(e.dataTransfer.files);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    processFiles(e.target.files);
  };

  const handleRemoveFile = (indexToRemove: number) => {
    const updated = files.filter((_, idx) => idx !== indexToRemove);
    onChange(updated);
  };

  const triggerInputClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="space-y-4">
      {/* Dashed Drag/Drop Box Area */}
      <div
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
        onClick={triggerInputClick}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-300 flex flex-col items-center justify-center gap-3 relative select-none ${
          isDragActive
            ? "border-[#3B82F6] bg-[#3B82F6]/5 shadow-inner"
            : "border-[#222D3D] hover:border-[#3B82F6]/50 bg-slate-900/10 hover:bg-slate-900/20"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          /* Guard 2 of 2 — must always agree with the suffix check in
             processFiles. Both read `acceptedExtensions`, see the block above. */
          accept={acceptedExtensions.join(",")}
          onChange={handleFileChange}
          className="hidden"
        />

        <div className="p-3 rounded-full bg-slate-800/40 border border-[#222D3D] text-slate-400 group-hover:text-white transition-colors">
          <UploadCloud className={`w-8 h-8 ${isDragActive ? "text-[#3B82F6] animate-bounce" : "text-slate-400"}`} />
        </div>

        <div className="space-y-1">
          <p className="text-xs font-semibold text-white">
            Drag & drop invoices here, or <span className="text-[#3B82F6] hover:underline">browse</span>
          </p>
          <p className="text-[10px] text-slate-500">
            Accepts {formatsLabel}. Max size 25MB.
          </p>
          {/* Founder decision, 2026-09-04: say the conversion out loud. Without
              it a user who uploads a photo later finds a `.pdf` filename in the
              ledger with no explanation of where it came from. */}
          <p className="text-[10px] text-slate-500">
            Photos and scans are converted to PDF automatically.
          </p>
        </div>
      </div>

      {/* Validation Error Banner */}
      {errorMessage && (
        <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 text-red-400 rounded-lg text-xs">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* FE Gap 113 item 7: with the queue relocated to the Status Ledger, the
          drop zone keeps only a short inline pointer so the files never look
          like they were silently dropped on the floor. */}
      {!showQueue && files.length > 0 && (
        <p className="text-[11px] text-slate-500">
          <span className="font-semibold text-slate-300">{files.length}</span>{" "}
          {files.length === 1 ? "file" : "files"} selected &mdash; review them under{" "}
          <span className="font-semibold text-slate-300">Pending</span> in the Status Ledger.
        </p>
      )}

      {/* Pending Files Display Queue */}
      {showQueue && files.length > 0 && (
        <div className="glass-panel p-4 rounded-xl space-y-3">
          <div className="flex items-center justify-between border-b border-[#222D3D] pb-2">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
              Selected Queue ({files.length})
            </span>
            <button
              onClick={() => onChange([])}
              className="text-[10px] text-red-400 hover:underline"
            >
              Clear Queue
            </button>
          </div>

          <div className="divide-y divide-[#222D3D]/30 max-h-48 overflow-y-auto">
            {files.map((file, idx) => (
              <div
                key={`${file.name}-${idx}`}
                className="flex items-center justify-between py-2 group text-xs text-slate-300"
              >
                <div className="flex items-center gap-2.5 truncate flex-1 pr-4">
                  <FileText className="w-4 h-4 text-accent-blue flex-shrink-0" />
                  <span className="truncate font-semibold text-slate-200 group-hover:text-white transition-colors">
                    {file.name}
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">
                    ({formatFileSize(file.size)})
                  </span>
                </div>
                
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRemoveFile(idx);
                  }}
                  className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-slate-800 transition-colors"
                  title="Remove file"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
