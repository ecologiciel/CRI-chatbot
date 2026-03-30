"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useAnalyticsTopQuestions } from "@/hooks/use-analytics";

const PAGE_SIZE = 10;

function TableSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="h-5 w-56 bg-muted animate-pulse rounded" />
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div className="h-10 bg-muted/50 animate-pulse rounded" />
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 bg-muted/30 animate-pulse rounded" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

interface TopQuestionsTableProps {
  period: string;
  start?: string;
  end?: string;
}

export function TopQuestionsTable({
  period,
  start,
  end,
}: TopQuestionsTableProps) {
  const [page, setPage] = useState(0);

  const { data, isLoading } = useAnalyticsTopQuestions(
    period,
    start,
    end,
    50,
  );

  if (isLoading) return <TableSkeleton />;
  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-heading">
            Questions les plus fréquentes
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-8">
            Aucune question pour cette période.
          </p>
        </CardContent>
      </Card>
    );
  }

  const totalPages = Math.ceil(data.length / PAGE_SIZE);
  const pageData = data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base font-heading">
          Questions les plus fréquentes
        </CardTitle>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs text-muted-foreground">
              {page + 1} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              <TableHead className="w-12 text-xs uppercase">#</TableHead>
              <TableHead className="text-xs uppercase">Question</TableHead>
              <TableHead className="w-24 text-xs uppercase text-center">
                Fréquence
              </TableHead>
              <TableHead className="w-32 text-xs uppercase">
                Confiance
              </TableHead>
              <TableHead className="w-28 text-xs uppercase text-center">
                Statut
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageData.map((q, i) => (
              <TableRow key={i} className="hover:bg-muted/30">
                <TableCell className="text-sm text-muted-foreground">
                  {page * PAGE_SIZE + i + 1}
                </TableCell>
                <TableCell className="text-sm max-w-[400px] truncate">
                  {q.question}
                </TableCell>
                <TableCell className="text-sm text-center font-medium">
                  {q.count}
                </TableCell>
                <TableCell>
                  <Progress
                    value={q.avg_confidence * 100}
                    className="h-2 [&>div]:bg-primary"
                  />
                </TableCell>
                <TableCell className="text-center">
                  <Badge
                    variant={
                      q.status === "covered" ? "default" : "secondary"
                    }
                    className={
                      q.status === "covered"
                        ? "bg-success/10 text-success border-success/20"
                        : "bg-warning/10 text-warning border-warning/20"
                    }
                  >
                    {q.status === "covered" ? "Couverte" : "Non couverte"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
