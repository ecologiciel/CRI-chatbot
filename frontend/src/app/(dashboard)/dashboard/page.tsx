"use client";

import {
  MessageSquare,
  MessageCircle,
  CheckCircle,
  Star,
  Users,
  BookOpen,
  HelpCircle,
  BarChart3,
  Loader2,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useDashboardStats } from "@/hooks/use-dashboard";
import type { LucideIcon } from "lucide-react";

type KPIColor = "primary" | "success" | "warning" | "info" | "muted";

interface KPIItem {
  title: string;
  value: string | number;
  icon: LucideIcon;
  color: KPIColor;
}

const colorClasses: Record<KPIColor, string> = {
  primary: "text-primary bg-primary/10",
  success: "text-success bg-success/10",
  warning: "text-warning bg-warning/10",
  info: "text-info bg-info/10",
  muted: "text-muted-foreground bg-muted",
};

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

export default function DashboardPage() {
  const { data: stats, isLoading, isError, refetch } = useDashboardStats();

  const primaryKpis: KPIItem[] = stats
    ? [
        {
          title: "Conversations actives",
          value: stats.active_conversations,
          icon: MessageSquare,
          color: "primary",
        },
        {
          title: "Messages aujourd'hui",
          value: stats.messages_today,
          icon: MessageCircle,
          color: "info",
        },
        {
          title: "Taux de résolution",
          value: `${stats.resolution_rate}%`,
          icon: CheckCircle,
          color: "success",
        },
        {
          title: "Score CSAT",
          value: `${stats.csat_score}/5`,
          icon: Star,
          color: "warning",
        },
      ]
    : [];

  const secondaryKpis: KPIItem[] = stats
    ? [
        {
          title: "Contacts",
          value: stats.total_contacts,
          icon: Users,
          color: "muted",
        },
        {
          title: "Documents KB",
          value: stats.kb_documents_indexed,
          icon: BookOpen,
          color: "muted",
        },
        {
          title: "Questions non couvertes",
          value: stats.unanswered_questions,
          icon: HelpCircle,
          color: "muted",
        },
      ]
    : [];

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold font-heading">Tableau de bord</h1>
      </div>

      {/* Error state */}
      {isError && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <AlertCircle className="h-8 w-8 text-destructive mb-3" />
          <p className="text-sm text-muted-foreground mb-3">
            Impossible de charger les statistiques
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-4 w-4 me-2" />
            Réessayer
          </Button>
        </div>
      )}

      {/* Primary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <KPICardSkeleton key={i} />)
          : primaryKpis.map((kpi) => {
              const Icon = kpi.icon;
              return (
                <Card key={kpi.title}>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-3 mb-3">
                      <div className={`rounded-lg p-2 ${colorClasses[kpi.color]}`}>
                        <Icon className="h-5 w-5" strokeWidth={1.75} />
                      </div>
                      <span className="text-sm text-muted-foreground">
                        {kpi.title}
                      </span>
                    </div>
                    <p className="text-3xl font-bold font-heading">{kpi.value}</p>
                  </CardContent>
                </Card>
              );
            })}
      </div>

      {/* Secondary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {isLoading
          ? Array.from({ length: 3 }).map((_, i) => <KPICardSkeleton key={i} />)
          : secondaryKpis.map((kpi) => {
              const Icon = kpi.icon;
              return (
                <Card key={kpi.title}>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-3 mb-3">
                      <div className={`rounded-lg p-2 ${colorClasses[kpi.color]}`}>
                        <Icon className="h-5 w-5" strokeWidth={1.75} />
                      </div>
                      <span className="text-sm text-muted-foreground">
                        {kpi.title}
                      </span>
                    </div>
                    <p className="text-3xl font-bold font-heading">{kpi.value}</p>
                  </CardContent>
                </Card>
              );
            })}
      </div>

      {/* Chart placeholder */}
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16">
          <BarChart3
            className="h-12 w-12 text-muted-foreground/40 mb-4"
            strokeWidth={1.5}
          />
          <h2 className="text-lg font-heading font-semibold text-muted-foreground">
            Graphiques et analytics
          </h2>
          <p className="text-sm text-muted-foreground/70 mt-1">
            Disponible prochainement
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
