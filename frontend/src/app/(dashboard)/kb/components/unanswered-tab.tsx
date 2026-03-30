"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle,
  X,
  Pencil,
  Loader2,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useLearningQuestions,
  useLearningStats,
  useApproveQuestion,
} from "@/hooks/use-learning";
import type { UnansweredQuestionStatus } from "@/types/kb";

import { LearningKPI } from "./learning-kpi";
import { QuestionDetailSheet } from "./question-detail-sheet";
import { RejectDialog } from "./reject-dialog";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

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

const STATUS_OPTIONS = [
  { value: "all", label: "Tous les statuts" },
  { value: "pending", label: "En attente" },
  { value: "approved", label: "Validées" },
  { value: "modified", label: "Modifiées" },
  { value: "rejected", label: "Rejetées" },
  { value: "injected", label: "Injectées" },
];

const DATE_OPTIONS = [
  { value: "all", label: "Toutes les périodes" },
  { value: "7", label: "7 derniers jours" },
  { value: "30", label: "30 derniers jours" },
  { value: "90", label: "90 derniers jours" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function computeDateFrom(dateFilter: string): string | undefined {
  if (dateFilter === "all") return undefined;
  const days = parseInt(dateFilter, 10);
  if (isNaN(days)) return undefined;
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

function formatRelativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "Aujourd'hui";
  if (days === 1) return "Hier";
  if (days < 30) return `Il y a ${days}j`;
  const months = Math.floor(days / 30);
  return `Il y a ${months} mois`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UnansweredTab() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [selectedQuestionId, setSelectedQuestionId] = useState<string | null>(
    null,
  );
  const [rejectQuestionId, setRejectQuestionId] = useState<string | null>(null);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilter, dateFilter]);

  const queryParams = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      status: statusFilter !== "all" ? statusFilter : undefined,
      date_from: computeDateFrom(dateFilter),
    }),
    [page, statusFilter, dateFilter],
  );

  const { data: statsData, isLoading: statsLoading } = useLearningStats();
  const { data, isLoading, isError, refetch } =
    useLearningQuestions(queryParams);
  const approveMutation = useApproveQuestion();

  const questions = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  function handleInlineApprove(id: string, hasProposal: boolean) {
    if (!hasProposal) return;
    approveMutation.mutate(
      { questionId: id, data: {} },
      {
        onSuccess: () => toast.success("Question validée"),
        onError: () => toast.error("Erreur lors de la validation"),
      },
    );
  }

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------

  if (isError) {
    return (
      <div className="space-y-4">
        <LearningKPI stats={statsData} isLoading={statsLoading} />
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
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-4">
      {/* KPI Cards */}
      <LearningKPI stats={statsData} isLoading={statsLoading} />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={dateFilter} onValueChange={setDateFilter}>
          <SelectTrigger className="w-full sm:w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DATE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
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
              <TableHead className="text-start hidden lg:table-cell w-[100px]">
                Date
              </TableHead>
              <TableHead className="text-end w-[120px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Chargement...</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : questions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  <p className="text-muted-foreground">
                    Aucune question non couverte
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              questions.map((q) => {
                const status = statusConfig[q.status];
                return (
                  <TableRow
                    key={q.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setSelectedQuestionId(q.id)}
                  >
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
                    <TableCell className="hidden lg:table-cell">
                      <span className="text-sm text-muted-foreground">
                        {formatRelativeDate(q.created_at)}
                      </span>
                    </TableCell>
                    <TableCell className="text-end">
                      <div
                        className="flex items-center justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-[hsl(var(--success))] hover:text-[hsl(var(--success))] hover:bg-[hsl(var(--success))]/10"
                          onClick={() =>
                            handleInlineApprove(q.id, !!q.proposed_answer)
                          }
                          disabled={
                            !q.proposed_answer || approveMutation.isPending
                          }
                        >
                          <CheckCircle className="h-4 w-4" />
                          <span className="sr-only">Valider</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                          onClick={() => setRejectQuestionId(q.id)}
                          disabled={approveMutation.isPending}
                        >
                          <X className="h-4 w-4" />
                          <span className="sr-only">Rejeter</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-primary hover:text-primary hover:bg-primary/10"
                          onClick={() => setSelectedQuestionId(q.id)}
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

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {total} question{total !== 1 ? "s" : ""}
        </p>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Précédent
            </Button>
            <span className="text-sm text-muted-foreground">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Suivant
            </Button>
          </div>
        )}
      </div>

      {/* Detail Sheet */}
      <QuestionDetailSheet
        questionId={selectedQuestionId}
        open={!!selectedQuestionId}
        onOpenChange={(open) => {
          if (!open) setSelectedQuestionId(null);
        }}
        onReject={(id) => {
          setSelectedQuestionId(null);
          setRejectQuestionId(id);
        }}
      />

      {/* Reject Dialog */}
      <RejectDialog
        questionId={rejectQuestionId}
        open={!!rejectQuestionId}
        onOpenChange={(open) => {
          if (!open) setRejectQuestionId(null);
        }}
      />
    </div>
  );
}
