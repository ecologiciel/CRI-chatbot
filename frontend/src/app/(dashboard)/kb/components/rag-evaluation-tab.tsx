"use client";

import { BarChart3, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useRAGEvaluationRuns, useRunRAGEvaluation } from "@/hooks/use-rag-evaluations";

function percentage(value: unknown): string {
  return typeof value === "number" ? `${Math.round(value * 100)} %` : "—";
}

export function RAGEvaluationTab() {
  const { data: runs = [], isLoading } = useRAGEvaluationRuns();
  const runEvaluation = useRunRAGEvaluation();
  const latest = runs[0];

  return (
    <div className="rounded-lg border bg-card p-5 shadow-card space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-heading font-semibold flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Évaluation RAG</h2>
          <p className="text-sm text-muted-foreground mt-1">Mesures indicatives : la provenance ne garantit pas la justesse d’une citation et le seuil de confiance ne mesure pas les abstentions réelles.</p>
        </div>
        <Button
          size="sm"
          disabled={runEvaluation.isPending}
          onClick={() => runEvaluation.mutate(undefined, {
            onSuccess: () => toast.success("Évaluation terminée"),
            onError: () => toast.error("Impossible de lancer l'évaluation"),
          })}
        >
          {runEvaluation.isPending ? <Loader2 className="h-4 w-4 me-2 animate-spin" /> : <Play className="h-4 w-4 me-2" />}
          Lancer
        </Button>
      </div>
      {isLoading ? <p className="text-sm text-muted-foreground">Chargement…</p> : latest ? (
        <div className="grid gap-3 sm:grid-cols-3 text-sm">
          <Metric label="Rappel sources @5" value={percentage(latest.metrics.source_recall_at_5)} />
          <Metric label="Cas avec provenance complète" value={percentage(latest.metrics.citation_coverage)} />
          <Metric label="Accord du seuil de confiance" value={percentage(latest.metrics.confidence_abstention_proxy)} />
        </div>
      ) : <p className="text-sm text-muted-foreground">Aucune évaluation exécutée. Ajoutez des cas via l’API d’évaluation puis lancez le monitoring.</p>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md bg-muted p-3"><p className="text-muted-foreground">{label}</p><p className="font-semibold text-lg mt-1">{value}</p></div>;
}
