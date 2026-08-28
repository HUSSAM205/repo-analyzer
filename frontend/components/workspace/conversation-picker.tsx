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
      <Button variant="outline" size="icon" onClick={onCreate} aria-label="New conversation">
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  );
}
