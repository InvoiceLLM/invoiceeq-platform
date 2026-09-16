"use client";

// FE Feature 22 Task 22.6: the chat screen moved, unchanged, to
// components/chat/ChatScreen.tsx so /ask renders the same screen. /chat keeps its
// "Semantic Chat" title and takes no deep link; with the four surfaces on it
// redirects to /ask (lib/navigation.ts), and the classic layout still renders it.

import ChatScreen from "@/components/chat/ChatScreen";

export default function ChatPage() {
  return <ChatScreen />;
}
