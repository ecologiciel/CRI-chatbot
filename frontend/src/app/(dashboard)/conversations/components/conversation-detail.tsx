"use client";

import { useEffect, useRef } from "react";
import { Phone, Bot, User, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./message-bubble";
import { mockConversations, mockMessages } from "@/lib/mock-data";
import type { ConversationStatus } from "@/types/conversation";

const statusLabels: Record<ConversationStatus, { label: string; className: string }> = {
  active: {
    label: "Active",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  waiting: {
    label: "En attente",
    className: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  escalated: {
    label: "Escaladée",
    className: "bg-destructive/10 text-destructive border-0",
  },
  closed: {
    label: "Terminée",
    className: "bg-muted text-muted-foreground border-0",
  },
  archived: {
    label: "Archivée",
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
  const conversation = mockConversations.find((c) => c.id === conversationId);
  const messages = mockMessages[conversationId] ?? [];

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
  }, [conversationId]);

  if (!conversation) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <p>Conversation introuvable</p>
      </div>
    );
  }

  const displayName = conversation.contact_name ?? conversation.contact_phone;
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
            <Phone className="h-3 w-3" />
            <span className="font-mono">
              {maskPhone(conversation.contact_phone)}
            </span>
          </div>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1 px-4 py-3">
        <div className="space-y-1">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>
      </ScrollArea>

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
