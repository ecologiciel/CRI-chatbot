"use client";

import { cn } from "@/lib/utils";

interface QuotaIndicatorProps {
  used: number;
  limit: number;
  percentage: number;
  className?: string;
}

export function QuotaIndicator({
  used,
  limit,
  percentage,
  className,
}: QuotaIndicatorProps) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(percentage, 100) / 100) * circumference;

  const colorClass =
    percentage > 95
      ? "text-destructive"
      : percentage > 80
        ? "text-[hsl(var(--warning))]"
        : "text-primary";

  const strokeColor =
    percentage > 95
      ? "hsl(var(--destructive))"
      : percentage > 80
        ? "hsl(var(--warning))"
        : "hsl(var(--primary))";

  return (
    <div className={cn("flex flex-col items-center gap-1", className)}>
      <div className="relative h-20 w-20">
        <svg
          className="h-full w-full -rotate-90"
          viewBox="0 0 80 80"
          fill="none"
        >
          {/* Background circle */}
          <circle
            cx="40"
            cy="40"
            r={radius}
            strokeWidth="6"
            stroke="hsl(var(--muted))"
          />
          {/* Progress circle */}
          <circle
            cx="40"
            cy="40"
            r={radius}
            strokeWidth="6"
            stroke={strokeColor}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="transition-all duration-500"
          />
        </svg>
        {/* Center text */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={cn("text-sm font-bold", colorClass)}>
            {Math.round(percentage)}%
          </span>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {used.toLocaleString("fr-FR")} / {limit.toLocaleString("fr-FR")}
      </p>
      <p className="text-xs text-muted-foreground">
        {(limit - used).toLocaleString("fr-FR")} restants
      </p>
    </div>
  );
}
