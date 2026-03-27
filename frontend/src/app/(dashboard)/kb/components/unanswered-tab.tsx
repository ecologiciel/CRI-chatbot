"use client";

import { CheckCircle, X, Pencil, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useUnansweredQuestions, useReviewQuestion } from "@/hooks/use-feedback";
import type { UnansweredQuestionStatus } from "@/types/kb";

const statusConfig: Record<
  UnansweredQuestionStatus,
  { label: string; className: string }
> = {
  pending: {
    label: "En attente",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  approved: {
    label: "Validée",
    className:
      "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  modified: {
    label: "Modifiée",
    className: "bg-primary/10 text-primary border-0",
  },
  rejected: {
    label: "Rejetée",
    className: "bg-destructive/10 text-destructive border-0",
  },
  injected: {
    label: "Injectée",
    className:
      "bg-[hsl(var(--olive))]/10 text-[hsl(var(--olive))] border-0",
  },
};

const languageLabels: Record<string, string> = {
  fr: "FR",
  ar: "AR",
  en: "EN",
};

export function UnansweredTab() {
  const { data, isLoading, isError, refetch } = useUnansweredQuestions();
  const reviewMutation = useReviewQuestion();

  const questions = data?.items ?? [];
  const total = data?.total ?? 0;

  function handleApprove(id: string) {
    reviewMutation.mutate(
      { questionId: id, data: { status: "approved" } },
      {
        onSuccess: () => toast.success("Question validée"),
        onError: () => toast.error("Erreur lors de la validation"),
      },
    );
  }

  function handleReject(id: string) {
    reviewMutation.mutate(
      { questionId: id, data: { status: "rejected" } },
      {
        onSuccess: () => toast.success("Question rejetée"),
        onError: () => toast.error("Erreur lors du rejet"),
      },
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger les questions
        </p>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 me-2" />
          Réessayer
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card shadow-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-start">Question</TableHead>
              <TableHead className="text-start hidden sm:table-cell w-[80px]">
                Langue
              </TableHead>
              <TableHead className="text-start hidden sm:table-cell w-[100px]">
                Fréquence
              </TableHead>
              <TableHead className="text-start hidden md:table-cell">
                Proposition IA
              </TableHead>
              <TableHead className="text-start w-[120px]">Statut</TableHead>
              <TableHead className="text-end w-[120px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Chargement...</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : questions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                  <p className="text-muted-foreground">Aucune question non couverte</p>
                </TableCell>
              </TableRow>
            ) : (
              questions.map((q) => {
                const status = statusConfig[q.status];
                return (
                  <TableRow key={q.id}>
                    <TableCell>
                      <p className="line-clamp-2 font-medium">{q.question}</p>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <Badge variant="secondary" className="text-xs font-mono">
                        {languageLabels[q.language] ?? q.language}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <Badge variant="outline" className="font-mono">
                        {q.frequency}x
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {q.proposed_answer ? (
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {q.proposed_answer}
                        </p>
                      ) : (
                        <span className="text-sm text-muted-foreground italic">
                          En attente
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={cn("text-xs font-medium", status.className)}
                      >
                        {status.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-end">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-[hsl(var(--success))] hover:text-[hsl(var(--success))] hover:bg-[hsl(var(--success))]/10"
                          onClick={() => handleApprove(q.id)}
                          disabled={reviewMutation.isPending}
                        >
                          <CheckCircle className="h-4 w-4" />
                          <span className="sr-only">Valider</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                          onClick={() => handleReject(q.id)}
                          disabled={reviewMutation.isPending}
                        >
                          <X className="h-4 w-4" />
                          <span className="sr-only">Rejeter</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-primary hover:text-primary hover:bg-primary/10"
                          disabled
                        >
                          <Pencil className="h-4 w-4" />
                          <span className="sr-only">Modifier</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">
        {total} question{total !== 1 ? "s" : ""} non couvertes
      </p>
    </div>
  );
}
