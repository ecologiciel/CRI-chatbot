"use client";

import { Clock, CheckCircle, XCircle, Target } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { LearningStats } from "@/types/learning";

interface LearningKPIProps {
  stats: LearningStats | undefined;
  isLoading: boolean;
}

const kpiItems = [
  {
    key: "pending" as const,
    label: "En attente",
    icon: Clock,
    color: "text-[hsl(var(--warning))] bg-[hsl(var(--warning))]/10",
  },
  {
    key: "approved" as const,
    label: "Validées",
    icon: CheckCircle,
    color: "text-[hsl(var(--success))] bg-[hsl(var(--success))]/10",
  },
  {
    key: "rejected" as const,
    label: "Rejetées",
    icon: XCircle,
    color: "text-destructive bg-destructive/10",
  },
  {
    key: "coverage" as const,
    label: "Couverture KB",
    icon: Target,
    color: "text-[hsl(var(--info))] bg-[hsl(var(--info))]/10",
  },
];

function KPICardSkeleton() {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center gap-3 mb-3">
          <div className="rounded-lg p-2 bg-muted animate-pulse h-9 w-9" />
          <div className="h-4 w-24 bg-muted animate-pulse rounded" />
        </div>
        <div className="h-8 w-16 bg-muted animate-pulse rounded" />
      </CardContent>
    </Card>
  );
}

function getValue(
  key: string,
  stats: LearningStats | undefined,
): string {
  if (!stats) return "0";
  const byStatus = stats.by_status ?? {};

  switch (key) {
    case "pending":
      return (byStatus.pending ?? 0).toLocaleString("fr-FR");
    case "approved":
      return (
        (byStatus.approved ?? 0) + (byStatus.modified ?? 0)
      ).toLocaleString("fr-FR");
    case "rejected":
      return (byStatus.rejected ?? 0).toLocaleString("fr-FR");
    case "coverage":
      return `${(stats.approval_rate * 100).toFixed(0)}%`;
    default:
      return "0";
  }
}

export function LearningKPI({ stats, isLoading }: LearningKPIProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <KPICardSkeleton key={i} />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {kpiItems.map((item) => {
        const Icon = item.icon;
        return (
          <Card key={item.key}>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-3">
                <div className={`rounded-lg p-2 ${item.color}`}>
                  <Icon className="h-5 w-5" strokeWidth={1.75} />
                </div>
                <span className="text-sm font-medium text-muted-foreground">
                  {item.label}
                </span>
              </div>
              <span className="text-2xl font-heading font-bold">
                {getValue(item.key, stats)}
              </span>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
