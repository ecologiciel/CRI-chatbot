"use client";

import { Badge } from "@/components/ui/badge";
import { TRIGGER_LABELS } from "@/types/escalation";
import type { EscalationTrigger } from "@/types/escalation";

interface TriggerBadgeProps {
  trigger: EscalationTrigger;
}

export function TriggerBadge({ trigger }: TriggerBadgeProps) {
  return (
    <Badge variant="outline" className="text-xs font-normal">
      {TRIGGER_LABELS[trigger]}
    </Badge>
  );
}
