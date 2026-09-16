"use client";

// =============================================================================
// FILE: components/today/UploadButton.tsx
// FEATURE: FE Feature 22 Task 22.24 — "Upload" on Today.
//
// A REAL `<input type="file">`: the browser's own picker, no directory picker,
// no filesystem access, no new backend. Files go to the Ingest screen's existing
// endpoint, `POST /invoices/upload` (`lib/today.ts::uploadDocuments`), and the
// picker offers exactly the formats Ingest's DropZone offers
// (`acceptedUploadExtensions()`), with the same 25 MB cap checked before upload.
//
// Uploading needs `can_load`, the same permission Ingest does — without it the
// button is not rendered. Success is confirmed inline and Today re-reads.
//
// Attach (to a conversation) is not a Today control: Ask's composer already has
// the native paperclip (Feature 26), and Today reaches it through
// `/ask?attach=1` (22.5 / 22.6). The `attach_prompt` card is blocked on BE 33.34.
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import {
  acceptedUploadExtensions,
  invalidFormatMessage,
  loadFeatureFlags,
  type FeatureFlags,
} from "@/lib/featureFlags";
import { uploadDocuments, uploadErrorMessage } from "@/lib/today";

/** Mirrors components/ingestion/DropZone.tsx's MAX_FILE_SIZE. */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

export default function UploadButton({ onUploaded }: { onUploaded?: () => void }) {
  const { canLoad, loading } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [flags, setFlags] = useState<FeatureFlags | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadedCount, setUploadedCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadFeatureFlags().then((next) => {
      if (!cancelled) setFlags(next);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading || !canLoad) return null;

  const extensions = acceptedUploadExtensions(flags);

  const onPicked = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    // Reset so picking the same file again still fires `change`.
    event.target.value = "";
    if (picked.length === 0) return;

    setError(null);
    setUploadedCount(null);
    const wrongFormat = picked.find((file) => !extensions.some((ext) => file.name.toLowerCase().endsWith(ext)));
    if (wrongFormat) {
      setError(invalidFormatMessage(extensions));
      return;
    }
    const tooLarge = picked.find((file) => file.size > MAX_UPLOAD_BYTES);
    if (tooLarge) {
      setError(`${tooLarge.name} is larger than 25 MB.`);
      return;
    }

    setUploading(true);
    try {
      await uploadDocuments(picked);
      setUploadedCount(picked.length);
      onUploaded?.();
    } catch (err) {
      setError(uploadErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {uploadedCount !== null && (
        <span role="status" className="text-xs text-emerald-300">
          {uploadedCount} {uploadedCount === 1 ? "document" : "documents"} uploaded — processing now.
        </span>
      )}
      {error && (
        <span role="alert" className="text-xs text-rose-300">
          {error}
        </span>
      )}
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={extensions.join(",")}
        onChange={onPicked}
        className="hidden"
        data-testid="today-upload-input"
      />
      <button
        type="button"
        data-testid="today-upload"
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className="inline-flex items-center gap-1.5 rounded-lg border border-[#222D3D] bg-[#0F172A] px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-wait disabled:opacity-60"
      >
        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Upload className="h-3.5 w-3.5" aria-hidden="true" />}
        Upload
      </button>
    </div>
  );
}
