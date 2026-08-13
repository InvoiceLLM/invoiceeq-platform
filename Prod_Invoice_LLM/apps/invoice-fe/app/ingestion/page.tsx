"use client";

import React, { useState, useEffect, useCallback } from "react";
import { UploadCloud, CheckCircle, AlertCircle, RefreshCw, FolderSearch, Send, ChevronDown, Bot, Zap, Settings2 } from "lucide-react";
import TagSelector from "../../components/ingestion/TagSelector";
import DropZone from "../../components/ingestion/DropZone";
import StatusTable from "../../components/ingestion/StatusTable";
import PendingLedger from "../../components/ingestion/PendingLedger";
import LogTerminal from "../../components/ingestion/LogTerminal";
import SendInvoiceStatusTable from "../../components/ingestion/SendInvoiceStatusTable";
import ConnectorBrowseBar from "../../components/ingestion/ConnectorBrowseBar";
import AutopilotHistoryTable from "../../components/ingestion/AutopilotHistoryTable";
import FolderTreeExplorer from "../../components/connectors/FolderTreeExplorer";
import Link from "next/link";
import { Lock, FolderOpen } from "lucide-react";
import { PageHeaderActions, usePageHeader } from "../../components/layout/PageHeaderContext";
import { apiClient } from "../../lib/apiClient";

type IngestionTab = "receiving" | "sending" | "autopilot";

// Module-level cache to persist selected files/tags across page navigations (Gap 146)
let cachedFiles: File[] = [];
let cachedTags: string[] = [];
let cachedOutboundFiles: File[] = [];

// Gap 204: same module-level pattern as Gap 146 above, but for a batch that's
// already been submitted and is actively processing -- without this, leaving
// the Ingestion screen mid-batch and coming back showed an empty ledger and a
// dead log terminal even though the worker was still running.
let cachedBatchId: string | null = null;
let cachedJobIds: string[] = [];
let cachedTrackedFiles: Array<{ name: string; size: number }> = [];

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

  // Feature 13: Autopilot config state
  const [autopilotConfig, setAutopilotConfig] = useState({
    source_type: "gdrive",
    source_ref: "",
    flow_direction: "INBOUND",
    trigger_mode: "interval",
    trigger_value: "60",
    notify_emails_raw: "",  // comma-separated string for the input
    send_approval_links: false,
  });
  const [autopilotConfigLoading, setAutopilotConfigLoading] = useState(false);
  const [autopilotSaving, setAutopilotSaving] = useState(false);
  const [autopilotSyncing, setAutopilotSyncing] = useState(false);
  const [autopilotSyncResult, setAutopilotSyncResult] = useState<string | null>(null);
  const [autopilotError, setAutopilotError] = useState<string | null>(null);
  const [autopilotHistoryKey, setAutopilotHistoryKey] = useState(0); // bump to force table refresh
  const [autopilotSourceRefName, setAutopilotSourceRefName] = useState("");
  const [autopilotConnectorStatus, setAutopilotConnectorStatus] = useState<{
    google_drive: string;
    salesforce: string;
  } | null>(null);
  const [autopilotConnectorChecking, setAutopilotConnectorChecking] = useState(true);
  const [autopilotBrowsing, setAutopilotBrowsing] = useState(false);

  // Load existing autopilot config on mount
  const loadAutopilotConfig = useCallback(async () => {
    try {
      setAutopilotConfigLoading(true);
      const res = await apiClient.get("/autopilot/config");
      if (res.data) {
        setAutopilotConfig({
          source_type: res.data.source_type || "gdrive",
          source_ref: res.data.source_ref || "",
          flow_direction: res.data.flow_direction || "INBOUND",
          trigger_mode: res.data.trigger_mode || "interval",
          trigger_value: res.data.trigger_value || "60",
          notify_emails_raw: (res.data.notify_emails || []).join(", "),
          send_approval_links: res.data.send_approval_links ?? false,
        });
      }
    } catch {
      // No config yet — defaults are fine
    } finally {
      setAutopilotConfigLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAutopilotConfig();
  }, [loadAutopilotConfig]);

  useEffect(() => {
    let cancelled = false;
    setAutopilotConnectorChecking(true);
    fetch("/api/connectors/status")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) setAutopilotConnectorStatus(data);
      })
      .finally(() => {
        if (!cancelled) setAutopilotConnectorChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const autopilotConnectorProvider =
    autopilotConfig.source_type === "gdrive" ? "google_drive" : "salesforce";
  const autopilotConnectorActive =
    autopilotConnectorStatus?.[autopilotConnectorProvider as "google_drive" | "salesforce"] === "Active";

  const handleSaveAutopilotConfig = async () => {
    setAutopilotSaving(true);
    setAutopilotError(null);
    setAutopilotSyncResult(null);
    try {
      await apiClient.put("/autopilot/config", {
        source_type: autopilotConfig.source_type,
        source_ref: autopilotConfig.source_ref.trim(),
        flow_direction: autopilotConfig.flow_direction,
        trigger_mode: autopilotConfig.trigger_mode,
        trigger_value: autopilotConfig.trigger_value.trim(),
        notify_emails: autopilotConfig.notify_emails_raw
          .split(",")
          .map((e: string) => e.trim())
          .filter(Boolean),
        send_approval_links: autopilotConfig.send_approval_links,
      });
      setAutopilotSyncResult("Configuration saved successfully.");
      setTimeout(() => setAutopilotSyncResult(null), 4000);
    } catch (err: any) {
      setAutopilotError(err?.response?.data?.detail || "Failed to save configuration.");
    } finally {
      setAutopilotSaving(false);
    }
  };

  const handleSyncNow = async () => {
    setAutopilotSyncing(true);
    setAutopilotError(null);
    setAutopilotSyncResult(null);
    try {
      const res = await apiClient.post("/autopilot/sync");
      setAutopilotSyncResult(res.data.message);
      setAutopilotHistoryKey((k) => k + 1); // refresh history table
    } catch (err: any) {
      setAutopilotError(err?.response?.data?.detail || "Sync failed. Please check your configuration.");
    } finally {
      setAutopilotSyncing(false);
    }
  };

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
  const [batchId, setBatchId] = useState<string | null>(() => cachedBatchId);
  const [jobIds, setJobIds] = useState<string[]>(() => cachedJobIds);
  const [trackedFiles, setTrackedFiles] = useState<Array<{ name: string; size: number }>>(() => cachedTrackedFiles);

  // Gap 204: keep the module-level cache in sync so an in-flight batch
  // reattaches (StatusTable/LogTerminal) instead of resetting to empty when
  // the user navigates away and back.
  useEffect(() => {
    cachedBatchId = batchId;
  }, [batchId]);

  useEffect(() => {
    cachedJobIds = jobIds;
  }, [jobIds]);

  useEffect(() => {
    cachedTrackedFiles = trackedFiles;
  }, [trackedFiles]);

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
  const showReceiving = activeTab === "receiving" && (receiveEnabled || !sendEnabled);
  const showSending = activeTab === "sending" && sendEnabled;
  const showAutopilot = activeTab === "autopilot";

  return (
    <div className="space-y-6">
      {/* Tab toggle in header — always shown (Autopilot is always available) */}
      <PageHeaderActions>
        <div className="flex items-center gap-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg p-1 w-fit">
          {receiveEnabled && (
            <button
              onClick={() => setActiveTab("receiving")}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                activeTab === "receiving" ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Receiving
            </button>
          )}
          {sendEnabled && (
            <button
              onClick={() => setActiveTab("sending")}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                activeTab === "sending" ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Sending
            </button>
          )}
          {/* Feature 13: Autopilot tab — always visible */}
          <button
            onClick={() => setActiveTab("autopilot")}
            className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors flex items-center gap-1 ${
              activeTab === "autopilot" ? "bg-violet-600 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Bot className="w-3 h-3" />
            Autopilot
          </button>
        </div>
      </PageHeaderActions>

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
            {/* FE Gap 113 item 3 & Gap 145: support both client-side folder selection and server-path watcher */}
            <p className="text-[11px] text-slate-500">
              Select a local folder or enter a shared server directory path.
            </p>

            {/* Gap 145: Browser Local Folder Picker */}
            <input
              type="file"
              ref={(ref) => {
                if (ref) {
                  ref.setAttribute("webkitdirectory", "");
                  ref.setAttribute("directory", "");
                }
              }}
              onChange={(e) => {
                // Gap 181: this had no error handling at all -- if reading the
                // selected folder ever throws (browser-specific security
                // policy, a huge/unusual directory, etc.), it surfaced as an
                // uncaught exception with no user-facing message, which is
                // consistent with reports of a bare "system error." Root
                // cause of the original report is still unconfirmed pending
                // a live repro; this ensures a failure here is never silent
                // or uncaught, whatever the underlying cause turns out to be.
                try {
                  const selectedList = Array.from(e.target.files || []);
                  const pdfs = selectedList.filter(
                    (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")
                  );
                  if (pdfs.length > 0) {
                    setFiles((prev) => [...prev, ...pdfs]);
                    setWatcherResult({ files_found: selectedList.length, files_queued: pdfs.length });
                    setWatcherError(null);
                  } else if (selectedList.length > 0) {
                    setWatcherError("No PDF files found in selected folder.");
                  }
                } catch (err) {
                  console.error("Failed to read selected folder", err);
                  setWatcherError("Couldn't read the selected folder. Try again, or use the server directory path below instead.");
                } finally {
                  // Reset so re-selecting the same folder fires onChange again.
                  e.target.value = "";
                }
              }}
              className="hidden"
              id="bulk-folder-input"
            />
            <button
              type="button"
              onClick={() => document.getElementById("bulk-folder-input")?.click()}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-medium border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition-all"
            >
              <FolderSearch className="w-3.5 h-3.5" />
              <span>Select Folder from Computer</span>
            </button>

            <div className="flex items-center gap-2 text-[10px] text-slate-500 my-1">
              <div className="h-px bg-[#222D3D] flex-1" />
              <span>OR SERVER PATH</span>
              <div className="h-px bg-[#222D3D] flex-1" />
            </div>

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
                  "Scan Directory Path"
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
      {/* ------------------------------------------------------------------ */}
      {/* Feature 13: Autopilot Tab                                           */}
      {/* ------------------------------------------------------------------ */}
      {showAutopilot && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Config Form */}
          <div className="space-y-4">
            <div className="glass-panel rounded-xl border border-[#222D3D] p-5 space-y-4">
              <div className="flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-violet-400" />
                <h3 className="text-sm font-semibold text-white">Autopilot Configuration</h3>
              </div>

              {autopilotConfigLoading ? (
                <div className="flex items-center gap-2 text-xs text-slate-500 py-4">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Loading config…
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Source type */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Cloud Source</label>
                    <div className="flex gap-3">
                      {(["gdrive", "salesforce"] as const).map((src) => (
                        <button
                          key={src}
                          onClick={() => setAutopilotConfig((c) => ({ ...c, source_type: src }))}
                          className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-all ${
                            autopilotConfig.source_type === src
                              ? "bg-violet-600/20 border-violet-500/40 text-violet-300"
                              : "bg-slate-900/40 border-[#222D3D] text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          {src === "gdrive" ? "Google Drive" : "Salesforce"}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Source folder — FE Gap 219 */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">
                      {autopilotConfig.source_type === "gdrive" ? "Google Drive Folder" : "Salesforce Directory"}
                    </label>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 min-w-0 rounded-lg border border-[#222D3D] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 truncate">
                        {autopilotConfig.source_ref
                          ? autopilotSourceRefName || autopilotConfig.source_ref
                          : "No folder selected"}
                      </div>
                      {autopilotConnectorChecking ? (
                        <span className="text-[10px] text-slate-500 shrink-0">Checking…</span>
                      ) : autopilotConnectorActive ? (
                        <button
                          type="button"
                          onClick={() => setAutopilotBrowsing(true)}
                          className="shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-lg text-[11px] font-medium bg-violet-600/20 border border-violet-500/40 text-violet-300 hover:bg-violet-600/30 transition-colors"
                        >
                          <FolderOpen className="w-3.5 h-3.5" />
                          Browse →
                        </button>
                      ) : (
                        <span className="shrink-0 flex items-center gap-1 text-[10px] text-slate-500">
                          <Lock className="w-3 h-3" />
                          <Link href="/settings/connectors" className="underline hover:text-white">
                            Connect in Settings
                          </Link>
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Flow direction */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Flow Direction</label>
                    <div className="flex gap-3">
                      {(["INBOUND", "OUTBOUND"] as const).map((dir) => (
                        <button
                          key={dir}
                          onClick={() => setAutopilotConfig((c) => ({ ...c, flow_direction: dir }))}
                          className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-all ${
                            autopilotConfig.flow_direction === dir
                              ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                              : "bg-slate-900/40 border-[#222D3D] text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          {dir === "INBOUND" ? "Inbound (AP)" : "Outbound (AR)"}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Schedule */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Schedule</label>
                    <div className="flex gap-2">
                      <select
                        value={autopilotConfig.trigger_mode}
                        onChange={(e) => setAutopilotConfig((c) => ({ ...c, trigger_mode: e.target.value }))}
                        className="bg-[#0B0F19] border border-[#222D3D] rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-violet-500/60"
                      >
                        <option value="interval">Interval (minutes)</option>
                        <option value="cron">Cron expression</option>
                      </select>
                      <input
                        type="text"
                        value={autopilotConfig.trigger_value}
                        onChange={(e) => setAutopilotConfig((c) => ({ ...c, trigger_value: e.target.value }))}
                        placeholder={autopilotConfig.trigger_mode === "interval" ? "60" : "0 * * * *"}
                        className="flex-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500/60"
                      />
                    </div>
                  </div>

                  {/* Notification emails */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">Notification Emails</label>
                    <input
                      type="text"
                      value={autopilotConfig.notify_emails_raw}
                      onChange={(e) => setAutopilotConfig((c) => ({ ...c, notify_emails_raw: e.target.value }))}
                      placeholder="email@example.com, another@example.com"
                      className="w-full bg-[#0B0F19] border border-[#222D3D] rounded-lg px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500/60"
                    />
                  </div>

                  {/* Approval links toggle */}
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={autopilotConfig.send_approval_links}
                      onChange={(e) => setAutopilotConfig((c) => ({ ...c, send_approval_links: e.target.checked }))}
                      className="w-4 h-4 rounded border-[#222D3D] accent-violet-500"
                    />
                    <span className="text-xs text-slate-300">Include manual approval link in notification emails</span>
                  </label>

                  {/* Result / error banners */}
                  {autopilotSyncResult && (
                    <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-lg text-xs">
                      <CheckCircle className="w-4 h-4 flex-shrink-0" />
                      <span>{autopilotSyncResult}</span>
                    </div>
                  )}
                  {autopilotError && (
                    <div className="flex items-center gap-2 p-3 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-xs">
                      <AlertCircle className="w-4 h-4 flex-shrink-0" />
                      <span>{autopilotError}</span>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-3 pt-1">
                    <button
                      onClick={handleSaveAutopilotConfig}
                      disabled={autopilotSaving}
                      className="flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-xs font-semibold border border-violet-500/40 bg-violet-600/20 text-violet-300 hover:bg-violet-600/30 disabled:opacity-50 disabled:cursor-wait transition-all"
                    >
                      {autopilotSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Settings2 className="w-3.5 h-3.5" />}
                      {autopilotSaving ? "Saving…" : "Save Config"}
                    </button>
                    <button
                      onClick={handleSyncNow}
                      disabled={autopilotSyncing}
                      className="flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-xs font-semibold border border-blue-500/40 bg-blue-600/20 text-blue-300 hover:bg-blue-600/30 disabled:opacity-50 disabled:cursor-wait transition-all"
                    >
                      {autopilotSyncing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
                      {autopilotSyncing ? "Syncing…" : "Sync Now"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right: Sync History Table */}
          <div>
            <AutopilotHistoryTable key={autopilotHistoryKey} autoRefresh={autopilotSyncing} />
          </div>

          {autopilotBrowsing && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
              <div className="w-full max-w-lg">
                <FolderTreeExplorer
                  provider={autopilotConnectorProvider as "google_drive" | "salesforce"}
                  direction="inbound"
                  selectionMode="folder"
                  onFolderSelected={(folder) => {
                    if (folder.id) {
                      setAutopilotConfig((c) => ({ ...c, source_ref: folder.id as string }));
                      setAutopilotSourceRefName(folder.name);
                    }
                  }}
                  onClose={() => setAutopilotBrowsing(false)}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
