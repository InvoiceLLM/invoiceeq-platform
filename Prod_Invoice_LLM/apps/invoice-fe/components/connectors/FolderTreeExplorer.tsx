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

interface ConnectorFile {
  id: string;
  name: string;
  type: "file" | "folder";
  size_bytes: number;
}

interface FolderTreeExplorerProps {
  provider: "google_drive" | "salesforce";
  direction: "inbound" | "outbound";
  onFolderSelected: (folderName: string) => void;
  onClose: () => void;
}

export default function FolderTreeExplorer({
  provider,
  direction,
  onFolderSelected,
  onClose,
}: FolderTreeExplorerProps) {
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [folderHistory, setFolderHistory] = useState<string[]>([]);
  const [files, setFiles] = useState<ConnectorFile[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importCompleted, setImportCompleted] = useState(false);

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

  // --- Navigation actions ---
  const handleFolderClick = (folder: ConnectorFile) => {
    if (folder.type !== "folder") return;
    if (currentFolderId) {
      setFolderHistory((prev) => [...prev, currentFolderId]);
    }
    setCurrentFolderId(folder.id);
    setSelectedFileIds([]);
  };

  const handleGoBack = () => {
    const history = [...folderHistory];
    const prevFolder = history.pop() || null;
    setFolderHistory(history);
    setCurrentFolderId(prevFolder);
    setSelectedFileIds([]);
  };

  // --- Select Folder for Mapping ---
  const handleMapFolder = () => {
    const currentName = currentFolderId
      ? files.find((f) => f.id === currentFolderId)?.name || currentFolderId
      : "Root";
    onFolderSelected(currentName);
  };

  // --- Trigger Ingestion Imports ---
  const handleImportSelected = async () => {
    if (selectedFileIds.length === 0) return;
    setIsImporting(true);
    setImportCompleted(false);

    try {
      // Import sequentially in background queue
      for (const fileId of selectedFileIds) {
        await fetch(`/api/connectors/import/${provider}?direction=${direction}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_id: fileId }),
        });
      }
      setImportCompleted(true);
      setSelectedFileIds([]);
      setTimeout(() => setImportCompleted(false), 4000);
    } catch (err) {
      console.error("Bulk connector import failed", err);
    } finally {
      setIsImporting(false);
    }
  };

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
          <p className="text-[10px] text-slate-400">
            Browse files and map folders for automated service flows.
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
        <div className="flex items-center gap-2 text-slate-300">
          {(currentFolderId || folderHistory.length > 0) && (
            <button
              onClick={handleGoBack}
              className="flex items-center gap-1 text-blue-400 hover:text-blue-300 font-medium transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" /> Back
            </button>
          )}
          <span className="text-slate-500">Path:</span>
          <span className="font-mono text-slate-400">
            Root {currentFolderId ? `/ ${currentFolderId}` : ""}
          </span>
        </div>

        <button
          onClick={handleMapFolder}
          className="text-[10px] text-emerald-400 hover:text-emerald-300 flex items-center gap-1 font-medium"
        >
          <CornerDownRight className="w-3.5 h-3.5" /> Map current folder
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
                  {isFile && (
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
        <span className="text-[10px] text-slate-400">
          {selectedFileIds.length} file(s) selected
        </span>

        <div className="flex items-center gap-3">
          {importCompleted && (
            <span className="text-[10px] text-emerald-400 font-medium flex items-center gap-1">
              <CheckCircle className="w-3.5 h-3.5" /> Import request queued!
            </span>
          )}

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
        </div>
      </footer>
    </div>
  );
}
