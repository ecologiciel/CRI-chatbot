"use client";

import { Clock, AlertTriangle, UserCheck, CheckCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { EscalationStatsData } from "@/types/escalation";

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins < 60) return `${mins}m ${secs}s`;
  const hours = Math.floor(mins / 60);
  const remainMins = mins % 60;
  return `${hours}h ${remainMins}m`;
}

interface EscalationStatsBarProps {
  stats?: EscalationStatsData;
  isLoading: boolean;
}

const statItems = [
  {
    key: "pending" as const,
    label: "En attente",
    icon: AlertTriangle,
    color: "text-[#B5544B]",
    bg: "bg-[#B5544B]/10",
    getValue: (s: EscalationStatsData) => s.total_pending,
  },
  {
    key: "active" as const,
    label: "En cours",
    icon: UserCheck,
    color: "text-[#7A8B5F]",
    bg: "bg-[#7A8B5F]/10",
    getValue: (s: EscalationStatsData) => s.total_in_progress,
  },
  {
    key: "avg_wait" as const,
    label: "Attente moy.",
    icon: Clock,
    color: "text-[#C4944B]",
    bg: "bg-[#C4944B]/10",
    getValue: (s: EscalationStatsData) => formatDuration(s.avg_wait_seconds),
  },
  {
    key: "avg_resolution" as const,
    label: "Résolution moy.",
    icon: CheckCircle,
    color: "text-[#5B7A8B]",
    bg: "bg-[#5B7A8B]/10",
    getValue: (s: EscalationStatsData) =>
      formatDuration(s.avg_resolution_seconds),
  },
];

export function EscalationStatsBar({
  stats,
  isLoading,
}: EscalationStatsBarProps) {
  if (isLoading || !stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-3">
              <div className="flex items-center gap-3">
                <div className="h-9 w-9 rounded-lg bg-muted animate-pulse" />
                <div className="space-y-1.5 flex-1">
                  <div className="h-3 w-16 bg-muted animate-pulse rounded" />
                  <div className="h-5 w-10 bg-muted animate-pulse rounded" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {statItems.map((item) => {
        const Icon = item.icon;
        const value = item.getValue(stats);

        return (
          <Card key={item.key}>
            <CardContent className="p-3">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-9 w-9 items-center justify-center rounded-lg ${item.bg}`}
                >
                  <Icon className={`h-4.5 w-4.5 ${item.color}`} strokeWidth={1.75} />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{item.label}</p>
                  <p className="text-lg font-semibold font-heading">{value}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
