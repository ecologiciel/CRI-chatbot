"use client";

import { Search } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useConversations } from "@/hooks/use-conversations";
import type { ConversationRecord } from "@/types/conversation";

function getInitials(name: string | null, phone: string): string {
  if (name) {
    return name
      .split(" ")
      .map((w) => w[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();
  }
  return phone.slice(-2);
}

function getAvatarColor(name: string | null, phone: string): string {
  const str = name ?? phone;
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "bg-primary/20 text-primary",
    "bg-[hsl(var(--info))]/20 text-[hsl(var(--info))]",
    "bg-[hsl(var(--success))]/20 text-[hsl(var(--success))]",
    "bg-[hsl(var(--warning))]/20 text-[hsl(var(--warning))]",
    "bg-secondary/40 text-secondary-foreground",
    "bg-[hsl(var(--olive))]/20 text-[hsl(var(--olive))]",
  ];
  return colors[Math.abs(hash) % colors.length];
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);

  if (diffMins < 1) return "À l'instant";
  if (diffMins < 60) return `${diffMins} min`;
  if (diffHours < 24) return `${diffHours}h`;
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

const statusIndicator: Partial<Record<ConversationRecord["status"], React.ReactNode>> = {
  active: (
    <span className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--success))]" />
  ),
  escalated: (
    <span className="h-2.5 w-2.5 rounded-full bg-destructive animate-pulse" />
  ),
};

interface ConversationListProps {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function ConversationList({
  selectedId,
  onSelect,
}: ConversationListProps) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, refetch } = useConversations(page, search);

  return (
    <div className="flex flex-col h-full border-e border-border">
      {/* Search */}
      <div className="p-3 border-b border-border">
        <div className="relative">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="ps-9 h-9"
          />
        </div>
      </div>

      {/* List */}
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="p-6 text-center text-sm text-muted-foreground">Chargement…</div>
        ) : isError ? (
          <div className="p-6 text-center text-sm text-destructive">
            Impossible de charger les conversations.
            <Button variant="outline" size="sm" onClick={() => refetch()} className="mt-2">Réessayer</Button>
          </div>
        ) : !data?.items.length ? (
          <div className="p-6 text-center text-sm text-muted-foreground">
            Aucune conversation trouvée
          </div>
        ) : (
          data.items.map((conv) => (
            <ConversationItem
              key={conv.id}
              conversation={conv}
              isActive={selectedId === conv.id}
              onSelect={() => onSelect(conv.id)}
            />
          ))
        )}
      </ScrollArea>
      {data && data.total > data.page_size && (
        <div className="flex items-center justify-between border-t p-2 text-xs">
          <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Précédent</Button>
          <span>Page {page}</span>
          <Button variant="ghost" size="sm" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Suivant</Button>
        </div>
      )}
    </div>
  );
}

function ConversationItem({
  conversation,
  isActive,
  onSelect,
}: {
  conversation: ConversationRecord;
  isActive: boolean;
  onSelect: () => void;
}) {
  const displayName = conversation.contact_name ?? conversation.contact_phone ?? "Visiteur web";
  const initials = getInitials(
    conversation.contact_name,
    conversation.contact_phone ?? "web"
  );
  const avatarColor = getAvatarColor(
    conversation.contact_name,
    conversation.contact_phone ?? "web"
  );
  const indicator = statusIndicator[conversation.status];

  return (
    <button
      onClick={onSelect}
      className={cn(
        "flex w-full items-start gap-3 p-3 text-start transition-colors hover:bg-muted/50",
        isActive && "bg-primary/10 border-s-[3px] border-primary"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "h-10 w-10 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold",
          avatarColor
        )}
      >
        {initials}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium truncate">{displayName}</span>
          <span className="text-[10px] text-muted-foreground shrink-0">
            {formatRelativeTime(conversation.last_message_at)}
          </span>
        </div>
        <p className="text-xs text-muted-foreground truncate mt-0.5">
          {conversation.last_message ?? "Aucun message"}
        </p>
      </div>

      {/* Right indicators */}
      <div className="flex flex-col items-center gap-1.5 shrink-0 pt-0.5">
        {indicator}
      </div>
    </button>
  );
}
