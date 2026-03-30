"use client";

import { useEffect, useRef, useState } from "react";
import {
  Calendar,
  CheckCircle,
  Globe,
  Loader2,
  AlertCircle,
  Sparkles,
  Hash,
  UserCheck,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  useLearningQuestion,
  useGenerateProposal,
  useApproveQuestion,
} from "@/hooks/use-learning";
import type { UnansweredQuestionStatus } from "@/types/kb";

interface QuestionDetailSheetProps {
  questionId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReject: (questionId: string) => void;
}

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
  fr: "Français",
  ar: "Arabe",
  en: "Anglais",
};

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function QuestionDetailSheet({
  questionId,
  open,
  onOpenChange,
  onReject,
}: QuestionDetailSheetProps) {
  const { data: question, isLoading, isError } = useLearningQuestion(
    open ? questionId : null,
  );
  const generateMutation = useGenerateProposal();
  const approveMutation = useApproveQuestion();

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [answerText, setAnswerText] = useState("");

  // Sync textarea when question data loads or after AI generation
  const proposedAnswer = question?.proposed_answer ?? "";
  const updatedAt = question?.updated_at;
  useEffect(() => {
    setAnswerText(proposedAnswer);
  }, [proposedAnswer, updatedAt]);

  // Reset state when sheet closes
  useEffect(() => {
    if (!open) {
      setAnswerText("");
    }
  }, [open]);

  const isModified = answerText !== (question?.proposed_answer ?? "");
  const canApprove = answerText.trim().length > 0;
  const isPending = question?.status === "pending";
  const isTerminal =
    question?.status === "rejected" || question?.status === "injected";

  function handleGenerate() {
    if (!questionId) return;
    generateMutation.mutate(questionId, {
      onError: () => toast.error("Erreur lors de la génération"),
    });
  }

  function handleApprove() {
    if (!questionId) return;
    const data: { proposed_answer?: string } = {};
    if (isModified) {
      data.proposed_answer = answerText;
    }
    approveMutation.mutate(
      { questionId, data },
      {
        onSuccess: () => {
          toast.success("Question approuvée — réinjection en cours");
          onOpenChange(false);
        },
        onError: () => toast.error("Erreur lors de l'approbation"),
      },
    );
  }

  function handleEdit() {
    textareaRef.current?.focus();
    textareaRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  const status = question ? statusConfig[question.status] : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-[600px] overflow-y-auto"
      >
        <SheetHeader className="pb-4">
          <SheetTitle className="font-heading">
            Détail de la question
          </SheetTitle>
        </SheetHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : isError || !question ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <AlertCircle className="h-8 w-8 text-destructive mb-3" />
            <p className="text-sm text-muted-foreground">
              Impossible de charger la question
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Question text + badges */}
            <div className="space-y-3">
              <p className="font-heading font-semibold text-lg leading-relaxed">
                {question.question}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {status && (
                  <Badge className={cn("text-xs font-medium", status.className)}>
                    {status.label}
                  </Badge>
                )}
                <Badge variant="secondary" className="text-xs font-mono">
                  {languageLabels[question.language] ?? question.language}
                </Badge>
                <Badge variant="outline" className="text-xs font-mono">
                  {question.frequency}x
                </Badge>
              </div>
            </div>

            <Separator />

            {/* Metadata */}
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <Hash
                  className="h-4 w-4 text-muted-foreground shrink-0"
                  strokeWidth={1.75}
                />
                <span className="text-sm text-muted-foreground">Fréquence</span>
                <span className="text-sm font-medium ms-auto">
                  Posée {question.frequency} fois
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Globe
                  className="h-4 w-4 text-muted-foreground shrink-0"
                  strokeWidth={1.75}
                />
                <span className="text-sm text-muted-foreground">Langue</span>
                <span className="text-sm font-medium ms-auto">
                  {languageLabels[question.language] ?? question.language}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Calendar
                  className="h-4 w-4 text-muted-foreground shrink-0"
                  strokeWidth={1.75}
                />
                <span className="text-sm text-muted-foreground">Créée le</span>
                <span className="text-sm font-medium ms-auto">
                  {formatDate(question.created_at)}
                </span>
              </div>
            </div>

            <Separator />

            {/* AI Proposal */}
            <div className="space-y-3">
              <Label htmlFor="proposed-answer" className="text-sm font-medium">
                Réponse proposée par l&apos;IA
              </Label>
              <Textarea
                ref={textareaRef}
                id="proposed-answer"
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                placeholder="Aucune proposition générée..."
                rows={8}
                disabled={isTerminal}
                className="resize-y"
              />

              {/* Generate AI button */}
              {isPending && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleGenerate}
                  disabled={generateMutation.isPending}
                >
                  {generateMutation.isPending ? (
                    <Loader2 className="h-4 w-4 me-2 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4 me-2" strokeWidth={1.75} />
                  )}
                  Générer proposition IA
                </Button>
              )}
            </div>

            {/* Review history */}
            {question.reviewed_by && (
              <>
                <Separator />
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    <UserCheck
                      className="h-4 w-4 text-muted-foreground shrink-0"
                      strokeWidth={1.75}
                    />
                    <span className="text-sm text-muted-foreground">
                      Reviewé le{" "}
                      {question.updated_at
                        ? formatDate(question.updated_at)
                        : "—"}
                    </span>
                  </div>
                  {question.review_note && (
                    <p className="text-sm text-muted-foreground bg-muted/50 rounded-lg p-3">
                      {question.review_note}
                    </p>
                  )}
                </div>
              </>
            )}

            <Separator />

            {/* Action buttons */}
            {!isTerminal && (
              <div className="flex flex-wrap items-center gap-3 pt-2">
                <Button
                  className="bg-[hsl(var(--success))] text-white hover:bg-[hsl(var(--success))]/90"
                  onClick={handleApprove}
                  disabled={
                    !canApprove ||
                    approveMutation.isPending
                  }
                >
                  {approveMutation.isPending ? (
                    <Loader2 className="h-4 w-4 me-2 animate-spin" />
                  ) : (
                    <CheckCircle className="h-4 w-4 me-2" strokeWidth={1.75} />
                  )}
                  Valider
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => {
                    if (questionId) onReject(questionId);
                  }}
                >
                  Rejeter
                </Button>
                <Button variant="outline" onClick={handleEdit}>
                  Éditer
                </Button>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
