"use client";

import { useState, useMemo } from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { useEscalations } from "@/hooks/use-escalations";
import { EscalationCard } from "./escalation-card";
import type { EscalationStatus, Escalation } from "@/types/escalation";

const PRIORITY_ORDER: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

function sortEscalations(items: Escalation[]): Escalation[] {
  return [...items].sort((a, b) => {
    // Priority first (high → low)
    const pa = PRIORITY_ORDER[a.priority] ?? 9;
    const pb = PRIORITY_ORDER[b.priority] ?? 9;
    if (pa !== pb) return pa - pb;
    // Then oldest first
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  });
}

type FilterTab = "all" | EscalationStatus;

const FILTER_TABS: { value: FilterTab; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "pending", label: "En attente" },
  { value: "assigned", label: "En cours" },
  { value: "resolved", label: "Résolues" },
];

interface EscalationListProps {
  selectedId: string | null;
  onSelect: (id: string) => void;
  className?: string;
}

export function EscalationList({
  selectedId,
  onSelect,
  className,
}: EscalationListProps) {
  const [filter, setFilter] = useState<FilterTab>("all");

  const statusParam =
    filter === "all"
      ? undefined
      : filter === "assigned"
        ? undefined // "assigned" tab shows both assigned + in_progress
        : filter;

  const { data, isLoading, isError } = useEscalations({
    page_size: 50,
    status: statusParam,
  });

  const items = useMemo(() => {
    if (!data?.items) return [];
    let filtered = data.items;

    // Client-side filter for the "assigned" tab (shows assigned + in_progress)
    if (filter === "assigned") {
      filtered = filtered.filter(
        (e) => e.status === "assigned" || e.status === "in_progress",
      );
    } else if (filter !== "all") {
      filtered = filtered.filter((e) => e.status === filter);
    }

    return sortEscalations(filtered);
  }, [data?.items, filter]);

  return (
    <div className={cn("flex flex-col h-full border-e border-border", className)}>
      {/* Filter tabs */}
      <div className="shrink-0 flex gap-1 px-3 pt-3 pb-2 overflow-x-auto">
        {FILTER_TABS.map((tab) => (
          <Button
            key={tab.value}
            variant={filter === tab.value ? "default" : "ghost"}
            size="sm"
            onClick={() => setFilter(tab.value)}
            className={cn(
              "text-xs shrink-0",
              filter === tab.value
                ? ""
                : "text-muted-foreground",
            )}
          >
            {tab.label}
          </Button>
        ))}
      </div>

      {/* List */}
      <ScrollArea className="flex-1">
        {isLoading && <ListSkeleton />}

        {isError && (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground gap-2 px-4">
            <AlertTriangle className="h-8 w-8 opacity-30" strokeWidth={1.5} />
            <p className="text-xs text-center">Erreur de chargement</p>
          </div>
        )}

        {!isLoading && !isError && items.length === 0 && (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground gap-2 px-4">
            <Inbox className="h-8 w-8 opacity-30" strokeWidth={1.5} />
            <p className="text-xs text-center">Aucune escalade</p>
          </div>
        )}

        {items.map((esc) => (
          <EscalationCard
            key={esc.id}
            escalation={esc}
            isActive={selectedId === esc.id}
            onSelect={() => onSelect(esc.id)}
          />
        ))}
      </ScrollArea>
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-0">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="px-4 py-3 border-b border-border"
        >
          <div className="flex items-start gap-3">
            <div className="h-2.5 w-2.5 rounded-full bg-muted animate-pulse mt-1.5" />
            <div className="flex-1 space-y-2">
              <div className="flex justify-between">
                <div className="h-4 w-24 bg-muted animate-pulse rounded" />
                <div className="h-3 w-10 bg-muted animate-pulse rounded" />
              </div>
              <div className="h-3 w-full bg-muted animate-pulse rounded" />
              <div className="flex gap-1.5">
                <div className="h-5 w-16 bg-muted animate-pulse rounded-full" />
                <div className="h-5 w-20 bg-muted animate-pulse rounded-full" />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
