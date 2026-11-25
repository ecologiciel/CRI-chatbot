"use client";

import { FormEvent, useState } from "react";
import { BarChart3, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useDocuments } from "@/hooks/use-documents";
import { useCreateRAGEvaluationCase, useRAGEvaluationCases, useRAGEvaluationRuns, useRunRAGEvaluation } from "@/hooks/use-rag-evaluations";
import type { RAGEvaluationCaseResult } from "@/types/kb";

function percentage(value: unknown): string {
  return typeof value === "number" ? `${Math.round(value * 100)} %` : "—";
}

export function RAGEvaluationTab() {
  const { data: runs = [], isLoading } = useRAGEvaluationRuns();
  const { data: cases = [], isError: casesError } = useRAGEvaluationCases();
  const createCase = useCreateRAGEvaluationCase();
  const runEvaluation = useRunRAGEvaluation();
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<"fr" | "ar" | "en">("fr");
  const [expectedDocument, setExpectedDocument] = useState("");
  const [documentPage, setDocumentPage] = useState(1);
  const { data: documents, isError: documentsError } = useDocuments({ status: "indexed", page: documentPage, page_size: 100 });
  const [abstain, setAbstain] = useState(false);
  const latest = runs[0];
  const latestResults = Array.isArray(latest?.metrics.case_results)
    ? latest.metrics.case_results as RAGEvaluationCaseResult[] : [];
  const resultsByCase = new Map(latestResults.map((result) => [result.case_id, result]));

  function addCase(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || (!abstain && !expectedDocument)) return;
    createCase.mutate({
      query: question.trim(), language,
      expected_document_ids: abstain ? [] : [expectedDocument],
      expects_abstention: abstain,
    }, {
      onSuccess: () => { setQuestion(""); setExpectedDocument(""); setAbstain(false); toast.success("Question ajoutée"); },
      onError: () => toast.error("Impossible d’ajouter la question"),
    });
  }

  return (
    <div className="rounded-lg border bg-card p-5 shadow-card space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-heading font-semibold flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Évaluation RAG</h2>
          <p className="text-sm text-muted-foreground mt-1">Mesures indicatives : la provenance ne garantit pas la justesse d’une citation et le seuil de confiance ne mesure pas les abstentions réelles.</p>
        </div>
        <Button size="sm" disabled={runEvaluation.isPending} onClick={() => runEvaluation.mutate(undefined, {
          onSuccess: () => toast.success("Évaluation terminée"),
          onError: () => toast.error("Impossible de lancer l’évaluation"),
        })}>
          {runEvaluation.isPending ? <Loader2 className="h-4 w-4 me-2 animate-spin" /> : <Play className="h-4 w-4 me-2" />} Lancer
        </Button>
      </div>
      {isLoading ? <p className="text-sm text-muted-foreground">Chargement…</p> : latest ? (
        <div className="grid gap-3 sm:grid-cols-3 text-sm">
          <Metric label="Rappel sources @5" value={percentage(latest.metrics.source_recall_at_5)} />
          <Metric label="Cas avec provenance complète" value={percentage(latest.metrics.citation_coverage)} />
          <Metric label="Accord du seuil de confiance" value={percentage(latest.metrics.confidence_abstention_proxy)} />
        </div>
      ) : <p className="text-sm text-muted-foreground">Aucune évaluation exécutée.</p>}
      <form onSubmit={addCase} className="space-y-3 border-t pt-4">
        <h3 className="font-semibold">Ajouter une question de test</h3>
        <p className="text-sm text-muted-foreground">Choisissez le document qui doit être retrouvé, ou indiquez que la base ne contient pas de réponse. Les cas demandent une revue humaine.</p>
        <label className="block text-sm">Question
          <textarea className="mt-1 w-full rounded-md border bg-background p-2" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={5000} required rows={2} />
        </label>
        <label className="block text-sm">Langue
          <select className="mt-1 block rounded-md border bg-background p-2" value={language} onChange={(e) => setLanguage(e.target.value as "fr" | "ar" | "en")}>
            <option value="fr">Français</option><option value="ar">Arabe</option><option value="en">Anglais</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={abstain} onChange={(e) => setAbstain(e.target.checked)} /> Aucune réponse attendue dans la base</label>
        {!abstain && <label className="block text-sm">Document attendu
          <select className="mt-1 block w-full rounded-md border bg-background p-2" value={expectedDocument} onChange={(e) => setExpectedDocument(e.target.value)} required>
            <option value="">Sélectionner un document indexé</option>
            {documents?.items.map((doc) => <option key={doc.id} value={doc.id}>{doc.title}</option>)}
          </select>
          {documents && documents.total > 100 && <span className="flex items-center gap-2 mt-2 text-muted-foreground">
            <button type="button" disabled={documentPage === 1} onClick={() => { setDocumentPage((p) => p - 1); setExpectedDocument(""); }} className="underline disabled:opacity-40">Précédent</button>
            Page {documentPage} sur {Math.ceil(documents.total / 100)}
            <button type="button" disabled={documentPage * 100 >= documents.total} onClick={() => { setDocumentPage((p) => p + 1); setExpectedDocument(""); }} className="underline disabled:opacity-40">Suivant</button>
          </span>}
          {documentsError && <span className="text-destructive">Impossible de charger les documents.</span>}
        </label>}
        <Button type="submit" size="sm" disabled={createCase.isPending}>Ajouter</Button>
      </form>
      <section className="space-y-2 border-t pt-4">
        <h3 className="font-semibold">Questions de test ({cases.length})</h3>
        {casesError && <p className="text-sm text-destructive">Impossible de charger les questions.</p>}
        {latest && latestResults.length === 0 && <p className="text-sm text-muted-foreground">Relancez l’évaluation pour obtenir les résultats par question.</p>}
        {cases.map((item) => {
          const result = resultsByCase.get(item.id);
          let status = "Non évaluée dans le dernier test";
          if (result?.recall_evaluated) status = result.expected_document_rank ? `Document attendu retrouvé en position ${result.expected_document_rank}` : "Document attendu absent des 5 premiers résultats";
          else if (result?.expects_abstention) status = result.low_confidence ? "Confiance faible ; abstention réelle à vérifier" : "Confiance non faible ; abstention réelle à vérifier";
          else if (result) status = "Aucun document attendu renseigné";
          return <div key={item.id} className="rounded-md border p-3 text-sm"><p>{item.query}</p><p className="mt-1 text-muted-foreground">{status}</p></div>;
        })}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md bg-muted p-3"><p className="text-muted-foreground">{label}</p><p className="font-semibold text-lg mt-1">{value}</p></div>;
}
