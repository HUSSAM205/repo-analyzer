"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowDown, Search } from "lucide-react";
import { ConversationPicker } from "./conversation-picker";
import { ChatMessage } from "./chat-message";
import { ChatInput } from "./chat-input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { parseSSEChunk } from "@/lib/sse";
import { apiFetch } from "@/lib/api-client";
import type { ChatMessage as ChatMessageType, Conversation } from "@/lib/types";

export function ChatPanel({ repoId }: { repoId: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const scrollViewportRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamingText, autoScroll]);

  function handleScroll() {
    const el = scrollViewportRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAutoScroll(distanceFromBottom < 80);
  }

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

  async function handleSend(content: string) {
    if (!activeId) return;
    setError(null);
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, role: "user", content, created_at: new Date().toISOString() },
    ]);
    setIsStreaming(true);
    setStreamingText("");
    setStatusText(null);
    setAutoScroll(true);

    try {
      const res = await apiFetch(`/api/conversations/${activeId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok || !res.body) {
        setError("Could not send that message. Please try again.");
        setIsStreaming(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, remainder } = parseSSEChunk(buffer);
        buffer = remainder;

        for (const event of events) {
          if (event.type === "token") {
            const text = (event.data as { text?: string }).text ?? "";
            finalText += text;
            setStreamingText((prev) => prev + text);
          } else if (event.type === "tool_call") {
            setStatusText("Searching code...");
          } else if (event.type === "tool_result") {
            setStatusText(null);
          } else if (event.type === "done") {
            setMessages((prev) => [
              ...prev,
              {
                id: (event.data as { message_id: string }).message_id,
                role: "assistant",
                content: finalText,
                created_at: new Date().toISOString(),
              },
            ]);
            setStreamingText("");
            setStatusText(null);
          } else if (event.type === "error") {
            setError((event.data as { message?: string }).message ?? "The assistant hit an error.");
            setStatusText(null);
          }
        }
      }
    } catch {
      setError("Connection lost while streaming the response.");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <ConversationPicker
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={handleCreate}
      />
      <div className="relative min-h-0 flex-1">
        <ScrollArea className="h-full p-3" viewportRef={scrollViewportRef} onScroll={handleScroll}>
          <div className="space-y-3">
            {messages.length === 0 && !isStreaming && (
              <p className="p-4 text-center text-sm text-muted-foreground">
                {activeId ? "No messages yet. Ask something below." : "Start a conversation to chat about this repo."}
              </p>
            )}
            {messages.map((m) => (
              <ChatMessage key={m.id} role={m.role} content={m.content} />
            ))}
            {isStreaming && (
              <div className="space-y-2">
                {statusText && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <motion.span
                      className="flex h-4 w-4 items-center justify-center"
                      animate={{ opacity: [1, 0.4, 1] }}
                      transition={{ duration: 1.2, repeat: Infinity }}
                    >
                      <Search className="h-3.5 w-3.5" />
                    </motion.span>
                    {statusText}
                  </div>
                )}
                {streamingText && <ChatMessage role="assistant" content={streamingText} />}
              </div>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>
        {!autoScroll && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setAutoScroll(true);
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
            }}
            className="absolute bottom-3 left-1/2 -translate-x-1/2"
          >
            <ArrowDown className="mr-1 h-3.5 w-3.5" /> Jump to bottom
          </Button>
        )}
      </div>
      <ChatInput onSend={handleSend} disabled={!activeId || isStreaming} />
    </div>
  );
}
