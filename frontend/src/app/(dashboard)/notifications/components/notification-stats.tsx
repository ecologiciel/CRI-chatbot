"use client";

import { Send, CircleSlash, AlertTriangle, Activity } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useNotificationStats } from "@/hooks/use-notifications";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

// ---------------------------------------------------------------------------
// KPI config
// ---------------------------------------------------------------------------

interface KPIConfig {
  title: string;
  icon: LucideIcon;
  colorClass: string;
  getValue: (stats: {
    total_sent: number;
    total_skipped: number;
    total_failed: number;
  }) => number;
}

const KPI_CARDS: KPIConfig[] = [
  {
    title: "Total envoyées",
    icon: Send,
    colorClass: "text-primary bg-primary/10",
    getValue: (s) => s.total_sent,
  },
  {
    title: "Ignorées",
    icon: CircleSlash,
    colorClass: "text-[hsl(var(--warning))] bg-[hsl(var(--warning))]/10",
    getValue: (s) => s.total_skipped,
  },
  {
    title: "Échouées",
    icon: AlertTriangle,
    colorClass: "text-destructive bg-destructive/10",
    getValue: (s) => s.total_failed,
  },
  {
    title: "Total traitées",
    icon: Activity,
    colorClass: "text-[hsl(var(--info))] bg-[hsl(var(--info))]/10",
    getValue: (s) => s.total_sent + s.total_skipped + s.total_failed,
  },
];

const PERIODS = [
  { label: "7j", value: 7 },
  { label: "30j", value: 30 },
  { label: "90j", value: 90 },
] as const;

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface NotificationStatsProps {
  days: number;
  onPeriodChange: (days: number) => void;
}

export function NotificationStats({
  days,
  onPeriodChange,
}: NotificationStatsProps) {
  const { data: stats, isLoading } = useNotificationStats(days);

  return (
    <div className="space-y-4">
      {/* Period toggle */}
      <div className="flex items-center gap-1">
        {PERIODS.map((p) => (
          <Button
            key={p.value}
            variant="outline"
            size="sm"
            className={cn(
              "text-xs",
              days === p.value &&
                "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground",
            )}
            onClick={() => onPeriodChange(p.value)}
          >
            {p.label}
          </Button>
        ))}
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <KPICardSkeleton key={i} />
            ))
          : KPI_CARDS.map((kpi) => {
              const Icon = kpi.icon;
              const value = stats
                ? kpi.getValue(stats)
                : 0;
              return (
                <Card key={kpi.title}>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-3 mb-3">
                      <div className={cn("rounded-lg p-2", kpi.colorClass)}>
                        <Icon className="h-5 w-5" strokeWidth={1.75} />
                      </div>
                      <span className="text-sm text-muted-foreground">
                        {kpi.title}
                      </span>
                    </div>
                    <p className="text-3xl font-bold font-heading">
                      {value.toLocaleString("fr-FR")}
                    </p>
                  </CardContent>
                </Card>
              );
            })}
      </div>
    </div>
  );
}
