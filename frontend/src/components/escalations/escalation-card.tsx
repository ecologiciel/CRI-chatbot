"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { PriorityBadge } from "./priority-badge";
import { TriggerBadge } from "./trigger-badge";
import type { Escalation } from "@/types/escalation";

function formatRelativeTime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remainMins = mins % 60;
  if (hours < 24) return `${hours}h ${remainMins}m`;
  const days = Math.floor(hours / 24);
  return `${days}j ${hours % 24}h`;
}

interface EscalationCardProps {
  escalation: Escalation;
  isActive: boolean;
  onSelect: () => void;
}

export function EscalationCard({
  escalation,
  isActive,
  onSelect,
}: EscalationCardProps) {
  const [elapsed, setElapsed] = useState(() =>
    Math.floor(
      (Date.now() - new Date(escalation.created_at).getTime()) / 1000,
    ),
  );

  // Live counter — ticks every second for pending/assigned escalations
  useEffect(() => {
    if (
      escalation.status === "resolved" ||
      escalation.status === "closed"
    ) {
      return;
    }

    const interval = setInterval(() => {
      setElapsed(
        Math.floor(
          (Date.now() - new Date(escalation.created_at).getTime()) / 1000,
        ),
      );
    }, 1000);

    return () => clearInterval(interval);
  }, [escalation.created_at, escalation.status]);

  const isPending = escalation.status === "pending";
  const displayName =
    escalation.contact_name ?? escalation.contact_phone ?? "Inconnu";
  const preview = escalation.user_message ?? "Aucun message";

  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full text-start px-4 py-3 border-b border-border transition-colors hover:bg-muted/50",
        isActive && "bg-primary/5 border-s-[3px] border-s-primary",
      )}
    >
      <div className="flex items-start gap-3">
        {/* Priority dot */}
        <div className="pt-1.5 shrink-0">
          <span
            className={cn(
              "block h-2.5 w-2.5 rounded-full",
              escalation.priority === "high" && "bg-[#B5544B]",
              escalation.priority === "medium" && "bg-[#C4944B]",
              escalation.priority === "low" && "bg-[#5B7A8B]",
              isPending && "animate-pulse",
            )}
          />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-sm font-medium truncate">{displayName}</span>
            <span className="text-[10px] text-muted-foreground shrink-0 font-mono">
              {formatRelativeTime(elapsed)}
            </span>
          </div>

          <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
            {preview}
          </p>

          <div className="flex items-center gap-1.5 flex-wrap">
            <PriorityBadge priority={escalation.priority} size="sm" />
            <TriggerBadge trigger={escalation.trigger_type} />
          </div>
        </div>
      </div>
    </button>
  );
}
