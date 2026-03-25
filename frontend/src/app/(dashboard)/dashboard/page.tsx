import {
  MessageSquare,
  MessageCircle,
  CheckCircle,
  Star,
  BarChart3,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { KPICard } from "@/types";

const kpis: KPICard[] = [
  {
    title: "Conversations actives",
    value: 24,
    icon: MessageSquare,
    color: "primary",
  },
  {
    title: "Messages aujourd'hui",
    value: 156,
    icon: MessageCircle,
    color: "info",
  },
  {
    title: "Taux de résolution",
    value: "87%",
    icon: CheckCircle,
    color: "success",
  },
  {
    title: "Score CSAT",
    value: "4.2/5",
    icon: Star,
    color: "warning",
  },
];

const colorClasses: Record<KPICard["color"], string> = {
  primary: "text-primary bg-primary/10",
  success: "text-success bg-success/10",
  warning: "text-warning bg-warning/10",
  info: "text-info bg-info/10",
};

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold font-heading">Tableau de bord</h1>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map((kpi) => {
          const Icon = kpi.icon;
          return (
            <Card key={kpi.title}>
              <CardContent className="p-6">
                <div className="flex items-center gap-3 mb-3">
                  <div className={`rounded-lg p-2 ${colorClasses[kpi.color]}`}>
                    <Icon className="h-5 w-5" strokeWidth={1.75} />
                  </div>
                  <span className="text-sm text-muted-foreground">{kpi.title}</span>
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
          <BarChart3 className="h-12 w-12 text-muted-foreground/40 mb-4" strokeWidth={1.5} />
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
