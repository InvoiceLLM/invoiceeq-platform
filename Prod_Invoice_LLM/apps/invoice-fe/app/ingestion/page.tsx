"use client";

import React, { useState, useEffect } from "react";
import { UploadCloud, CheckCircle, AlertCircle, RefreshCw, FolderSearch, Send } from "lucide-react";
import TagSelector from "../../components/ingestion/TagSelector";
import DropZone from "../../components/ingestion/DropZone";
import StatusTable from "../../components/ingestion/StatusTable";
import LogTerminal from "../../components/ingestion/LogTerminal";
import SendInvoiceStatusTable from "../../components/ingestion/SendInvoiceStatusTable";
import ConnectorBrowseBar from "../../components/ingestion/ConnectorBrowseBar";
import PageHeader from "../../components/layout/PageHeader";
import { apiClient } from "../../lib/apiClient";

type IngestionTab = "receiving" | "sending";

export default function IngestionPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Task 3.1.1 (Feature 3.1, Service Flow): the tab header only appears when
  // both Receive/Send are enabled -- a single-service tenant sees exactly
  // its one relevant view, unchanged from today's default when Send is off.
  const [receiveEnabled, setReceiveEnabled] = useState(true);
  const [sendEnabled, setSendEnabled] = useState(false);
  const [activeTab, setActiveTab] = useState<IngestionTab>("receiving");

  // Outbound (Sending) state
  const [outboundFile, setOutboundFile] = useState<File | null>(null);
  const [outboundInvoiceId, setOutboundInvoiceId] = useState<string | null>(null);
  const [isOutboundUploading, setIsOutboundUploading] = useState(false);
  const [outboundError, setOutboundError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/service-flow")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setReceiveEnabled(data.receive_invoices_enabled ?? true);
        setSendEnabled(data.send_invoices_enabled ?? false);
        if (!data.receive_invoices_enabled && data.send_invoices_enabled) {
          setActiveTab("sending");
        }
      })
      .catch(() => {
        // Settings fetch failing shouldn't break the page -- defaults keep
        // today's behavior (Receive-only view).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleOutboundUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!outboundFile) return;

    setIsOutboundUploading(true);
    setOutboundError(null);

    const formData = new FormData();
    formData.append("file", outboundFile);

    try {
      const response = await apiClient.post("/outbound-invoices/upload", formData);
      setOutboundInvoiceId(response.data.invoice_id);
    } catch (err: any) {
      console.error("Outbound upload failed", err);
      setOutboundError(err.response?.data?.detail || "Failed to upload outbound invoice.");
    } finally {
      setIsOutboundUploading(false);
    }
  };

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

  const showTabs = receiveEnabled && sendEnabled;
  const showReceiving = !sendEnabled || activeTab === "receiving";
  const showSending = (sendEnabled && !receiveEnabled) || (showTabs && activeTab === "sending");

  return (
    <div className="space-y-6">
      <PageHeader title="File Ingestion" agentIcon="🤖" agentName="NOVA" agentRole="Extraction & Validation" />

      {/* Task 3.1.1: Receiving/Sending tab header, only when both flows enabled */}
      {showTabs && (
        <div className="flex items-center gap-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg p-1 w-fit">
          <button
            onClick={() => setActiveTab("receiving")}
            className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
              activeTab === "receiving" ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Receiving
          </button>
          <button
            onClick={() => setActiveTab("sending")}
            className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
              activeTab === "sending" ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Sending
          </button>
        </div>
      )}

      {showSending && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-6">
            <div className="glass-panel rounded-xl border border-[#222D3D] p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                <Send className="w-4 h-4 text-slate-500" />
                Upload Outbound Invoice
              </div>
              <input
                type="file"
                accept="application/pdf"
                onChange={(e) => setOutboundFile(e.target.files?.[0] || null)}
                className="w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200 file:text-xs"
              />
              <ConnectorBrowseBar direction="outbound" />
              {outboundError && (
                <div className="flex items-center gap-2 p-2 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-[11px]">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  <span>{outboundError}</span>
                </div>
              )}
              <button
                onClick={handleOutboundUpload}
                disabled={!outboundFile || isOutboundUploading}
                className={`w-full flex items-center justify-center gap-2 py-2.5 px-3 rounded-lg text-xs font-semibold border transition-all ${
                  !outboundFile
                    ? "bg-slate-800/40 border-[#222D3D] text-slate-500 cursor-not-allowed"
                    : "bg-accent-blue border-accent-blue text-white hover:bg-[#2563EB]"
                }`}
              >
                {isOutboundUploading ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Uploading...
                  </>
                ) : (
                  <>
                    <UploadCloud className="w-3.5 h-3.5" /> Upload &amp; Extract
                  </>
                )}
              </button>
            </div>
          </div>
          <div className="lg:col-span-2">
            {outboundInvoiceId && outboundFile ? (
              <SendInvoiceStatusTable invoiceId={outboundInvoiceId} fileName={outboundFile.name} />
            ) : (
              <div className="glass-panel rounded-xl border border-[#222D3D] p-12 text-center h-full min-h-[200px] flex flex-col items-center justify-center gap-3">
                <div className="p-4 rounded-full bg-slate-900/50 border border-[#222D3D] text-slate-500">
                  <Send className="w-8 h-8" />
                </div>
                <p className="text-[11px] text-slate-500 max-w-xs">
                  Upload one of your own invoices on the left to verify it before sending.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {showReceiving && (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Tagging & Files Drag-Drop - takes 1 col */}
        <div className="lg:col-span-1 space-y-6">
          {/* Metadata tagging */}
          <TagSelector tags={tags} onChange={setTags} />

          {/* Files Selector */}
          <DropZone files={files} onChange={setFiles} />

          {/* Connector-sourced files (Gap 98): only renders once an admin has
              an active Google Drive/Salesforce connection in Settings. */}
          <ConnectorBrowseBar direction="inbound" />

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
      )}
    </div>
  );
}
