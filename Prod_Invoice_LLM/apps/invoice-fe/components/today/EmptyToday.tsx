"use client";

// =============================================================================
// FILE: components/today/EmptyToday.tsx
// FEATURE: FE Feature 22 Tasks 22.4 + 22.25 — Today with nothing to show.
//
// Two states that must never be confused:
//   - EmptyToday: ATLAS has run and nothing needs the user right now.
//   - PreOnboardingToday (22.25): ATLAS has NOT run yet — `GET /today` returned
//     `{state: "pre_onboarding", docs_seen, docs_required}`. It shows how to get
//     documents in and how many have arrived, and NOTHING else: no finding, no
//     FP&A line, no input request, because none exists yet.
//
// The progress is the server's two numbers as words ("4 of 10"), not a bar or
// a percentage the server didn't send. The inbox address comes from the email
// settings endpoint and is omitted when unavailable — never guessed. The drop
// zone is the Ingest screen's own DropZone and upload endpoint; uploading needs
// the same `can_load` permission Ingest does, so without it the user is told who
// can upload instead of being offered a control the backend would refuse.
// =============================================================================

import React, { useEffect, useState } from "react";
import { Check, CheckCircle2, Copy, Loader2, Mail, UploadCloud } from "lucide-react";
import DropZone from "@/components/ingestion/DropZone";
import { useAuth } from "@/hooks/useAuth";
import { getInboxAddress, uploadDocuments, uploadErrorMessage } from "@/lib/today";

export default function EmptyToday() {
  return (
    <div
      data-testid="today-empty"
      className="flex flex-col items-center gap-2 rounded-xl border border-[#1E293B] bg-[#0F172A]/60 px-6 py-14 text-center"
    >
      <CheckCircle2 className="h-7 w-7 text-emerald-400" />
      <h2 className="text-sm font-semibold text-white">Nothing needs you right now</h2>
      <p className="max-w-sm text-xs text-slate-400">
        Forward an invoice or ask a question — new findings will appear here.
      </p>
    </div>
  );
}

interface PreOnboardingTodayProps {
  docsSeen: number;
  docsRequired: number;
  /** Called after a successful upload, so Today re-reads its state. */
  onUploaded?: () => void;
}

export function PreOnboardingToday({ docsSeen, docsRequired, onUploaded }: PreOnboardingTodayProps) {
  const { canLoad } = useAuth();
  const [inbox, setInbox] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedCount, setUploadedCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getInboxAddress().then((address) => {
      if (!cancelled) setInbox(address);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const copyInbox = async () => {
    if (!inbox) return;
    try {
      await navigator.clipboard.writeText(inbox);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable — the address stays visible to copy by hand */
    }
  };

  const upload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setUploadError(null);
    setUploadedCount(null);
    try {
      await uploadDocuments(files);
      setUploadedCount(files.length);
      setFiles([]);
      onUploaded?.();
    } catch (err) {
      setUploadError(uploadErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      data-testid="today-pre-onboarding"
      className="flex flex-col gap-5 rounded-xl border border-[#1E293B] bg-[#0F172A]/60 px-6 py-8"
    >
      <div className="flex flex-col items-center gap-2 text-center">
        <UploadCloud className="h-7 w-7 text-sky-400" />
        <h2 className="text-sm font-semibold text-white">Upload documents to begin</h2>
        <p data-testid="today-pre-onboarding-progress" className="max-w-md text-xs text-slate-400">
          <span className="font-mono text-slate-200">
            {docsSeen} of {docsRequired}
          </span>{" "}
          documents so far. Today starts finding things for you once there are enough to analyse.
        </p>
      </div>

      {inbox && (
        <div
          data-testid="today-inbox"
          className="flex flex-wrap items-center justify-center gap-2 rounded-lg border border-[#1E293B] bg-[#0B0F19] px-4 py-3 text-xs"
        >
          <Mail className="h-3.5 w-3.5 text-slate-400" />
          <span className="text-slate-400">Or forward invoices to</span>
          <span className="font-mono text-slate-100">{inbox}</span>
          <button
            type="button"
            onClick={copyInbox}
            aria-label="Copy inbox address"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-slate-300 transition-colors hover:bg-slate-800 hover:text-white"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}

      {canLoad ? (
        <div data-testid="today-drop-zone" className="flex flex-col gap-3">
          <DropZone files={files} onChange={setFiles} />
          <div className="flex flex-wrap items-center justify-end gap-3">
            {uploadError && (
              <p role="alert" className="text-xs text-rose-300">
                {uploadError}
              </p>
            )}
            {uploadedCount !== null && (
              <p role="status" className="text-xs text-emerald-300">
                {uploadedCount} {uploadedCount === 1 ? "document" : "documents"} uploaded — processing now.
              </p>
            )}
            <button
              type="button"
              onClick={upload}
              disabled={files.length === 0 || uploading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#3B82F6] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#2563EB] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Upload {files.length > 0 ? files.length : ""}
            </button>
          </div>
        </div>
      ) : (
        <p data-testid="today-no-upload-permission" className="text-center text-xs text-slate-500">
          Uploading needs the ingest permission — ask an Admin to upload, or to grant it to you.
        </p>
      )}
    </div>
  );
}
