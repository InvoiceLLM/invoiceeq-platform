"use client";

// =============================================================================
// FILE: components/chat/SessionRail.tsx
// FEATURE: FE Feature 22 Task 22.6 — the conversation list beside Ask / Chat.
//
// Extracted unchanged from `ThreadSidebar` in components/chat/ChatWindow.tsx
// (search, rename, delete, hide — FE Gaps 149, 216, 274 still hold), then:
//   - sessions are grouped under day headers ("Today", "Yesterday", "12 Sep"),
//     keeping the server's order — the grouping only inserts headers, it never
//     re-sorts;
//   - a 🔒 badge marks a private (`clearance: "exec"`) session.
//
// ⚠️ BACKEND GAP (plan open item #19): `GET /chat/sessions` does not return
// `clearance` today and does not filter by it, so the badge cannot appear yet —
// and an exec session is listed for every role. The FE renders what it is sent
// and filters nothing; the fix belongs in `routers/chat.py::list_sessions`.
// The Admin "Private" toggle is not built: `POST /chat/sessions` accepts no
// clearance to set.
// =============================================================================

import { useState } from "react";
import {
  Check,
  Loader2,
  Lock,
  MessageSquare,
  MessageSquarePlus,
  PanelLeftClose,
  Pencil,
  Search,
  Trash2,
  X,
} from "lucide-react";
import type { ChatSession } from "@/types/chat";

function toDate(dateStr: string): Date | null {
  if (!dateStr) return null;
  const isoStr = dateStr.endsWith("Z") || dateStr.includes("+") ? dateStr : `${dateStr.replace(" ", "T")}Z`;
  const date = new Date(isoStr);
  return isNaN(date.getTime()) ? null : date;
}

function formatSessionDate(dateStr: string): string {
  const date = toDate(dateStr);
  if (!date) return dateStr ?? "";

  const now = new Date();
  const diffHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);
  if (diffHours < 24) {
    return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
  }
  return date.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

/** The day header a session sits under, in the viewer's local calendar. */
export function sessionDayLabel(dateStr: string, now: Date = new Date()): string {
  const date = toDate(dateStr);
  if (!date) return "Earlier";
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Consecutive sessions sharing a day label, in the order given. Never re-sorts. */
export function groupSessionsByDay(sessions: ChatSession[], now: Date = new Date()) {
  const groups: { label: string; sessions: ChatSession[] }[] = [];
  for (const session of sessions) {
    const label = sessionDayLabel(session.updated_at || session.created_at, now);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.sessions.push(session);
    else groups.push({ label, sessions: [session] });
  }
  return groups;
}

interface SessionRailProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, newTitle: string) => void;
  onDelete: (id: string) => void;
  /** FE Gap 274: hides the whole panel. Undefined = no hide affordance rendered. */
  onHide?: () => void;
}

export default function SessionRail({
  sessions,
  activeSessionId,
  isLoading,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onHide,
}: SessionRailProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const filteredSessions = sessions.filter((s) =>
    (s.title || "New Chat").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const startRename = (e: React.MouseEvent, s: ChatSession) => {
    e.stopPropagation();
    setEditingId(s.id);
    setEditingTitle(s.title || "New Chat");
  };

  const confirmRename = (e: React.MouseEvent | React.FormEvent) => {
    e.preventDefault();
    if (editingId && editingTitle.trim()) {
      onRename(editingId, editingTitle.trim());
    }
    setEditingId(null);
  };

  const renderSession = (session: ChatSession) => {
    const isActive = session.id === activeSessionId;
    const isEditing = session.id === editingId;
    const isPrivate = session.clearance === "exec";

    return (
      <div
        key={session.id}
        id={`chat-session-${session.id}`}
        onClick={() => onSelect(session.id)}
        className={`
          group w-full text-left px-3 py-2.5 rounded-lg cursor-pointer
          flex items-start justify-between gap-2 transition-all duration-150
          ${isActive
            ? "bg-[#1E293B] border border-blue-800/40 text-white"
            : "text-slate-400 hover:bg-[#1E293B]/40 hover:text-slate-200 border border-transparent"
          }
        `}
      >
        <div className="flex items-start gap-2 min-w-0 flex-1">
          <MessageSquare
            className={`w-4 h-4 mt-0.5 shrink-0 ${isActive ? "text-blue-400" : "text-slate-500 group-hover:text-slate-400"}`}
          />
          <div className="flex-1 min-w-0">
            {isEditing ? (
              <form onSubmit={confirmRename} className="flex items-center gap-1">
                <input
                  type="text"
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  autoFocus
                  className="w-full bg-slate-900 text-xs text-white px-1.5 py-0.5 rounded border border-blue-500 outline-none"
                />
                <button type="submit" className="p-0.5 text-emerald-400 hover:text-emerald-300">
                  <Check className="w-3 h-3" />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingId(null);
                  }}
                  className="p-0.5 text-slate-400 hover:text-slate-300"
                >
                  <X className="w-3 h-3" />
                </button>
              </form>
            ) : (
              <>
                <p className="text-xs font-medium truncate flex items-center gap-1">
                  {isPrivate && (
                    <span data-testid={`chat-session-private-${session.id}`} title="Private — visible to Admins only">
                      <Lock className="w-3 h-3 shrink-0 text-amber-400" aria-label="Private" />
                    </span>
                  )}
                  <span className="truncate">{session.title || "New Chat"}</span>
                </p>
                <p className="text-[10px] text-slate-500 mt-0.5">
                  {formatSessionDate(session.updated_at || session.created_at)}
                  {session.message_count > 0 && <span className="ml-1.5">· {session.message_count} msgs</span>}
                </p>
              </>
            )}
          </div>
        </div>

        {!isEditing && (
          <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 shrink-0 transition-opacity">
            <button
              type="button"
              onClick={(e) => startRename(e, session)}
              title="Rename thread"
              className="p-1 text-slate-400 hover:text-blue-400 rounded hover:bg-slate-800"
            >
              <Pencil className="w-3 h-3" />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(session.id);
              }}
              title="Delete thread"
              className="p-1 text-slate-400 hover:text-rose-400 rounded hover:bg-slate-800"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-64 shrink-0 border-r border-[#222D3D] flex flex-col h-full bg-[#080B12]/60">
      {/* Header with "+ New Chat" button */}
      <div className="px-4 py-4 border-b border-[#222D3D] flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-200">Conversations</span>
        <div className="flex items-center gap-1.5">
          <button
            id="chat-new-session-btn"
            onClick={onCreate}
            title="New Chat"
            className="
              flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300
              bg-blue-900/20 hover:bg-blue-900/40 border border-blue-800/30
              px-2.5 py-1.5 rounded-lg transition-all duration-150
              focus:outline-none focus:ring-1 focus:ring-blue-600
            "
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            New Chat
          </button>
          {/* FE Gap 274: hide this panel to reclaim width for the message area. */}
          {onHide && (
            <button
              type="button"
              onClick={onHide}
              title="Hide conversation list"
              aria-label="Hide conversation list"
              className="text-slate-500 hover:text-slate-200 p-1.5 rounded-lg hover:bg-[#1E293B]/50 transition-colors"
            >
              <PanelLeftClose className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Search Input Bar (Gap 149) */}
      <div className="px-3 py-2 border-b border-[#222D3D]/60">
        <div className="relative flex items-center">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search threads..."
            className="w-full bg-[#0F172A] border border-[#222D3D] text-xs text-slate-200 placeholder:text-slate-500 pl-8 pr-2.5 py-1.5 rounded-lg outline-none focus:border-blue-500/50"
          />
        </div>
      </div>

      {/* Thread List — three states: loading, empty, populated (grouped by day) */}
      <div className="flex-1 overflow-y-auto py-2 space-y-0.5 px-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 text-slate-500 animate-spin" />
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="text-center py-8 text-xs text-slate-500 px-4">
            {searchQuery ? "No matching conversations." : "No conversations yet. Click \"New Chat\" to start."}
          </div>
        ) : (
          groupSessionsByDay(filteredSessions).map((group, index) => (
            <div key={`${group.label}-${index}`} data-testid="chat-session-group" className="space-y-0.5">
              <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                {group.label}
              </p>
              {group.sessions.map(renderSession)}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
