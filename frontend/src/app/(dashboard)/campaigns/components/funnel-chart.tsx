"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import type { CampaignStatsData } from "@/types/campaign";

interface FunnelChartProps {
  stats: CampaignStatsData;
}

const COLORS = [
  "hsl(16, 55%, 53%)",   // terracotta — Envoyés
  "hsl(28, 50%, 64%)",   // sable — Délivrés
  "hsl(80, 19%, 46%)",   // olive — Lus
  "hsl(200, 21%, 45%)",  // info — Cliqués
];

export function FunnelChart({ stats }: FunnelChartProps) {
  const data = [
    { name: "Envoyés", value: stats.sent },
    { name: "Délivrés", value: stats.delivered },
    { name: "Lus", value: stats.read },
    { name: "En attente", value: stats.pending },
  ];

  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <Card>
      <CardContent className="p-6">
        <h3 className="mb-4 text-base font-heading font-semibold">
          Entonnoir de livraison
        </h3>

        {stats.total === 0 ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            Aucune donnée disponible
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data} layout="vertical" barCategoryGap="20%">
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="name"
                width={80}
                tick={{ fontSize: 13, fill: "hsl(var(--muted-foreground))" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                formatter={(value) => [
                  Number(value).toLocaleString("fr-FR"),
                  "Messages",
                ]}
                contentStyle={{
                  borderRadius: "8px",
                  border: "1px solid hsl(var(--border))",
                  backgroundColor: "hsl(var(--card))",
                  fontSize: "13px",
                }}
              />
              <Bar
                dataKey="value"
                radius={[0, 4, 4, 0]}
                maxBarSize={32}
                label={{
                  position: "right",
                  fill: "hsl(var(--muted-foreground))",
                  fontSize: 12,
                  formatter: (v) =>
                    maxValue > 0
                      ? `${((Number(v) / maxValue) * 100).toFixed(0)}%`
                      : "0%",
                }}
              >
                {data.map((_, index) => (
                  <Cell key={index} fill={COLORS[index % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
