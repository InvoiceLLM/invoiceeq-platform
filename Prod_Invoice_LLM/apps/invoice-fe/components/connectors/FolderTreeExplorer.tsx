"use client";

/**
 * Feature 7 — FolderTreeExplorer.tsx
 *
 * Browses folder paths and files, allowing multi-file selection and
 * triggering background queue imports.
 */

import React, { useState, useEffect } from "react";
import {
  Folder,
  FileText,
  ChevronLeft,
  ChevronRight,
  DownloadCloud,
  CheckSquare,
  Square,
  Loader2,
  CornerDownRight,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";
import {
  ConnectorDirection,
  ConnectorProvider,
  FolderShortcut,
} from "@/lib/connectorFolderShortcut";

interface ConnectorFile {
  id: string;
  name: string;
  type: "file" | "folder";
  size_bytes: number;
}

interface FolderTreeExplorerProps {
  provider: ConnectorProvider;
  direction: ConnectorDirection;
  /**
   * Fired when the user saves the folder they are currently in as their
   * default browse folder. FE Gap 165: this used to hand back a bare string
   * that was, in practice, usually a raw folder id (see handleSetDefaultFolder)
   * and could not be navigated back to. It now carries both id and name.
   */
  onFolderSelected: (folder: FolderShortcut) => void;
  onClose: () => void;
  initialFolder?: FolderShortcut | null;
  /**
   * `import` (default): multi-file selection + queue import.
   * `folder`: pick the current folder only (FE Gap 219 Autopilot source_ref).
   */
  selectionMode?: "import" | "folder";
}

export default function FolderTreeExplorer({
  provider,
  direction,
  onFolderSelected,
  onClose,
  initialFolder = null,
  selectionMode = "import",
}: FolderTreeExplorerProps) {
  /**
   * The folders entered so far, root-first. Replaces the previous
   * `currentFolderId` + `folderHistory` pair, which tracked ids only -- with no
   * name for the folder you were standing in, "Map current folder" fell back to
   * the raw id and the path row rendered that id too (FE Gap 165).
   */
  const [path, setPath] = useState<FolderShortcut[]>(
    initialFolder?.id ? [initialFolder] : []
  );
  const currentFolder = path.length > 0 ? path[path.length - 1] : null;
  const currentFolderId = currentFolder?.id ?? null;
  const [files, setFiles] = useState<ConnectorFile[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  // FE Gap 267: was a plain boolean ("did the whole batch succeed"), which
  // only made sense together with the old abort-on-first-failure loop below.
  // Now holds a real per-batch summary since success/failure is per file.
  const [importCompleted, setImportCompleted] = useState<string | null>(null);
  // FE Gap 166: a failed import has to be visible, not just console-logged.
  // FE Gap 267: now a summary of every failure in the batch, not just the
  // first one that used to abort the whole loop.
  const [importError, setImportError] = useState<string | null>(null);

  // --- Load directory contents ---
  useEffect(() => {
    const fetchFiles = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const query = currentFolderId ? `&folder_id=${currentFolderId}` : "";
        const res = await fetch(`/api/connectors/files/${provider}?direction=${direction}${query}`);
        if (!res.ok) {
          const detail = await res.json().then((d) => d.detail).catch(() => "Failed to load files from cloud connector.");
          throw new Error(detail);
        }
        const data = await res.json();
        setFiles(data.files || []);
      } catch (err: any) {
        console.error("Connector file listing failed", err);
        setError(err.message || "Failed to connect or list directory.");
      } finally {
        setIsLoading(false);
      }
    };
    fetchFiles();
  }, [provider, direction, currentFolderId]);

  // --- Toggle File Selection ---
  const handleToggleSelect = (id: string) => {
    setSelectedFileIds((prev) =>
      prev.includes(id) ? prev.filter((fid) => fid !== id) : [...prev, id]
    );
  };

  // FE Gap 265: files in the current folder only -- matches how `files`
  // itself is already scoped (subfolder contents aren't held in state until
  // navigated into, so a recursive "select everything" isn't possible here).
  const selectableFileIds = files.filter((f) => f.type === "file").map((f) => f.id);
  const allSelected =
    selectableFileIds.length > 0 &&
    selectableFileIds.every((id) => selectedFileIds.includes(id));

  const handleToggleSelectAll = () => {
    setSelectedFileIds(allSelected ? [] : selectableFileIds);
  };

  // --- Navigation actions ---
  const handleFolderClick = (folder: ConnectorFile) => {
    if (folder.type !== "folder") return;
    setPath((prev) => [...prev, { id: folder.id, name: folder.name }]);
    setSelectedFileIds([]);
  };

  const handleGoBack = () => {
    setPath((prev) => prev.slice(0, -1));
    setSelectedFileIds([]);
  };

  // --- Save the current folder as this browser's default browse folder ---
  // FE Gap 165: the name came from `files.find(f => f.id === currentFolderId)`,
  // but `files` holds the *children* of the current folder -- the folder itself
  // is never in that list, so this always fell through to the raw folder id.
  // The breadcrumb carries the real name now.
  const handleSetDefaultFolder = () => {
    onFolderSelected(currentFolder ?? { id: null, name: "Root" });
  };

  // --- Trigger Ingestion Imports ---
  // FE Gap 267: this used to loop sequentially and abort the ENTIRE batch on
  // the first failed file (Gap 166's reasoning was "the rest are probably
  // failing for the same reason" -- confirmed wrong under real multi-file,
  // multi-cause testing: one file's unrelated permission/transient error
  // silently prevented every file queued after it from ever being attempted,
  // and the user only ever saw one generic error covering the whole
  // selection). Every file is now attempted independently and the result is
  // a real per-file count, not an all-or-nothing outcome.
  const handleImportSelected = async () => {
    if (selectedFileIds.length === 0) return;
    setIsImporting(true);
    setImportCompleted(null);
    setImportError(null);

    const results = await Promise.allSettled(
      selectedFileIds.map(async (fileId) => {
        const res = await fetch(`/api/connectors/import/${provider}?direction=${direction}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_id: fileId }),
        });
        if (!res.ok) {
          // FE Gap 166: the response status used to be ignored entirely --
          // only a network-level throw was caught -- so a rejected import
          // (unknown file id, quota exceeded, backend 500) still counted as
          // queued. Same `if (!res.ok) throw` shape as
          // components/settings/EmailSendersList.tsx.
          const detail = await res
            .json()
            .then((d) => d.detail || d.error)
            .catch(() => null);
          throw new Error(detail || "The connector rejected this import request.");
        }
        return fileId;
      })
    );

    const succeeded = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - succeeded;

    if (succeeded > 0) {
      setImportCompleted(
        failed > 0
          ? `${succeeded} of ${results.length} file(s) queued for import.`
          : `${succeeded} file(s) queued for import.`
      );
      setTimeout(() => setImportCompleted(null), 4000);
    }

    if (failed > 0) {
      const reasons = Array.from(
        new Set(
          results
            .filter((r): r is PromiseRejectedResult => r.status === "rejected")
            .map((r) => (r.reason instanceof Error ? r.reason.message : "Unknown error"))
        )
      );
      console.error("Some connector imports failed", reasons);
      setImportError(
        `${failed} of ${results.length} file(s) failed: ${reasons.join("; ")}`
      );
    }

    // Only clear the files that actually succeeded -- a failed selection
    // should stay checked so the user can see and retry exactly what didn't go through.
    const succeededIds = new Set(
      selectedFileIds.filter((_, idx) => results[idx].status === "fulfilled")
    );
    setSelectedFileIds((prev) => prev.filter((id) => !succeededIds.has(id)));
    setIsImporting(false);
  };

  const handleSelectFolder = () => {
    const folder = currentFolder ?? { id: null, name: "Root" };
    onFolderSelected(folder);
    onClose();
  };

  const isFolderMode = selectionMode === "folder";

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "—";
    const kb = bytes / 1024;
    return `${kb.toFixed(1)} KB`;
  };

  return (
    <div className="bg-[#111827] border border-[#1E293B] rounded-2xl flex flex-col h-[480px] overflow-hidden shadow-xl animate-in fade-in slide-in-from-bottom-3 duration-200">
      
      {/* Explorer Header */}
      <header className="px-5 py-4 border-b border-[#1E293B]/70 bg-[#151B26] flex items-center justify-between">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-white capitalize">
              {provider.replace("_", " ")} Explorer
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium capitalize">
              {direction}
            </span>
          </div>
          {/* Gap 165: this said "map folders for automated service flows" —
              there is no automated pull from a connector folder; files enter
              the pipeline only when they are imported here, explicitly. */}
          <p className="text-[10px] text-slate-400">
            Browse the connector and import the files you want processed.
          </p>
        </div>

        <button
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-200 bg-[#1E293B] border border-[#2D3F55] px-3 py-1.5 rounded-lg transition-colors"
        >
          Close
        </button>
      </header>

      {/* Explorer Path Navigation */}
      <div className="px-5 py-2.5 bg-[#0F141F] border-b border-[#1E293B]/40 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 text-slate-300 min-w-0">
          {path.length > 0 && (
            <button
              onClick={handleGoBack}
              className="flex items-center gap-1 text-blue-400 hover:text-blue-300 font-medium transition-colors shrink-0"
            >
              <ChevronLeft className="w-3.5 h-3.5" /> Back
            </button>
          )}
          <span className="text-slate-500 shrink-0">Path:</span>
          {/* Gap 165: folder names, not the opaque provider ids this used to print. */}
          <span className="font-mono text-slate-400 truncate">
            {["Root", ...path.map((f) => f.name)].join(" / ")}
          </span>
        </div>

        {/* Gap 165: was "Map current folder", which implied this folder would be
            picked up automatically. It is a per-browser starting point for
            browsing — nothing imports from it on its own. */}
        <button
          onClick={handleSetDefaultFolder}
          title="Remembers this folder as where browsing starts, in this browser. It does not import anything on its own."
          className="text-[10px] text-emerald-400 hover:text-emerald-300 flex items-center gap-1 font-medium shrink-0"
        >
          <CornerDownRight className="w-3.5 h-3.5" /> Start here next time
        </button>
      </div>

      {/* Directory Contents Panel */}
      <div className="flex-1 overflow-y-auto p-4 space-y-1">
        {isLoading ? (
          <div className="h-full flex items-center justify-center text-slate-500 text-xs gap-2.5">
            <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
            Reading cloud catalog…
          </div>
        ) : error ? (
          <div className="h-full flex flex-col items-center justify-center text-rose-400 text-xs py-8 text-center px-4 gap-2">
            <AlertTriangle className="w-6 h-6 text-rose-500" />
            <p className="font-semibold">Connection Error</p>
            <p className="text-[10px] text-slate-500 max-w-xs">{error}</p>
          </div>
        ) : files.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-500 text-xs py-8">
            This directory is empty.
          </div>
        ) : (
          files.map((file) => {
            const isSelected = selectedFileIds.includes(file.id);
            const isFile = file.type === "file";

            return (
              <div
                key={file.id}
                onClick={() => !isFile && handleFolderClick(file)}
                className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl border transition-all ${
                  isFile
                    ? "bg-[#151B26]/50 border-[#1E293B]/40 hover:border-slate-700/50"
                    : "bg-[#1E293B]/20 border-dashed border-[#2D3F55]/60 hover:bg-[#1E293B]/40 hover:border-blue-500/40 cursor-pointer"
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  {/* Multiselect Checkboxes for Files */}
                  {isFile && !isFolderMode && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggleSelect(file.id);
                      }}
                      className="text-slate-500 hover:text-slate-300"
                      aria-label={isSelected ? `Deselect ${file.name}` : `Select ${file.name}`}
                    >
                      {isSelected ? (
                        <CheckSquare className="w-4 h-4 text-blue-400" />
                      ) : (
                        <Square className="w-4 h-4 text-slate-600" />
                      )}
                    </button>
                  )}

                  <div className="shrink-0">
                    {isFile ? (
                      <FileText className="w-4 h-4 text-slate-400" />
                    ) : (
                      <Folder className="w-4 h-4 text-blue-400 fill-blue-400/10" />
                    )}
                  </div>

                  <span className="text-xs text-slate-200 font-medium truncate max-w-[280px]">
                    {file.name}
                  </span>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-slate-500 font-mono">
                    {isFile ? formatSize(file.size_bytes) : "Folder"}
                  </span>
                  {!isFile && <ChevronRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Explorer Footer Action Bar */}
      <footer className="px-5 py-4 border-t border-[#1E293B]/70 bg-[#151B26] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-slate-400">
            {isFolderMode
              ? `Current folder: ${currentFolder?.name ?? "Root"}`
              : `${selectedFileIds.length} file(s) selected`}
          </span>
          {/* FE Gap 265: bulk-select every file in the current folder. */}
          {!isFolderMode && selectableFileIds.length > 0 && (
            <button
              type="button"
              onClick={handleToggleSelectAll}
              className="flex items-center gap-1 text-[10px] font-medium text-blue-400 transition-colors hover:text-blue-300"
            >
              {allSelected ? (
                <>
                  <CheckSquare className="w-3.5 h-3.5" /> Deselect All
                </>
              ) : (
                <>
                  <Square className="w-3.5 h-3.5" /> Select All
                </>
              )}
            </button>
          )}
        </div>

        <div className="flex items-center gap-3">
          {!isFolderMode && importCompleted && (
            <span className="text-[10px] text-emerald-400 font-medium flex items-center gap-1">
              <CheckCircle className="w-3.5 h-3.5" /> {importCompleted}
            </span>
          )}

          {!isFolderMode && importError && (
            <span
              title={importError}
              className="text-[10px] text-rose-400 font-medium flex items-center gap-1 max-w-[320px] truncate"
            >
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {importError}
            </span>
          )}

          {isFolderMode ? (
            <button
              onClick={handleSelectFolder}
              className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold flex items-center gap-2 transition-all shadow-md shadow-violet-900/10"
            >
              <CornerDownRight className="w-3.5 h-3.5" />
              Select This Folder
            </button>
          ) : (
            <button
              onClick={handleImportSelected}
              disabled={selectedFileIds.length === 0 || isImporting}
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center gap-2 transition-all shadow-md shadow-blue-900/10"
            >
              {isImporting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <DownloadCloud className="w-3.5 h-3.5" />
              )}
              Import Selected
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}
