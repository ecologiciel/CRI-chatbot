"use client";

import { Card, CardContent } from "@/components/ui/card";
import type { DossierStats as DossierStatsType } from "@/types/dossier";
import { STATS_CARD_CONFIG } from "@/types/dossier";
import { cn } from "@/lib/utils";

interface DossierStatsProps {
  stats?: DossierStatsType;
  isLoading: boolean;
}

export function DossierStats({ stats, isLoading }: DossierStatsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-4">
        {STATS_CARD_CONFIG.map((card) => (
          <Card key={card.key} className="shadow-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-muted animate-pulse" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 w-16 bg-muted animate-pulse rounded" />
                  <div className="h-7 w-12 bg-muted animate-pulse rounded" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-4">
      {STATS_CARD_CONFIG.map((card) => {
        const Icon = card.icon;
        const value = stats?.[card.key] ?? 0;
        return (
          <Card
            key={card.key}
            className="shadow-card hover:shadow-elevated transition-shadow duration-200"
          >
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                    card.color,
                  )}
                >
                  <Icon className={cn("h-5 w-5", card.textColor)} strokeWidth={1.75} />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground truncate">
                    {card.label}
                  </p>
                  <p className="text-2xl font-bold font-heading">
                    {value.toLocaleString("fr-FR")}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
