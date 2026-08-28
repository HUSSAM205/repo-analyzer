"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ChatInput({
  onSend,
  onStop,
  disabled,
  isStreaming,
}: {
  onSend: (content: string) => void;
  onStop?: () => void;
  disabled: boolean;
  isStreaming?: boolean;
}) {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <motion.form
      onSubmit={handleSubmit}
      className="glass m-2 flex items-end gap-2 rounded-lg p-2"
      initial={false}
    >
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
          }
        }}
        rows={1}
        placeholder="Ask about this repo..."
        disabled={disabled}
        className="max-h-32 flex-1 resize-none rounded-sm bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:elevated-ring"
      />
      {isStreaming ? (
        // Same slot as the send button (ChatGPT/Claude's own convention) --
        // an AbortController-driven stop, not just a UI-side "give up
        // waiting": see chat-panel.tsx's handleStop for what it actually
        // tears down (the fetch stream, and the backend's SSE generator via
        // CancelledError once the connection drops).
        <Button type="button" size="icon" variant="outline" onClick={onStop} aria-label="Stop generating">
          <Square className="h-3.5 w-3.5 fill-current" />
        </Button>
      ) : (
        <Button type="submit" size="icon" disabled={disabled || !value.trim()} aria-label="Send message">
          <ArrowUp className="h-4 w-4" />
        </Button>
      )}
    </motion.form>
  );
}
