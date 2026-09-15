"use client";

import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { Conversation } from "@/lib/types";

export function ConversationPicker({
  conversations,
  activeId,
  onSelect,
  onCreate,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-border p-2">
      <select
        value={activeId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        aria-label="Select conversation"
        className="flex-1 rounded-md border border-input bg-transparent px-2 py-1.5 text-sm"
      >
        {conversations.length === 0 && <option value="">No conversations yet</option>}
        {conversations.map((c) => (
          <option key={c.id} value={c.id}>
            {c.title}
          </option>
        ))}
      </select>
      {/* size="icon" is the shared 36x36 icon-button size used across the
          app (kept as-is on desktop/pointer devices) -- max-md: bumps just
          this one, mobile-only, to the 44x44 touch-target minimum, since
          it's the button a stalled/rate-limited chat's advisory note (see
          below the chat input) points people at. */}
      <Button
        variant="outline"
        size="icon"
        onClick={onCreate}
        aria-label="New conversation"
        className="max-md:h-11 max-md:w-11"
      >
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  );
}
