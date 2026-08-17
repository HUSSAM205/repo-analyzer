"use client";

import { useEffect, useState } from "react";
import { ConversationPicker } from "./conversation-picker";
import { ChatMessage } from "./chat-message";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api-client";
import type { ChatMessage as ChatMessageType, Conversation } from "@/lib/types";

export function ChatPanel({ repoId }: { repoId: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageType[]>([]);

  useEffect(() => {
    apiFetch(`/api/repos/${repoId}/conversations`, { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<Conversation[]>) : []))
      .then((data) => {
        setConversations(data);
        if (data.length > 0) setActiveId(data[0].id);
      });
  }, [repoId]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    apiFetch(`/api/conversations/${activeId}/messages`, { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<ChatMessageType[]>) : []))
      .then(setMessages);
  }, [activeId]);

  async function handleCreate() {
    const res = await apiFetch(`/api/repos/${repoId}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "New conversation" }),
    });
    if (!res.ok) return;
    const conversation = (await res.json()) as Conversation;
    setConversations((prev) => [conversation, ...prev]);
    setActiveId(conversation.id);
  }

  return (
    <div className="flex h-full flex-col">
      <ConversationPicker
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={handleCreate}
      />
      <ScrollArea className="flex-1 p-3">
        <div className="space-y-3">
          {messages.length === 0 && (
            <p className="p-4 text-center text-sm text-muted-foreground">
              {activeId ? "No messages yet. Ask something below." : "Start a conversation to chat about this repo."}
            </p>
          )}
          {messages.map((m) => (
            <ChatMessage key={m.id} role={m.role} content={m.content} />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
