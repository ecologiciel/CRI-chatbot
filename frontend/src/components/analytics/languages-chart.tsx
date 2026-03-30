"use client";

import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { LanguageDistribution } from "@/types/analytics";

const LANGUAGE_COLORS: Record<string, string> = {
  fr: "#C4704B",
  ar: "#D4A574",
  en: "#7A8B5F",
};

function ChartSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="h-5 w-40 bg-muted animate-pulse rounded" />
      </CardHeader>
      <CardContent>
        <div className="h-[250px] bg-muted/50 animate-pulse rounded-lg" />
      </CardContent>
    </Card>
  );
}

interface LanguagesChartProps {
  data: LanguageDistribution[] | undefined;
  isLoading: boolean;
}

export function LanguagesChart({ data, isLoading }: LanguagesChartProps) {
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
          Répartition par langue
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(30 12% 90%)" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 12 }}
              stroke="hsl(20 12% 37%)"
            />
            <YAxis
              orientation={isRTL ? "right" : "left"}
              tick={{ fontSize: 12 }}
              stroke="hsl(20 12% 37%)"
            />
            <Tooltip
              formatter={(value) => [
                Number(value).toLocaleString("fr-FR"),
                "Conversations",
              ]}
              contentStyle={{
                backgroundColor: "white",
                border: "1px solid hsl(30 12% 90%)",
                borderRadius: "8px",
                boxShadow: "0 4px 12px rgba(61,43,31,0.12)",
              }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={60}>
              {data.map((entry) => (
                <Cell
                  key={entry.language}
                  fill={LANGUAGE_COLORS[entry.language] ?? "#C4704B"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
