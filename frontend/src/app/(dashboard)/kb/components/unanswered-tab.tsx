"use client";

import { CheckCircle, X, Pencil } from "lucide-react";
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
import { mockUnansweredQuestions } from "@/lib/mock-data";
import type { UnansweredQuestionStatus } from "@/types/kb";

const statusConfig: Record<
  UnansweredQuestionStatus,
  { label: string; className: string }
> = {
  pending: {
    label: "En attente",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  ai_proposed: {
    label: "Proposition IA",
    className:
      "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  approved: {
    label: "Validée",
    className:
      "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  rejected: {
    label: "Rejetée",
    className: "bg-destructive/10 text-destructive border-0",
  },
  edited: {
    label: "Modifiée",
    className: "bg-primary/10 text-primary border-0",
  },
};

const languageLabels: Record<string, string> = {
  fr: "FR",
  ar: "AR",
  en: "EN",
};

export function UnansweredTab() {
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
            {mockUnansweredQuestions.map((q) => {
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
                        onClick={() =>
                          console.log("Approve:", q.id)
                        }
                      >
                        <CheckCircle className="h-4 w-4" />
                        <span className="sr-only">Valider</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                        onClick={() =>
                          console.log("Reject:", q.id)
                        }
                      >
                        <X className="h-4 w-4" />
                        <span className="sr-only">Rejeter</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-primary hover:text-primary hover:bg-primary/10"
                        onClick={() =>
                          console.log("Edit:", q.id)
                        }
                      >
                        <Pencil className="h-4 w-4" />
                        <span className="sr-only">Modifier</span>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">
        {mockUnansweredQuestions.length} question
        {mockUnansweredQuestions.length !== 1 ? "s" : ""} non couvertes
      </p>
    </div>
  );
}
