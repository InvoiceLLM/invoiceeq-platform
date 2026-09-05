"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
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
import { useSearchParams } from "next/navigation";
import { Lock, FolderOpen } from "lucide-react";
import { PageHeaderActions, usePageHeader } from "../../components/layout/PageHeaderContext";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../hooks/useAuth";
import {
  acceptedFormatsLabel,
  acceptedUploadExtensions,
  loadFeatureFlags,
  type FeatureFlags,
} from "../../lib/featureFlags";

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

function IngestionPageContent() {
  // FE Gap 110: title + NOVA badge now live in Shell's one shared header.
  usePageHeader({
    title: "File Ingestion",
    agentIcon: "🤖",
    agentName: "NOVA",
    agentRole: "Extraction & Validation",
  });

  // FE Gap 457: the Invoice Builder deep-links into this page (see the effect
  // below the outbound state).
  const searchParams = useSearchParams();

  const [files, setFiles] = useState<File[]>(() => cachedFiles);
  const [tags, setTags] = useState<string[]>(() => cachedTags);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // FE Feature 19: the folder picker below is a THIRD entry point for files,
  // alongside DropZone's two guards, so it reads the same accept list. Same
  // one-request-per-page `loadFeatureFlags()` promise the drop zone uses.
  const [uploadFeatureFlags, setUploadFeatureFlags] = useState<FeatureFlags | null>(null);
  useEffect(() => {
    let cancelled = false;
    void loadFeatureFlags().then((flags) => {
      if (!cancelled) setUploadFeatureFlags(flags);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const acceptedExtensions = acceptedUploadExtensions(uploadFeatureFlags);

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
  // Gap 405: per-user Send Invoices visibility, on top of the tenant-wide
  // sendEnabled flag above -- both must be true for this user to see Sending.
  const { canSendInvoices } = useAuth();
  const sendVisible = sendEnabled && canSendInvoices;
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
    // FE Gap 434 / BE Gap 429: how long skipped/failed/empty sync-history rows
    // are kept before the backend hard-deletes them (7-365, default 90).
    // Imported rows are always kept, for duplicate detection.
    history_retention_days: 90,
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
          history_retention_days: res.data.history_retention_days ?? 90,
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

  // FE Gap 322: Autopilot's source_type vocabulary ('gdrive') still differs
  // from Connectors' provider vocabulary ('google_drive'), so the translation
  // stays -- it is just no longer a ternary now that Salesforce is gone.
  const autopilotConnectorProvider = "google_drive" as const;
  const autopilotConnectorActive =
    autopilotConnectorStatus?.[autopilotConnectorProvider] === "Active";

  // Gap 288: shared by Save and Sync Now so a folder picked in the browser
  // (which only ever touches local `autopilotConfig` state -- see
  // FolderTreeExplorer's onFolderSelected below) can't silently diverge from
  // what's persisted. Sync Now used to skip this and hit the backend
  // directly, so it synced whatever source_ref was last *saved*, not
  // whatever the auditor had just picked -- reproducible by picking a new
  // folder and clicking Sync Now without clicking Save Config first.
  const saveAutopilotConfigPayload = () =>
    apiClient.put("/autopilot/config", {
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
      history_retention_days: autopilotConfig.history_retention_days,
    });

  // Gap 288: distinguishes "the backend responded with a real error" from
  // "the request never got a clean response at all" (network failure, proxy
  // timeout, non-JSON body) -- the two used to collapse into one generic,
  // uninformative fallback string.
  const describeAutopilotError = (err: any, action: string) => {
    const detail = err?.response?.data?.detail;
    if (detail) return detail;
    if (err?.response) {
      return `${action} failed: unexpected server error (HTTP ${err.response.status}).`;
    }
    return `${action} failed: could not reach the server (${err?.message || err?.code || "network error"}). Check your connection and try again.`;
  };

  const handleSaveAutopilotConfig = async () => {
    setAutopilotSaving(true);
    setAutopilotError(null);
    setAutopilotSyncResult(null);
    try {
      await saveAutopilotConfigPayload();
      setAutopilotSyncResult("Configuration saved successfully.");
      setTimeout(() => setAutopilotSyncResult(null), 4000);
    } catch (err: any) {
      setAutopilotError(describeAutopilotError(err, "Save"));
    } finally {
      setAutopilotSaving(false);
    }
  };

  const handleSyncNow = async () => {
    setAutopilotSyncing(true);
    setAutopilotError(null);
    setAutopilotSyncResult(null);
    try {
      await saveAutopilotConfigPayload();
      const res = await apiClient.post("/autopilot/sync");
      setAutopilotSyncResult(res.data.message);
      setAutopilotHistoryKey((k) => k + 1); // refresh history table
    } catch (err: any) {
      setAutopilotError(describeAutopilotError(err, "Sync"));
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
        // Gap 405: only auto-switch to a tab this user can actually see --
        // canSendInvoices=false must not land them on a tab with no visible
        // button and nothing rendered.
        if (!data.receive_invoices_enabled && data.send_invoices_enabled && canSendInvoices) {
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

  // FE Gap 457: the Invoice Builder hands off with
  // /ingestion?tab=sending&builtInvoice=<invoice_id>&batch=<batch_id>&name=<label>
  // after POST /outbound-invoices/build. Nothing on this page read those
  // params, so a freshly created invoice landed on Receiving with an idle
  // outbound ledger. Seeding one row reuses the upload path's render verbatim:
  // SendInvoiceStatusTable polls GET /invoices/{id} and LogTerminal subscribes
  // to the batch id, and both work for a builder-created invoice because it is
  // an ordinary outbound row.
  //
  // Keyed on sendVisible rather than mount-once: it is false until the
  // service-flow fetch above resolves, and Gap 405 means a user without
  // canSendInvoices must never be moved onto a tab they cannot see. Re-running
  // is harmless -- the seed is idempotent on invoice id, and the deps do not
  // change when the user clicks a tab by hand.
  useEffect(() => {
    if (searchParams.get("tab") !== "sending" || !sendVisible) return;
    setActiveTab("sending");

    const builtInvoice = searchParams.get("builtInvoice");
    const batch = searchParams.get("batch");
    if (!builtInvoice || !batch) return;
    // useSearchParams() already percent-decodes, so the builder's
    // encodeURIComponent'd label is used as-is -- decoding it a second time
    // would throw URIError on any invoice number containing a literal "%".
    const name = searchParams.get("name") || "New invoice";
    setOutboundInvoices((prev) =>
      prev.some((inv) => inv.id === builtInvoice)
        ? prev
        : [...prev, { id: builtInvoice, batchId: batch, name }]
    );
  }, [searchParams, sendVisible]);

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

  // FE Gap 406 (2026-09-02): the server-path directory watcher form
  // (directoryPath/isScanning/handleWatchDirectory, POST /invoices/watcher)
  // was removed here -- a raw server-filesystem path input is meaningless in
  // a hosted multi-tenant SaaS deployment, and the browser folder picker
  // below (Gap 145) is the working, modern equivalent. watcherError/
  // watcherResult are kept: the folder picker's own onChange handler still
  // uses both to report what it found. The backend endpoint
  // (`routers/invoices.py::start_directory_watcher`) is deliberately left
  // in place -- see be_features_tracker.md Gap 406 for why removing it is a
  // separate, later decision.
  const [watcherError, setWatcherError] = useState<string | null>(null);
  const [watcherResult, setWatcherResult] = useState<{ files_found: number; files_queued: number } | null>(null);
  // FE Gap 69: collapsed by default so the left column fits the viewport
  // without scrolling. Bulk Directory Scan is the least-used control in this
  // column (a shared-drop-folder path, not the normal drag-and-drop path), so
  // it's the right one to fold away -- the header row stays visible so it's
  // still discoverable, unlike being pushed below the fold entirely.
  const [isDirectoryScanOpen, setIsDirectoryScanOpen] = useState(false);

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

  // Gap 405: sendVisible (tenant flag AND per-user permission) replaces
  // sendEnabled everywhere Sending's visibility, not just its backing data,
  // is decided -- a user without canSendInvoices must not see the tab, the
  // tab button, or land on it via the auto-switch effect above.
  const showTabs = receiveEnabled && sendVisible;
  const showReceiving = activeTab === "receiving" && (receiveEnabled || !sendVisible);
  const showSending = activeTab === "sending" && sendVisible;
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
          {sendVisible && (
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
                /* Gap 284: exactly one LogTerminal per outbound file. This
                   block used to render one here *and* SendInvoiceStatusTable
                   rendered a second one internally (Gap 134), keyed on the
                   invoice id rather than the batch id — see that component's
                   header comment. The internal one is gone; this one keeps the
                   real `batch_id` from POST /outbound-invoices/upload, which is
                   the id the SSE channel is actually named after.
                   `includeStatusEvents` because the outbound worker publishes
                   stage events, never `log_line` events. */
                <div key={inv.id} className="space-y-4">
                  <SendInvoiceStatusTable invoiceId={inv.id} fileName={inv.name} />
                  <LogTerminal batchId={inv.batchId} includeStatusEvents />
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

          {/* Bulk Directory Scan: bulk-ingest a local folder in one pass, no
              per-file drag-and-drop. FE Gap 69: collapsed into a disclosure so
              it stops pushing itself off-screen. Header row is always
              rendered and always clickable. FE Gap 406: the server-path half
              of this card was removed -- browser folder selection (Gap 145)
              is now the only mechanism here. */}
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
            {/* FE Gap 113 item 3 & Gap 145: client-side folder selection. */}
            <p className="text-[11px] text-slate-500">
              Select a local folder containing the invoices you want to bulk-ingest.
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
                  // FE Feature 19: the folder path filters on the same accept
                  // list the drop zone uses, and its message is built from the
                  // same list -- otherwise a folder of photos reads as empty.
                  const selectedList = Array.from(e.target.files || []);
                  const accepted = selectedList.filter((f) => {
                    const lowerName = f.name.toLowerCase();
                    return acceptedExtensions.some((ext) => lowerName.endsWith(ext));
                  });
                  if (accepted.length > 0) {
                    setFiles((prev) => [...prev, ...accepted]);
                    setWatcherResult({ files_found: selectedList.length, files_queued: accepted.length });
                    setWatcherError(null);
                  } else if (selectedList.length > 0) {
                    setWatcherError(`No ${acceptedFormatsLabel(acceptedExtensions)} files found in selected folder.`);
                  }
                } catch (err) {
                  console.error("Failed to read selected folder", err);
                  setWatcherError("Couldn't read the selected folder. Please try again.");
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
                  {/* Source type — FE Gap 322: the "Cloud Source" toggle was a
                      2-entry Drive/Salesforce picker. With Salesforce removed it
                      would render a single button that is always already
                      selected and does nothing, so the whole block is gone.
                      source_type stays pinned to its 'gdrive' default (see the
                      autopilotConfig initial state and loadAutopilotConfig). */}

                  {/* Source folder — FE Gap 219 */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">
                      Google Drive Folder
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

                  {/* History retention (FE Gap 434) */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] text-slate-400 font-medium uppercase tracking-wider">History Retention (Days)</label>
                    <input
                      type="number"
                      min={7}
                      max={365}
                      value={autopilotConfig.history_retention_days}
                      onChange={(e) =>
                        setAutopilotConfig((c) => ({
                          ...c,
                          history_retention_days: Number(e.target.value),
                        }))
                      }
                      placeholder="90"
                      className="w-full bg-[#0B0F19] border border-[#222D3D] rounded-lg px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500/60"
                    />
                    <p className="text-[10px] text-slate-500">
                      Skipped, failed and empty sync-history entries older than this are deleted automatically. Imported entries are kept for duplicate detection.
                    </p>
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
            <AutopilotHistoryTable
              key={autopilotHistoryKey}
              autoRefresh={autopilotSyncing}
              retentionDays={autopilotConfig.history_retention_days}
            />
          </div>

          {autopilotBrowsing && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
              <div className="w-full max-w-lg">
                <FolderTreeExplorer
                  provider={autopilotConnectorProvider}
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

// useSearchParams() requires a Suspense boundary in the app router -- same
// wrapper shape as app/trainer/page.tsx and app/invoices/outbound-builder/page.tsx.
export default function IngestionPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-white">Loading File Ingestion…</div>}>
      <IngestionPageContent />
    </Suspense>
  );
}
