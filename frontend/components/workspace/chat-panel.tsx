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

const QUICK_PROMPTS = ["Explain repo architecture", "Find security vulnerabilities", "List API routes"];

export function ChatPanel({
  repoId,
  onCitationClick,
}: {
  repoId: string;
  onCitationClick?: (path: string) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const scrollViewportRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  function scrollToBottom(behavior: ScrollBehavior) {
    bottomRef.current?.scrollIntoView({ behavior });
  }

  // Auto-follow should turn off only when the user actually scrolls away
  // themselves -- never as a side effect of the app's own scroll-to-bottom
  // calls (the auto-follow effect below, and the "jump to bottom" button).
  // A native "scroll" event can't distinguish the two: it fires identically
  // whether scrollTop changed because of a user's wheel/touch gesture or
  // because `scrollIntoView` moved it programmatically, including at every
  // intermediate frame of a "smooth" scroll's animation. An earlier version
  // of this guarded against that with a timing heuristic (a ref flag armed
  // before each programmatic scroll, cleared a fixed delay afterward) --
  // but real streaming chunks arrive faster than that delay, so the guard
  // stayed continuously re-armed for the whole duration of a live stream
  // and a genuine user scroll-up got ignored until the stream paused.
  //
  // Fixed properly here: only ever evaluate "has the user scrolled away
  // from the bottom" from listeners on genuine user-input event types --
  // "wheel" (mouse/trackpad) and "touchstart"/"touchmove" (touch drag).
  // `scrollIntoView` never dispatches any of these, so there is no event
  // for a programmatic scroll to be mistaken for, at any point in its
  // animation, with no timing window to guess at. The generic "scroll"
  // event is not listened to at all for this purpose.
  useEffect(() => {
    const el = scrollViewportRef.current;
    if (!el) return;

    function evaluateUserScrollPosition() {
      if (!el) return;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      setAutoScroll(distanceFromBottom < 80);
    }

    el.addEventListener("wheel", evaluateUserScrollPosition, { passive: true });
    el.addEventListener("touchstart", evaluateUserScrollPosition, { passive: true });
    el.addEventListener("touchmove", evaluateUserScrollPosition, { passive: true });
    return () => {
      el.removeEventListener("wheel", evaluateUserScrollPosition);
      el.removeEventListener("touchstart", evaluateUserScrollPosition);
      el.removeEventListener("touchmove", evaluateUserScrollPosition);
    };
  }, []);

  async function refetchMessages(conversationId: string) {
    const res = await apiFetch(`/api/conversations/${conversationId}/messages`, { cache: "no-store" });
    if (res.ok) {
      setMessages((await res.json()) as ChatMessageType[]);
    }
  }

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/repos/${repoId}/conversations`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load conversations");
        return res.json() as Promise<Conversation[]>;
      })
      .then((data) => {
        if (cancelled) return;
        setConversations(data);
        if (data.length > 0) setActiveId(data[0].id);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load conversations. Please refresh the page.");
      });
    return () => {
      cancelled = true;
    };
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

  async function handleCreate() {
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New conversation" }),
      });
      if (!res.ok) {
        setError("Could not start a new conversation. Please try again.");
        return;
      }
      const conversation = (await res.json()) as Conversation;
      setConversations((prev) => [conversation, ...prev]);
      setActiveId(conversation.id);
    } catch {
      setError("Could not start a new conversation. Please try again.");
    }
  }

  async function handleSend(content: string) {
    if (!activeId) return;
    setError(null);
    setFailedMessage(null);
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
        setFailedMessage(content);
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
            setFailedMessage(content);
            setStatusText(null);
          }
        }
      }
    } catch {
      setError("Connection lost while streaming the response.");
      setFailedMessage(content);
    } finally {
      setIsStreaming(false);
    }
  }

  function handleRetry() {
    if (!failedMessage) return;
    handleSend(failedMessage);
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
        <ScrollArea className="h-full p-3" viewportRef={scrollViewportRef}>
          <div className="space-y-3">
            {messages.length === 0 && !isStreaming && (
              <div className="space-y-3 p-4 text-center">
                <p className="text-sm text-muted-foreground">
                  {activeId ? "No messages yet. Ask something below." : "Start a conversation to chat about this repo."}
                </p>
                {activeId && (
                  <div className="flex flex-wrap justify-center gap-2">
                    {QUICK_PROMPTS.map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        onClick={() => handleSend(prompt)}
                        className="rounded-full border border-zinc-800/60 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-700/50 hover:text-zinc-100"
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {messages.map((m) => (
              <ChatMessage key={m.id} role={m.role} content={m.content} onCitationClick={onCitationClick} />
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
                {streamingText && (
                  <div className="flex items-end gap-1">
                    <ChatMessage role="assistant" content={streamingText} onCitationClick={onCitationClick} />
                    <span
                      data-testid="streaming-cursor"
                      className="mb-2 h-3 w-1.5 shrink-0 animate-pulse-subtle rounded-sm bg-primary"
                    />
                  </div>
                )}
              </div>
            )}
            {error && (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <p>{error}</p>
                {failedMessage && (
                  <Button size="sm" variant="outline" onClick={handleRetry} disabled={isStreaming}>
                    Retry
                  </Button>
                )}
              </div>
            )}
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
