"use client";

import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  type PieLabelRenderProps,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { QuestionTypeDistribution } from "@/types/analytics";

const TYPE_COLORS: Record<string, string> = {
  faq: "#C4704B",
  escalade: "#7A8B5F",
  en_cours: "#5B7A8B",
};

function ChartSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="h-5 w-44 bg-muted animate-pulse rounded" />
      </CardHeader>
      <CardContent>
        <div className="h-[250px] bg-muted/50 animate-pulse rounded-lg" />
      </CardContent>
    </Card>
  );
}

interface QuestionsDonutProps {
  data: QuestionTypeDistribution[] | undefined;
  isLoading: boolean;
}

export function QuestionsDonut({ data, isLoading }: QuestionsDonutProps) {
  if (isLoading) return <ChartSkeleton />;
  if (!data || data.length === 0) return null;

  const total = data.reduce((sum, d) => sum + d.count, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-heading">
          Types de conversations
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <PieChart>
            <Pie
              data={data}
              dataKey="count"
              nameKey="label"
              cx="50%"
              cy="50%"
              innerRadius={55}
              outerRadius={90}
              paddingAngle={3}
              strokeWidth={0}
              label={(props: PieLabelRenderProps) =>
                `${props.name ?? ""} ${((props.percent ?? 0) * 100).toFixed(0)}%`
              }
            >
              {data.map((entry) => (
                <Cell
                  key={entry.type}
                  fill={TYPE_COLORS[entry.type] ?? "#D4A574"}
                />
              ))}
            </Pie>
            <Tooltip
              formatter={(value, name) => [
                `${Number(value).toLocaleString("fr-FR")} (${
                  total > 0 ? Math.round((Number(value) / total) * 100) : 0
                }%)`,
                String(name),
              ]}
              contentStyle={{
                backgroundColor: "white",
                border: "1px solid hsl(30 12% 90%)",
                borderRadius: "8px",
                boxShadow: "0 4px 12px rgba(61,43,31,0.12)",
              }}
            />
            <Legend />
            {/* Center total text */}
            <text
              x="50%"
              y="50%"
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-foreground"
              style={{ fontSize: "20px", fontWeight: 700 }}
            >
              {total.toLocaleString("fr-FR")}
            </text>
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
