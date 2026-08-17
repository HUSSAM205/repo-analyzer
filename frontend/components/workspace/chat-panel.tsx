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
  // Guards handleScroll against the app's own scroll-to-bottom calls. A
  // `scrollIntoView({ behavior: "smooth" })` animates over several frames,
  // firing native "scroll" events along the way -- and handleScroll can't
  // tell those apart from the user grabbing the scrollbar. Without this,
  // an in-flight auto-follow animation (or the "jump to bottom" button's own
  // scroll) can be measured mid-flight, read as "far from bottom", and
  // permanently kill auto-follow with no user action at all. Set to true
  // right before every programmatic scroll and cleared a bit after the
  // *last* one settles (see scrollToBottom below); handleScroll no-ops
  // while it's true.
  const programmaticScrollRef = useRef(false);
  const clearProgrammaticScrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function scrollToBottom(behavior: ScrollBehavior) {
    programmaticScrollRef.current = true;
    if (clearProgrammaticScrollTimeoutRef.current) {
      clearTimeout(clearProgrammaticScrollTimeoutRef.current);
    }
    bottomRef.current?.scrollIntoView({ behavior });
    // 600ms comfortably outlasts a "smooth" scrollIntoView animation over a
    // chat-panel-sized distance in evergreen browsers. Not using the
    // "scrollend" event because it isn't universally supported yet; a
    // generous fixed delay, re-armed on every call, is simpler and safe
    // here since the only cost of guarding a little too long is briefly
    // ignoring a real user scroll during active streaming.
    clearProgrammaticScrollTimeoutRef.current = setTimeout(() => {
      programmaticScrollRef.current = false;
    }, 600);
  }

  async function refetchMessages(conversationId: string) {
    const res = await apiFetch(`/api/conversations/${conversationId}/messages`, { cache: "no-store" });
    if (res.ok) {
      setMessages((await res.json()) as ChatMessageType[]);
    }
  }

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
    refetchMessages(activeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  useEffect(() => {
    if (autoScroll) {
      scrollToBottom("smooth");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, streamingText, autoScroll]);

  function handleScroll() {
    if (programmaticScrollRef.current) return;
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
            if (finalText.trim()) {
              setMessages((prev) => [
                ...prev,
                {
                  id: (event.data as { message_id: string }).message_id,
                  role: "assistant",
                  content: finalText,
                  created_at: new Date().toISOString(),
                },
              ]);
            } else {
              // The agent's give-up path (max tool-call iterations with no
              // textual answer, see backend/app/core/agent.py) emits "done"
              // with no preceding "token" events at all -- finalText is
              // empty here even though the backend persisted real
              // explanatory text for this turn. The "done" payload only
              // carries {message_id}, not the text itself, so it can't be
              // recovered from the stream. Refetch the conversation's
              // message list instead, which reflects whatever was actually
              // persisted, rather than rendering a blank assistant bubble.
              await refetchMessages(activeId);
            }
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
              scrollToBottom("smooth");
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
