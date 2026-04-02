"use client";

import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { cn } from "@/lib/utils";
import type { DossierHistory } from "@/types/dossier";
import { DOSSIER_FIELD_LABELS, STATUT_CONFIG } from "@/types/dossier";
import type { DossierStatut } from "@/types/dossier";
import { ScrollArea } from "@/components/ui/scroll-area";

interface DossierTimelineProps {
  history: DossierHistory[];
}

function getDotColor(entry: DossierHistory): string {
  // If the change is a status change, color the dot with the new status color
  if (entry.field_changed === "statut" && entry.new_value) {
    const cfg = STATUT_CONFIG[entry.new_value as DossierStatut];
    if (cfg) {
      // Extract the text color class and convert to bg
      return cfg.className
        .split(" ")
        .find((c) => c.startsWith("text-"))
        ?.replace("text-", "bg-") ?? "bg-muted-foreground";
    }
  }
  return "bg-muted-foreground";
}

function formatFieldChange(entry: DossierHistory): string {
  const label = DOSSIER_FIELD_LABELS[entry.field_changed] ?? entry.field_changed;

  // For status changes, show French labels
  if (entry.field_changed === "statut") {
    const oldLabel =
      entry.old_value && STATUT_CONFIG[entry.old_value as DossierStatut]
        ? STATUT_CONFIG[entry.old_value as DossierStatut].label
        : entry.old_value ?? "—";
    const newLabel =
      entry.new_value && STATUT_CONFIG[entry.new_value as DossierStatut]
        ? STATUT_CONFIG[entry.new_value as DossierStatut].label
        : entry.new_value ?? "—";
    return `${label} : ${oldLabel} → ${newLabel}`;
  }

  const old = entry.old_value || "—";
  const val = entry.new_value || "—";
  return `${label} : ${old} → ${val}`;
}

export function DossierTimeline({ history }: DossierTimelineProps) {
  if (history.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        Aucune modification enregistrée
      </p>
    );
  }

  return (
    <ScrollArea className="max-h-[400px]">
      <div className="relative ps-6">
        {/* Vertical line */}
        <div className="absolute start-[7px] top-2 bottom-2 w-[2px] bg-border" />

        <div className="space-y-4">
          {history.map((entry) => (
            <div key={entry.id} className="relative">
              {/* Dot */}
              <div
                className={cn(
                  "absolute start-[-21px] top-1.5 h-4 w-4 rounded-full border-2 border-background",
                  getDotColor(entry),
                )}
              />

              {/* Content */}
              <div className="space-y-0.5">
                <p className="text-xs text-muted-foreground">
                  {format(new Date(entry.changed_at), "dd/MM/yyyy HH:mm", {
                    locale: fr,
                  })}
                </p>
                <p className="text-sm font-medium">
                  {formatFieldChange(entry)}
                </p>
                {entry.sync_log_id && (
                  <p className="text-xs text-muted-foreground">
                    Import #{entry.sync_log_id.slice(0, 8)}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </ScrollArea>
  );
}
