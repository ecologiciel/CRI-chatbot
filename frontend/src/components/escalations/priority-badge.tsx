"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { PRIORITY_CONFIG } from "@/types/escalation";
import type { EscalationPriority } from "@/types/escalation";

interface PriorityBadgeProps {
  priority: EscalationPriority;
  size?: "sm" | "default";
}

export function PriorityBadge({ priority, size = "default" }: PriorityBadgeProps) {
  const config = PRIORITY_CONFIG[priority];

  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 font-medium",
        config.className,
        size === "sm" && "text-[10px] px-1.5 py-0 h-5",
      )}
    >
      <span
        className={cn(
          "shrink-0 rounded-full",
          config.dotClassName,
          size === "sm" ? "h-1.5 w-1.5" : "h-2 w-2",
        )}
      />
      {config.label}
    </Badge>
  );
}
