"use client";

import { useEffect, useRef } from "react";
import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { EscalationMessage, Escalation } from "@/types/escalation";

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resolveSenderType(
  message: EscalationMessage,
  escalation: Escalation,
): "user" | "bot" | "agent" {
  if (message.sender_type) return message.sender_type;
  if (message.direction === "inbound") return "user";
  // Outbound: determine if bot or agent based on assignment timestamp
  if (
    escalation.assigned_at &&
    new Date(message.timestamp) >= new Date(escalation.assigned_at)
  ) {
    return "agent";
  }
  return "bot";
}

// ---------------------------------------------------------------------------
// Individual bubble
// ---------------------------------------------------------------------------

interface BubbleProps {
  message: EscalationMessage;
  senderType: "user" | "bot" | "agent";
}

function MessageBubble({ message, senderType }: BubbleProps) {
  const { type, content, timestamp } = message;

  // System messages
  if (type === "system") {
    return (
      <div className="flex justify-center py-2">
        <p className="text-xs text-muted-foreground italic bg-muted/50 rounded-full px-3 py-1 max-w-[80%] text-center">
          {content}
        </p>
      </div>
    );
  }

  const isUser = senderType === "user";
  const isAgent = senderType === "agent";

  return (
    <div
      className={cn(
        "flex w-full mb-3",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-lg px-3.5 py-2.5",
          isUser && "bg-primary/10 rounded-te-none",
          senderType === "bot" &&
            "bg-card border border-border rounded-ts-none",
          isAgent &&
            "bg-[hsl(var(--olive))]/5 border border-[hsl(var(--olive))]/20 rounded-ts-none",
        )}
      >
        {/* Sender indicator for non-user messages */}
        {!isUser && (
          <div className="flex items-center gap-1.5 mb-1">
            {isAgent ? (
              <Badge
                variant="outline"
                className="text-[9px] px-1 py-0 h-4 border-[hsl(var(--olive))]/30 text-[hsl(var(--olive))]"
              >
                <User className="h-2.5 w-2.5 me-0.5" strokeWidth={2} />
                Agent
              </Badge>
            ) : (
              <Bot
                className="h-3.5 w-3.5 text-muted-foreground"
                strokeWidth={1.75}
              />
            )}
          </div>
        )}

        <p className="text-sm whitespace-pre-wrap break-words">{content}</p>
        <p
          className={cn(
            "text-[10px] mt-1.5 text-end",
            isUser ? "text-primary/60" : "text-muted-foreground",
          )}
        >
          {formatTime(timestamp)}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bubbles container
// ---------------------------------------------------------------------------

interface ConversationBubblesProps {
  messages: EscalationMessage[];
  escalation: Escalation;
}

export function ConversationBubbles({
  messages,
  escalation,
}: ConversationBubblesProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      const viewport = scrollRef.current.querySelector(
        "[data-radix-scroll-area-viewport]",
      );
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
      }
    }
  }, [messages.length]);

  return (
    <ScrollArea ref={scrollRef} className="flex-1 px-4 py-3">
      <div className="space-y-1">
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            senderType={resolveSenderType(msg, escalation)}
          />
        ))}
      </div>
    </ScrollArea>
  );
}
