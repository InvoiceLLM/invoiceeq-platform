"use client";

import React, { useState } from "react";
import { UploadCloud, CheckCircle, AlertCircle, RefreshCw, FolderSearch } from "lucide-react";
import TagSelector from "../../components/ingestion/TagSelector";
import DropZone from "../../components/ingestion/DropZone";
import StatusTable from "../../components/ingestion/StatusTable";
import LogTerminal from "../../components/ingestion/LogTerminal";
import { apiClient } from "../../lib/apiClient";

export default function IngestionPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // States to pass to the active StatusTable
  const [batchId, setBatchId] = useState<string | null>(null);
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [trackedFiles, setTrackedFiles] = useState<Array<{ name: string; size: number }>>([]);

  // Gap 12/FE Gap 1: directory watcher — bulk-ingest a server-accessible folder
  // in one pass, without per-file drag-and-drop.
  const [directoryPath, setDirectoryPath] = useState("");
  const [isScanning, setIsScanning] = useState(false);
  const [watcherError, setWatcherError] = useState<string | null>(null);
  const [watcherResult, setWatcherResult] = useState<{ files_found: number; files_queued: number } | null>(null);

  const handleWatchDirectory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!directoryPath.trim()) return;

    setIsScanning(true);
    setWatcherError(null);
    setWatcherResult(null);

    try {
      const response = await apiClient.post("/invoices/watcher", { directory_path: directoryPath.trim() });
      const { batch_id, job_ids, files_found, files_queued } = response.data;
      setWatcherResult({ files_found, files_queued });
      if (job_ids?.length > 0) {
        setTrackedFiles(job_ids.map((id: string) => ({ name: id, size: 0 })));
        setBatchId(batch_id);
        setJobIds(job_ids);
      }
    } catch (err: any) {
      if (err.response?.status === 501) {
        setWatcherError("Directory watcher isn't enabled for this environment.");
      } else {
        setWatcherError(err.response?.data?.detail || "Failed to scan directory.");
      }
    } finally {
      setIsScanning(false);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;

    setIsUploading(true);
    setError(null);
    setSuccess(false);

    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });
    tags.forEach((tag) => {
      formData.append("tags", tag);
    });

    try {
      const response = await apiClient.post("/invoices/upload", formData);

      const { batch_id, job_ids } = response.data;

      // Track files currently uploaded
      setTrackedFiles(files.map((f) => ({ name: f.name, size: f.size })));
      setBatchId(batch_id);
      setJobIds(job_ids);

      // Clear input queues
      setFiles([]);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) {
      console.error("Upload failed", err);
      if (err.response?.status === 402) {
        setError("Billing limit reached. Upgrade to a premium plan to parse more invoices.");
      } else {
        setError(err.response?.data?.detail || "Failed to upload files. Ensure backend services are running.");
      }
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Title Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-white tracking-wide flex items-center gap-3">
          File Ingestion Portal
          <span className="text-[11px] px-2.5 py-1 rounded-full bg-[#22D3EE]/10 text-[#22D3EE] border border-[#22D3EE]/30 font-mono font-semibold tracking-widest">
            NOVA
          </span>
        </h1>
        <p className="text-xs text-slate-400">
          Upload multi-page invoices, assign metadata tags, and queue AI parsing.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Tagging & Files Drag-Drop - takes 1 col */}
        <div className="lg:col-span-1 space-y-6">
          {/* Metadata tagging */}
          <TagSelector tags={tags} onChange={setTags} />

          {/* Files Selector */}
          <DropZone files={files} onChange={setFiles} />

          {/* Form Status Notification Banner */}
          {error && (
            <div className="flex items-center gap-2 p-3 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-xs">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-lg text-xs">
              <CheckCircle className="w-4 h-4 flex-shrink-0" />
              <span>Batch successfully queued for processing.</span>
            </div>
          )}

          {/* Submit/Upload Button */}
          <button
            onClick={handleUpload}
            disabled={files.length === 0 || isUploading}
            className={`w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-xs font-semibold tracking-wide border transition-all duration-300 ${files.length === 0
              ? "bg-slate-800/40 border-[#222D3D] text-slate-500 cursor-not-allowed"
              : isUploading
                ? "bg-accent-blue/20 border-accent-blue/40 text-accent-blue cursor-wait"
                : "bg-accent-blue border-accent-blue text-white shadow-lg shadow-accent-blue/10 hover:shadow-accent-blue/20 hover:bg-[#2563EB]"
              }`}
          >
            {isUploading ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Ingesting Files...
              </>
            ) : (
              <>
                <UploadCloud className="w-4 h-4" />
                Submit Ingestion Batch
              </>
            )}
          </button>

          {/* Directory Watcher (Gap 12 / FE Gap 1): bulk-ingest a server-accessible
              folder in one pass, no per-file drag-and-drop. */}
          <div className="glass-panel rounded-xl border border-[#222D3D] p-4 space-y-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
              <FolderSearch className="w-4 h-4 text-slate-500" />
              Bulk Directory Scan
            </div>
            <p className="text-[11px] text-slate-500">
              Point at a folder the backend can read (e.g. a shared network drop
              folder) to ingest every PDF inside in one pass.
            </p>
            <form onSubmit={handleWatchDirectory} className="flex flex-col gap-2">
              <input
                type="text"
                value={directoryPath}
                onChange={(e) => setDirectoryPath(e.target.value)}
                placeholder="/path/to/watched/folder"
                className="w-full bg-[#0B0F19] border border-[#222D3D] rounded-lg px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent-blue/60"
              />
              <button
                type="submit"
                disabled={!directoryPath.trim() || isScanning}
                className={`w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-medium border transition-all ${
                  !directoryPath.trim()
                    ? "bg-slate-800/40 border-[#222D3D] text-slate-500 cursor-not-allowed"
                    : "bg-slate-800/60 border-[#222D3D] text-slate-200 hover:bg-slate-800"
                }`}
              >
                {isScanning ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Scanning...
                  </>
                ) : (
                  "Scan Directory"
                )}
              </button>
            </form>
            {watcherError && (
              <div className="flex items-center gap-2 p-2 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-[11px]">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{watcherError}</span>
              </div>
            )}
            {watcherResult && (
              <div className="flex items-center gap-2 p-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-lg text-[11px]">
                <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>
                  Found {watcherResult.files_found}, queued {watcherResult.files_queued} for processing.
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Status ledger tracking - takes 2 cols */}
        <div className="lg:col-span-2 space-y-4">
          {jobIds.length > 0 ? (
            <>
              <StatusTable
                batchId={batchId}
                jobIds={jobIds}
                initialFiles={trackedFiles}
              />
              <LogTerminal batchId={batchId} />
            </>
          ) : (
            <div className="glass-panel rounded-xl border border-[#222D3D] p-12 text-center h-full min-h-[300px] flex flex-col items-center justify-center gap-3">
              <div className="p-4 rounded-full bg-slate-900/50 border border-[#222D3D] text-slate-500">
                <UploadCloud className="w-8 h-8" />
              </div>
              <div className="max-w-xs space-y-1">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                  Status Ledger Idle
                </h3>
                <p className="text-[11px] text-slate-500 leading-normal">
                  Drop files and dispatch an ingestion batch on the left to monitor live OCR extraction progress.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
