"use client";

import React, { useState, useEffect } from "react";
import { UploadCloud, CheckCircle, AlertCircle, RefreshCw, FolderSearch, Send, ChevronDown } from "lucide-react";
import TagSelector from "../../components/ingestion/TagSelector";
import DropZone from "../../components/ingestion/DropZone";
import StatusTable from "../../components/ingestion/StatusTable";
import PendingLedger from "../../components/ingestion/PendingLedger";
import LogTerminal from "../../components/ingestion/LogTerminal";
import SendInvoiceStatusTable from "../../components/ingestion/SendInvoiceStatusTable";
import ConnectorBrowseBar from "../../components/ingestion/ConnectorBrowseBar";
import { PageHeaderActions, usePageHeader } from "../../components/layout/PageHeaderContext";
import { apiClient } from "../../lib/apiClient";

type IngestionTab = "receiving" | "sending";

// Module-level cache to persist selected files/tags across page navigations (Gap 146)
let cachedFiles: File[] = [];
let cachedTags: string[] = [];
let cachedOutboundFiles: File[] = [];

export default function IngestionPage() {
  // FE Gap 110: title + NOVA badge now live in Shell's one shared header.
  usePageHeader({
    title: "File Ingestion",
    agentIcon: "🤖",
    agentName: "NOVA",
    agentRole: "Extraction & Validation",
  });

  const [files, setFiles] = useState<File[]>(() => cachedFiles);
  const [tags, setTags] = useState<string[]>(() => cachedTags);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Sync inbound files and tags to cache
  useEffect(() => {
    cachedFiles = files;
  }, [files]);

  useEffect(() => {
    cachedTags = tags;
  }, [tags]);

  // Task 3.1.1 (Feature 3.1, Service Flow): the tab header only appears when
  // both Receive/Send are enabled -- a single-service tenant sees exactly
  // its one relevant view, unchanged from today's default when Send is off.
  const [receiveEnabled, setReceiveEnabled] = useState(true);
  const [sendEnabled, setSendEnabled] = useState(false);
  const [activeTab, setActiveTab] = useState<IngestionTab>("receiving");

  // Outbound (Sending) state
  const [outboundFiles, setOutboundFiles] = useState<File[]>(() => cachedOutboundFiles);
  const [outboundInvoices, setOutboundInvoices] = useState<Array<{ id: string; batchId: string; name: string }>>([]);
  const [isOutboundUploading, setIsOutboundUploading] = useState(false);
  const [outboundError, setOutboundError] = useState<string | null>(null);

  // Sync outbound files to cache
  useEffect(() => {
    cachedOutboundFiles = outboundFiles;
  }, [outboundFiles]);

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
    if (outboundFiles.length === 0) return;

    setIsOutboundUploading(true);
    setOutboundError(null);

    const uploadedList: Array<{ id: string; batchId: string; name: string }> = [];
    let hasError = false;

    for (const file of outboundFiles) {
      const formData = new FormData();
      formData.append("file", file);

      try {
        const response = await apiClient.post("/outbound-invoices/upload", formData);
        uploadedList.push({
          id: response.data.invoice_id,
          batchId: response.data.batch_id,
          name: file.name,
        });
      } catch (err: any) {
        console.error(`Outbound upload failed for ${file.name}`, err);
        setOutboundError(err.response?.data?.detail || `Failed to upload outbound invoice: ${file.name}`);
        hasError = true;
        break;
      }
    }

    if (!hasError) {
      setOutboundInvoices((prev) => [...prev, ...uploadedList]);
      setOutboundFiles([]);
      cachedOutboundFiles = [];
    }
    setIsOutboundUploading(false);
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
  // FE Gap 69: collapsed by default so the left column fits the viewport
  // without scrolling. Bulk Directory Scan is the least-used control in this
  // column (a shared-drop-folder path, not the normal drag-and-drop path), so
  // it's the right one to fold away -- the header row stays visible so it's
  // still discoverable, unlike being pushed below the fold entirely.
  const [isDirectoryScanOpen, setIsDirectoryScanOpen] = useState(false);

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
      {/* FE Gap 86 (preserved through Gap 110): the Receiving/Sending toggle
          must stay on the same row as the title, not start a row of its own.
          The title now lives in Shell's shared header, so the toggle follows it
          there through the header's actions portal rather than through the old
          `actions` prop. Still gated on showTabs, so a single-service tenant
          sees exactly what it did before. */}
      {showTabs && (
        <PageHeaderActions>
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
        </PageHeaderActions>
      )}

      {showSending && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* FE Gap 69: space-y-4 (was space-y-6) -- tighter vertical rhythm so
              the column fits the viewport without scrolling. */}
          <div className="lg:col-span-1 space-y-4">
            <div className="glass-panel rounded-xl border border-[#222D3D] p-4 space-y-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                <Send className="w-4 h-4 text-slate-500" />
                Upload Outbound Invoice
              </div>
              <DropZone files={outboundFiles} onChange={setOutboundFiles} />
              <ConnectorBrowseBar direction="outbound" />
              {outboundError && (
                <div className="flex items-center gap-2 p-3 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-xs">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{outboundError}</span>
                </div>
              )}
              <button
                onClick={handleOutboundUpload}
                disabled={outboundFiles.length === 0 || isOutboundUploading}
                className={`w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl text-xs font-semibold border transition-all duration-300 ${
                  outboundFiles.length === 0
                    ? "bg-slate-800/40 border-[#222D3D] text-slate-500 cursor-not-allowed"
                    : isOutboundUploading
                      ? "bg-accent-blue/20 border-accent-blue/40 text-accent-blue cursor-wait"
                      : "bg-accent-blue border-accent-blue text-white shadow-lg shadow-accent-blue/10 hover:shadow-accent-blue/20 hover:bg-[#2563EB]"
                }`}
              >
                {isOutboundUploading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" /> Uploading...
                  </>
                ) : (
                  <>
                    <UploadCloud className="w-4 h-4" /> Upload &amp; Extract
                  </>
                )}
              </button>
            </div>
          </div>
          <div className="lg:col-span-2 space-y-4">
            {outboundInvoices.length > 0 ? (
              outboundInvoices.map((inv) => (
                <div key={inv.id} className="space-y-4">
                  <SendInvoiceStatusTable invoiceId={inv.id} fileName={inv.name} />
                  <LogTerminal batchId={inv.batchId} />
                </div>
              ))
            ) : (
              <div className="glass-panel rounded-xl border border-[#222D3D] p-12 text-center h-full min-h-[300px] flex flex-col items-center justify-center gap-3">
                <div className="p-4 rounded-full bg-slate-900/50 border border-[#222D3D] text-slate-500">
                  <Send className="w-8 h-8" />
                </div>
                <div className="max-w-xs space-y-1">
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                    Outbound Ledger Idle
                  </h3>
                  <p className="text-[11px] text-slate-500 leading-normal">
                    Upload your outbound invoices on the left to run touchless validation and monitor processing.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {showReceiving && (
      /* FE Gap 113 items 5/6: three real columns on a 12-col grid instead of
         the old 1/3 + 2/3 split -- inputs (4), a slim Dispatch panel (3), and
         the Status Ledger (5). The ledger used to take two-thirds of the width
         to show three fields' worth of content; the width it gave back is what
         lets Submit stand beside it as its own panel rather than being stacked
         at the bottom of the input pile. */
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Side: file selection & batch inputs.
            FE Gap 69: space-y-4 (was space-y-6). */}
        <div className="lg:col-span-4 space-y-4">
          {/* Files Selector.
              FE Gap 113 item 1: the drop zone now leads this column -- picking
              files is the primary action here, tagging is metadata applied to
              files already picked. TagSelector used to render above it.
              Item 7: showQueue={false} moves the selected-file list into the
              Status Ledger's Pending section on the right. */}
          <DropZone files={files} onChange={setFiles} showQueue={false} />

          {/* Metadata tagging */}
          <TagSelector tags={tags} onChange={setTags} />

          {/* Connector-sourced files (Gap 98). FE Gap 113 item 4: always
              rendered now -- inactive providers show locked with a link to
              Settings rather than the whole row disappearing. */}
          <ConnectorBrowseBar direction="inbound" />

          {/* Directory Watcher (Gap 12 / FE Gap 1): bulk-ingest a server-accessible
              folder in one pass, no per-file drag-and-drop.
              FE Gap 69: collapsed into a disclosure so it stops pushing itself
              off-screen. Header row is always rendered and always clickable. */}
          <div className="glass-panel rounded-xl border border-[#222D3D] p-4 space-y-3">
            <button
              type="button"
              onClick={() => setIsDirectoryScanOpen((open) => !open)}
              aria-expanded={isDirectoryScanOpen}
              aria-controls="bulk-directory-scan-body"
              className="w-full flex items-center gap-2 text-xs font-semibold text-slate-300 hover:text-white transition-colors"
            >
              <FolderSearch className="w-4 h-4 text-slate-500 shrink-0" />
              <span>Bulk Directory Scan</span>
              <ChevronDown
                className={`w-4 h-4 text-slate-500 ml-auto shrink-0 transition-transform duration-200 ${
                  isDirectoryScanOpen ? "rotate-180" : ""
                }`}
              />
            </button>

            {isDirectoryScanOpen && (
            <div id="bulk-directory-scan-body" className="space-y-3">
            {/* FE Gap 113 item 3: condensed from a two-line explanatory
                sentence to the action itself. This is still the raw
                server-readable filesystem path feature it always was -- it has
                no relationship to the OAuth connectors in the row above. */}
            <p className="text-[11px] text-slate-500">
              Select a shared folder path to scan.
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
            )}
          </div>
        </div>

        {/* Middle: Dispatch.
            FE Gap 113 item 5: Submit was the last thing in a stack of four
            input panels, so the one action on this screen looked like another
            input. It now stands on its own beside the ledger it feeds. It is
            still the single action that both dispatches the batch and starts
            OCR extraction -- not two steps -- and the submit-result banners
            moved with it, since they report on this button rather than on any
            of the inputs. */}
        <div className="lg:col-span-3 space-y-4">
          <div className="glass-panel rounded-xl border border-[#222D3D] p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-white tracking-wide">Dispatch</h3>
              <p className="text-[11px] text-slate-500">
                Queues the batch and starts OCR extraction.
              </p>
            </div>

            <div className="flex items-center justify-between text-[11px] text-slate-500 border-y border-[#222D3D] py-2">
              <span>Files selected</span>
              <span className="font-mono font-semibold text-slate-300">{files.length}</span>
            </div>

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
          </div>
        </div>

        {/* Right Side: Status ledger tracking.
            FE Gap 113 item 6: 5 of 12 columns, down from two-thirds of the
            screen -- sized to the filename / stage / status it actually shows.
            Item 7: Pending sits at the top of this column, so one place shows
            the whole lifecycle (pending -> processing -> completed) instead of
            splitting the first stage off into the drop zone. */}
        <div className="lg:col-span-5 space-y-4">
          <PendingLedger files={files} onChange={setFiles} />

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
            files.length === 0 && (
              <div className="glass-panel rounded-xl border border-[#222D3D] p-8 text-center h-full min-h-[300px] flex flex-col items-center justify-center gap-3">
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
            )
          )}
        </div>
      </div>
      )}
    </div>
  );
}
