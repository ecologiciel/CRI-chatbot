"use client";

import { cn } from "@/lib/utils";
import type { Message } from "@/types/conversation";

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const { direction, type, content, timestamp } = message;

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

  const isInbound = direction === "inbound";

  return (
    <div
      className={cn(
        "flex w-full mb-3",
        isInbound ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-lg px-3.5 py-2.5",
          isInbound
            ? "bg-primary/10 rounded-te-none"
            : "bg-card border border-border rounded-ts-none"
        )}
      >
        <p className="text-sm whitespace-pre-wrap break-words">{content}</p>
        <p
          className={cn(
            "text-[10px] mt-1.5",
            isInbound ? "text-primary/60 text-end" : "text-muted-foreground text-end"
          )}
        >
          {formatTime(timestamp)}
        </p>
      </div>
    </div>
  );
}
