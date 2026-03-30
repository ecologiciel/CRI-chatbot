"use client";

import { Send, CheckCircle, Eye, AlertCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { CampaignStatsData } from "@/types/campaign";

interface CampaignStatsProps {
  stats: CampaignStatsData | undefined;
  isLoading: boolean;
}

const kpiItems = [
  {
    key: "sent" as const,
    label: "Envoyés",
    icon: Send,
    color: "text-primary bg-primary/10",
    rateKey: null,
  },
  {
    key: "delivered" as const,
    label: "Délivrés",
    icon: CheckCircle,
    color: "text-[hsl(var(--success))] bg-[hsl(var(--success))]/10",
    rateKey: "delivery_rate" as const,
  },
  {
    key: "read" as const,
    label: "Lus",
    icon: Eye,
    color: "text-[hsl(var(--info))] bg-[hsl(var(--info))]/10",
    rateKey: "read_rate" as const,
  },
  {
    key: "failed" as const,
    label: "Échoués",
    icon: AlertCircle,
    color: "text-destructive bg-destructive/10",
    rateKey: null,
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

export function CampaignStats({ stats, isLoading }: CampaignStatsProps) {
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
        const value = stats?.[item.key] ?? 0;
        const total = stats?.total ?? 0;
        const rate =
          item.rateKey && stats ? stats[item.rateKey] : null;

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
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-heading font-bold">
                  {value.toLocaleString("fr-FR")}
                </span>
                {total > 0 && (
                  <span className="text-sm text-muted-foreground">
                    / {total.toLocaleString("fr-FR")}
                  </span>
                )}
              </div>
              {rate !== null && rate !== undefined && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {rate.toFixed(1)}%
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
