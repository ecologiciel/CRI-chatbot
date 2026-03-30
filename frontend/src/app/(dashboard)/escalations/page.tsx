"use client";

import { useState } from "react";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { EscalationList } from "@/components/escalations/escalation-list";
import { EscalationDetail } from "@/components/escalations/escalation-detail";
import { EscalationStatsBar } from "@/components/escalations/escalation-stats";
import { useEscalationStats, useEscalationWebSocket } from "@/hooks/use-escalations";

export default function EscalationsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { isConnected } = useEscalationWebSocket();
  const { data: stats, isLoading: statsLoading } = useEscalationStats();

  return (
    <div className="space-y-4">
      {/* Mobile header — changes based on selection */}
      <div className="md:hidden">
        {selectedId ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedId(null)}
            className="gap-2"
          >
            <ArrowLeft className="h-4 w-4 rtl:rotate-180" strokeWidth={1.75} />
            Retour aux escalades
          </Button>
        ) : (
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold font-heading text-foreground">
                Escalades
              </h1>
              <WebSocketIndicator connected={isConnected} />
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              Gestion des conversations transférées aux agents humains
            </p>
          </div>
        )}
      </div>

      {/* Desktop header */}
      <div className="hidden md:block">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold font-heading text-foreground">
            Escalades
          </h1>
          <WebSocketIndicator connected={isConnected} />
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          Gestion des conversations transférées aux agents humains
        </p>
      </div>

      {/* Stats bar */}
      <EscalationStatsBar stats={stats} isLoading={statsLoading} />

      {/* Master-detail layout */}
      <div className="rounded-lg border bg-card shadow-card overflow-hidden h-[calc(100vh-280px)] min-h-[500px]">
        {/* Desktop: side-by-side */}
        <div className="hidden md:flex h-full">
          <div className="w-[400px] shrink-0">
            <EscalationList
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
          <div className="flex-1">
            {selectedId ? (
              <EscalationDetail escalationId={selectedId} />
            ) : (
              <EmptyState />
            )}
          </div>
        </div>

        {/* Mobile: list OR detail */}
        <div className="md:hidden h-full">
          {selectedId ? (
            <EscalationDetail escalationId={selectedId} />
          ) : (
            <EscalationList
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function WebSocketIndicator({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-1.5" title={connected ? "Connecté" : "Déconnecté"}>
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          connected
            ? "bg-[#5F8B5F] shadow-[0_0_4px_rgba(95,139,95,0.5)]"
            : "bg-[#B5544B]",
        )}
      />
      <span className="text-[10px] text-muted-foreground hidden sm:inline">
        {connected ? "Temps réel" : "Hors ligne"}
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3">
      <AlertTriangle className="h-12 w-12 opacity-30" strokeWidth={1.5} />
      <p className="text-sm">Sélectionnez une escalade</p>
    </div>
  );
}
