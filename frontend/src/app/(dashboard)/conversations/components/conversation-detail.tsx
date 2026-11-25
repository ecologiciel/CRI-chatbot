"use client";

import { useEffect, useRef, useState } from "react";
import { Phone, Bot, User, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./message-bubble";
import { useConversation, useConversationMessages } from "@/hooks/use-conversations";
import type { ConversationRecord } from "@/types/conversation";

const statusLabels: Record<ConversationRecord["status"], { label: string; className: string }> = {
  active: {
    label: "Active",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  human_handled: {
    label: "Prise en charge",
    className: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  escalated: {
    label: "Escaladée",
    className: "bg-destructive/10 text-destructive border-0",
  },
  ended: {
    label: "Terminée",
    className: "bg-muted text-muted-foreground border-0",
  },
};

function maskPhone(phone: string): string {
  // +212 6XX XXX 567 → +212 6•• ••• 567
  if (phone.length > 8) {
    return phone.slice(0, 8) + "•••• " + phone.slice(-3);
  }
  return phone;
}

interface ConversationDetailProps {
  conversationId: string;
}

export function ConversationDetail({ conversationId }: ConversationDetailProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(1);
  const { data: conversation, isLoading, isError, refetch } = useConversation(conversationId);
  const messagesQuery = useConversationMessages(conversationId, page);

  useEffect(() => setPage(1), [conversationId]);

  useEffect(() => {
    // Auto-scroll to bottom
    if (scrollRef.current) {
      const scrollArea = scrollRef.current.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (scrollArea) {
        scrollArea.scrollTop = scrollArea.scrollHeight;
      }
    }
  }, [conversationId, messagesQuery.data]);

  if (isLoading) return <div className="p-6 text-sm">Chargement…</div>;
  if (isError) return <div className="p-6 text-sm">Impossible de charger la conversation. <Button variant="outline" size="sm" onClick={() => refetch()}>Réessayer</Button></div>;

  if (!conversation) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <p>Conversation introuvable</p>
      </div>
    );
  }

  const displayName = conversation.contact_name ?? conversation.contact_phone ?? "Visiteur web";
  const status = statusLabels[conversation.status];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3 shrink-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-sm font-semibold font-heading truncate">
              {displayName}
            </h2>
            <Badge className={cn("text-xs", status.className)}>
              {status.label}
            </Badge>
            <Badge
              variant="outline"
              className="text-xs gap-1"
            >
              {conversation.agent_type === "internal" ? (
                <User className="h-3 w-3" />
              ) : (
                <Bot className="h-3 w-3" />
              )}
              {conversation.agent_type === "internal" ? "Interne" : "Public"}
            </Badge>
          </div>
          <div className="flex items-center gap-1.5 mt-0.5 text-xs text-muted-foreground">
            {conversation.contact_phone ? <><Phone className="h-3 w-3" /><span className="font-mono">{maskPhone(conversation.contact_phone)}</span></> : <span>Canal web</span>}
          </div>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1 px-4 py-3">
        <div className="space-y-1">
          {messagesQuery.isLoading && <p className="text-sm text-muted-foreground">Chargement des messages…</p>}
          {messagesQuery.isError && <p className="text-sm text-destructive">Impossible de charger les messages. <Button variant="outline" size="sm" onClick={() => messagesQuery.refetch()}>Réessayer</Button></p>}
          {messagesQuery.data?.items.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>
      </ScrollArea>

      {messagesQuery.data && messagesQuery.data.total > messagesQuery.data.page_size && (
        <div className="flex items-center justify-between border-t p-2 text-xs">
          <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Précédent</Button>
          <span>Page {page}</span>
          <Button variant="ghost" size="sm" disabled={page * messagesQuery.data.page_size >= messagesQuery.data.total} onClick={() => setPage(page + 1)}>Suivant</Button>
        </div>
      )}

      {/* Supervision banner */}
      <div className="shrink-0 border-t border-border px-4 py-3">
        <div className="flex items-center gap-2 rounded-lg bg-[hsl(var(--info))]/10 px-3 py-2">
          <Info className="h-4 w-4 text-[hsl(var(--info))] shrink-0" />
          <p className="text-xs text-[hsl(var(--info))]">
            Mode supervision — lecture seule
          </p>
        </div>
      </div>
    </div>
  );
}
