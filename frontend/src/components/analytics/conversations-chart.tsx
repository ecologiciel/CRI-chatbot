"use client";

import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TimeSeriesPoint } from "@/types/analytics";

const CHART_COLORS = {
  conversations: "#C4704B",
  messages: "#D4A574",
  escalations: "#5B7A8B",
};

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
}

function ChartSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="h-5 w-48 bg-muted animate-pulse rounded" />
      </CardHeader>
      <CardContent>
        <div className="h-[300px] bg-muted/50 animate-pulse rounded-lg" />
      </CardContent>
    </Card>
  );
}

interface ConversationsChartProps {
  data: TimeSeriesPoint[] | undefined;
  isLoading: boolean;
}

export function ConversationsChart({
  data,
  isLoading,
}: ConversationsChartProps) {
  const [isRTL, setIsRTL] = useState(false);

  useEffect(() => {
    setIsRTL(document.documentElement.dir === "rtl");
  }, []);

  if (isLoading) return <ChartSkeleton />;
  if (!data || data.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-heading">
          Évolution journalière
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(30 12% 90%)" />
            <XAxis
              dataKey="date"
              tickFormatter={formatDateLabel}
              tick={{ fontSize: 12 }}
              stroke="hsl(20 12% 37%)"
            />
            <YAxis
              orientation={isRTL ? "right" : "left"}
              tick={{ fontSize: 12 }}
              stroke="hsl(20 12% 37%)"
            />
            <Tooltip
              labelFormatter={(label) => formatDateLabel(String(label))}
              contentStyle={{
                backgroundColor: "white",
                border: "1px solid hsl(30 12% 90%)",
                borderRadius: "8px",
                boxShadow: "0 4px 12px rgba(61,43,31,0.12)",
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="conversations"
              name="Conversations"
              stroke={CHART_COLORS.conversations}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Line
              type="monotone"
              dataKey="messages"
              name="Messages"
              stroke={CHART_COLORS.messages}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Line
              type="monotone"
              dataKey="escalations"
              name="Escalades"
              stroke={CHART_COLORS.escalations}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
