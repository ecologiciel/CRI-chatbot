"use client";

import {
  MessageSquare,
  Send,
  CheckCircle,
  Star,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { AnalyticsOverview } from "@/types/analytics";
import type { LucideIcon } from "lucide-react";

type KPIColor = "primary" | "info" | "success" | "warning";

interface KPIConfig {
  title: string;
  icon: LucideIcon;
  color: KPIColor;
  valueKey: keyof AnalyticsOverview;
  trendKey: keyof AnalyticsOverview;
  format: (v: number) => string;
}

const colorClasses: Record<KPIColor, string> = {
  primary: "text-primary bg-primary/10",
  info: "text-info bg-info/10",
  success: "text-success bg-success/10",
  warning: "text-warning bg-warning/10",
};

const KPI_CONFIGS: KPIConfig[] = [
  {
    title: "Conversations",
    icon: MessageSquare,
    color: "primary",
    valueKey: "conversations_total",
    trendKey: "conversations_trend",
    format: (v) => v.toLocaleString("fr-FR"),
  },
  {
    title: "Messages",
    icon: Send,
    color: "info",
    valueKey: "messages_total",
    trendKey: "messages_trend",
    format: (v) => v.toLocaleString("fr-FR"),
  },
  {
    title: "Taux résolution",
    icon: CheckCircle,
    color: "success",
    valueKey: "resolution_rate",
    trendKey: "resolution_trend",
    format: (v) => `${v}%`,
  },
  {
    title: "CSAT moyen",
    icon: Star,
    color: "warning",
    valueKey: "csat_average",
    trendKey: "csat_trend",
    format: (v) => `${v}/5`,
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
        <div className="h-8 w-20 bg-muted animate-pulse rounded mb-2" />
        <div className="h-3 w-16 bg-muted animate-pulse rounded" />
      </CardContent>
    </Card>
  );
}

interface KPICardsProps {
  data: AnalyticsOverview | undefined;
  isLoading: boolean;
}

export function KPICards({ data, isLoading }: KPICardsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <KPICardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {KPI_CONFIGS.map((cfg) => {
        const Icon = cfg.icon;
        const value = data[cfg.valueKey] as number;
        const trend = data[cfg.trendKey] as number;
        const isPositive = trend >= 0;

        return (
          <Card key={cfg.title}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className={`rounded-lg p-2 ${colorClasses[cfg.color]}`}>
                    <Icon className="h-5 w-5" strokeWidth={1.75} />
                  </div>
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {cfg.title}
                  </span>
                </div>
                {trend !== 0 && (
                  <span
                    className={`flex items-center gap-1 text-xs font-medium ${
                      isPositive ? "text-success" : "text-destructive"
                    }`}
                  >
                    {isPositive ? (
                      <TrendingUp className="h-3.5 w-3.5" />
                    ) : (
                      <TrendingDown className="h-3.5 w-3.5" />
                    )}
                    {isPositive ? "+" : ""}
                    {trend}%
                  </span>
                )}
              </div>
              <p className="text-3xl font-bold font-heading">
                {cfg.format(value)}
              </p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
