/**
 * FE Feature 22 Task 22.6 — Ask.
 *
 *   - SessionRail groups conversations under day headers WITHOUT re-sorting, and
 *     badges a private (`clearance: "exec"`) session. It renders exactly what the
 *     server sent — no role filtering happens here.
 *   - /ask deep links from Today (22.5): `session` opens that conversation once
 *     the list has loaded, `seed` pre-fills the composer (never sends), and
 *     `attach=1` focuses the attach control — opening a conversation first when
 *     none is selected.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import type { ChatSession } from "@/types/chat";

const nav = vi.hoisted(() => ({ params: new URLSearchParams() }));
const chat = vi.hoisted(() => ({ state: {} as Record<string, unknown> }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/hooks/useChatSession", () => ({ useChatSession: () => chat.state }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ canTrain: false, role: "Admin", loading: false }) }));

import AskPage from "@/app/ask/page";
import ChatWindow from "@/components/chat/ChatWindow";
import SessionRail, { groupSessionsByDay, sessionDayLabel } from "@/components/chat/SessionRail";

const NOW = new Date();

function iso(daysAgo: number, hour = 10): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
}

function session(id: string, daysAgo: number, extra: Partial<ChatSession> = {}): ChatSession {
  return {
    id,
    tenant_id: "t",
    user_id: "u",
    title: `Conversation ${id}`,
    message_count: 0,
    created_at: iso(daysAgo),
    updated_at: "",
    ...extra,
  };
}

function chatState(overrides: Record<string, unknown> = {}) {
  return {
    sessions: [session("s1", 0)],
    activeSessionId: null,
    messages: [],
    isLoadingSessions: false,
    isLoadingMessages: false,
    isSending: false,
    error: null,
    createSession: vi.fn(),
    selectSession: vi.fn(),
    sendMessage: vi.fn(),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
    attachment: null,
    uploadAttachment: vi.fn(),
    removeAttachment: vi.fn(),
    cancelAttachment: vi.fn(),
    attachmentCount: 0,
    confirmMatches: vi.fn(),
    updatedInsightMessageIds: [],
    ...overrides,
  };
}

beforeEach(() => {
  nav.params = new URLSearchParams();
  chat.state = chatState();
});

describe("SessionRail (22.6)", () => {
  it("labels days as Today, Yesterday, then the date", () => {
    expect(sessionDayLabel(iso(0), NOW)).toBe("Today");
    expect(sessionDayLabel(iso(1), NOW)).toBe("Yesterday");
    const fourDaysAgo = new Date();
    fourDaysAgo.setDate(fourDaysAgo.getDate() - 4);
    expect(sessionDayLabel(iso(4), NOW)).toBe(fourDaysAgo.toLocaleDateString("en-IN", { day: "numeric", month: "short" }));
  });

  it("groups consecutive sessions without re-sorting the server's order", () => {
    const groups = groupSessionsByDay([session("a", 0), session("b", 1), session("c", 0)], NOW);
    expect(groups.map((g) => [g.label, g.sessions.map((s) => s.id)])).toEqual([
      ["Today", ["a"]],
      ["Yesterday", ["b"]],
      ["Today", ["c"]],
    ]);
  });

  it("renders every session it is sent, under day headers, badging only exec ones", () => {
    const sessions = [session("a", 0, { clearance: "exec" }), session("b", 0, { clearance: "ops" }), session("c", 1)];
    render(
      <SessionRail
        sessions={sessions}
        activeSessionId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />
    );
    const groups = screen.getAllByTestId("chat-session-group");
    expect(groups.map((g) => g.querySelector("p")?.textContent)).toEqual(["Today", "Yesterday"]);
    expect(document.querySelectorAll("[id^='chat-session-']")).toHaveLength(3);
    expect(screen.getByTestId("chat-session-private-a")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-session-private-b")).toBeNull();
    expect(screen.queryByTestId("chat-session-private-c")).toBeNull();
  });
});

describe("/ask deep links (22.6)", () => {
  it("opens the session from ?session= once the list has loaded — not before", () => {
    nav.params = new URLSearchParams("session=sess-42&seed=Why%3F");
    chat.state = chatState({ isLoadingSessions: true });
    const { rerender } = render(<AskPage />);
    expect((chat.state.selectSession as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();

    const select = vi.fn();
    chat.state = chatState({ isLoadingSessions: false, selectSession: select });
    rerender(<AskPage />);
    rerender(<AskPage />);
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenCalledWith("sess-42");
  });

  it("?attach=1 with no conversation selected opens a new one", () => {
    nav.params = new URLSearchParams("attach=1");
    render(<AskPage />);
    expect(chat.state.createSession).toHaveBeenCalledTimes(1);
    expect(chat.state.selectSession).not.toHaveBeenCalled();
  });

  it("?invoice= (the old review URL) opens a conversation and pins the review card (22.12)", async () => {
    nav.params = new URLSearchParams("invoice=inv-9");
    chat.state = chatState({ activeSessionId: null });
    const { rerender } = render(<AskPage />);
    expect(chat.state.createSession).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("chat-top-card")).toBeNull();

    chat.state = chatState({ activeSessionId: "s1" });
    await act(async () => {
      rerender(<AskPage />);
    });
    expect(screen.getByTestId("chat-top-card")).toBeInTheDocument();
  });

  it("a plain /ask does nothing on arrival", () => {
    render(<AskPage />);
    expect(chat.state.createSession).not.toHaveBeenCalled();
    expect(chat.state.selectSession).not.toHaveBeenCalled();
  });
});

describe("ChatWindow arrival behaviour (22.6)", () => {
  const base = {
    sessions: [session("sess-42", 0)],
    messages: [],
    isLoadingSessions: false,
    isLoadingMessages: false,
    isSending: false,
    error: null,
    onCreateSession: vi.fn(),
    onSelectSession: vi.fn(),
    onSendMessage: vi.fn(),
    onRenameSession: vi.fn(),
    onDeleteSession: vi.fn(),
    onAttach: vi.fn(),
  };

  it("pre-fills the composer with the seed once a conversation is open, and never sends it", async () => {
    const { rerender } = render(<ChatWindow {...base} activeSessionId={null} initialSeed="Why did Rajesh over-bill PO-1041?" />);
    await act(async () => {
      rerender(<ChatWindow {...base} activeSessionId="sess-42" initialSeed="Why did Rajesh over-bill PO-1041?" />);
    });
    const textarea = document.getElementById("chat-input-textarea") as HTMLTextAreaElement;
    expect(textarea.value).toBe("Why did Rajesh over-bill PO-1041?");
    expect(base.onSendMessage).not.toHaveBeenCalled();

    // The user clears it, the conversation closes (e.g. deleted), and another opens:
    // the arrival seed must not come back.
    fireEvent.change(textarea, { target: { value: "" } });
    await act(async () => {
      rerender(<ChatWindow {...base} activeSessionId={null} initialSeed="Why did Rajesh over-bill PO-1041?" />);
    });
    await act(async () => {
      rerender(<ChatWindow {...base} activeSessionId="sess-43" initialSeed="Why did Rajesh over-bill PO-1041?" />);
    });
    expect((document.getElementById("chat-input-textarea") as HTMLTextAreaElement).value).toBe("");
  });

  it("focuses the attach control once it is usable", async () => {
    const { rerender } = render(<ChatWindow {...base} activeSessionId={null} focusAttach />);
    expect(document.activeElement?.id).not.toBe("chat-attach-btn");
    await act(async () => {
      rerender(<ChatWindow {...base} activeSessionId="sess-42" focusAttach />);
    });
    expect(document.activeElement?.id).toBe("chat-attach-btn");
    expect(within(document.body).getByRole("button", { name: "Attach a document" })).toHaveFocus();
  });
});
