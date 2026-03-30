"use client";

import { Sparkles } from "lucide-react";

interface AiSummaryBannerProps {
  summary: string | null;
}

export function AiSummaryBanner({ summary }: AiSummaryBannerProps) {
  if (!summary) return null;

  return (
    <div className="mx-4 mt-3 rounded-lg bg-[hsl(var(--olive))]/10 border border-[hsl(var(--olive))]/20 px-3.5 py-2.5">
      <div className="flex items-start gap-2.5">
        <Sparkles
          className="h-4 w-4 shrink-0 mt-0.5 text-[hsl(var(--olive))]"
          strokeWidth={1.75}
        />
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--olive))] mb-1">
            Résumé IA
          </p>
          <p className="text-sm text-foreground/80 leading-relaxed">
            {summary}
          </p>
        </div>
      </div>
    </div>
  );
}
