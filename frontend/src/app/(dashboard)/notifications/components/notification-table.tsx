"use client";

import { useState } from "react";
import { Loader2, AlertCircle, RefreshCw } from "lucide-react";
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
import { Card } from "@/components/ui/card";
import { useNotificationHistory } from "@/hooks/use-notifications";
import { cn } from "@/lib/utils";
import type {
  NotificationStatus,
  NotificationEventType,
} from "@/types/notification";

// ---------------------------------------------------------------------------
// Badge configs
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<
  NotificationStatus,
  { label: string; className: string }
> = {
  sent: {
    label: "Envoyée",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  skipped: {
    label: "Ignorée",
    className:
      "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  failed: {
    label: "Échouée",
    className: "bg-destructive/10 text-destructive border-0",
  },
};

const EVENT_TYPE_CONFIG: Record<string, { label: string; className: string }> =
  {
    decision_finale: {
      label: "Décision finale",
      className: "bg-[#C4704B]/10 text-[#C4704B] border-0",
    },
    complement_request: {
      label: "Complément",
      className: "bg-[#C4944B]/10 text-[#C4944B] border-0",
    },
    status_update: {
      label: "Mise à jour",
      className: "bg-[#5B7A8B]/10 text-[#5B7A8B] border-0",
    },
    dossier_incomplet: {
      label: "Incomplet",
      className: "bg-[#B5544B]/10 text-[#B5544B] border-0",
    },
  };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NotificationTable() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("all");
  const pageSize = 20;

  const { data, isLoading, isError, refetch } = useNotificationHistory({
    page,
    page_size: pageSize,
    status:
      statusFilter !== "all"
        ? (statusFilter as NotificationStatus)
        : undefined,
    event_type:
      eventTypeFilter !== "all"
        ? (eventTypeFilter as NotificationEventType)
        : undefined,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <Card className="shadow-card">
      {/* Filters */}
      <div className="p-4 border-b">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Select
            value={statusFilter}
            onValueChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-full sm:w-[180px]">
              <SelectValue placeholder="Statut" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les statuts</SelectItem>
              <SelectItem value="sent">Envoyée</SelectItem>
              <SelectItem value="skipped">Ignorée</SelectItem>
              <SelectItem value="failed">Échouée</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={eventTypeFilter}
            onValueChange={(v) => {
              setEventTypeFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-full sm:w-[200px]">
              <SelectValue placeholder="Type d'événement" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les types</SelectItem>
              <SelectItem value="decision_finale">Décision finale</SelectItem>
              <SelectItem value="complement_request">Complément</SelectItem>
              <SelectItem value="status_update">Mise à jour</SelectItem>
              <SelectItem value="dossier_incomplet">Incomplet</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-start">Type</TableHead>
            <TableHead className="text-start">Statut</TableHead>
            <TableHead className="text-start hidden sm:table-cell">
              N° Dossier
            </TableHead>
            <TableHead className="text-start hidden md:table-cell">
              Template
            </TableHead>
            <TableHead className="text-start hidden lg:table-cell">
              Raison
            </TableHead>
            <TableHead className="text-start hidden sm:table-cell">
              Date
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={6} className="h-24 text-center">
                <div className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Chargement...</span>
                </div>
              </TableCell>
            </TableRow>
          ) : isError ? (
            <TableRow>
              <TableCell colSpan={6} className="h-24 text-center">
                <div className="flex flex-col items-center justify-center gap-2">
                  <AlertCircle className="h-5 w-5 text-destructive" />
                  <p className="text-sm text-muted-foreground">
                    Impossible de charger les notifications
                  </p>
                  <Button variant="outline" size="sm" onClick={() => refetch()}>
                    <RefreshCw className="h-3 w-3 me-1" />
                    Réessayer
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="h-24 text-center">
                <p className="text-muted-foreground">
                  Aucune notification trouvée
                </p>
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => {
              const evtConfig = item.event_type
                ? EVENT_TYPE_CONFIG[item.event_type]
                : null;
              const statusCfg = STATUS_CONFIG[item.status];

              return (
                <TableRow key={item.id}>
                  <TableCell>
                    {evtConfig ? (
                      <Badge
                        className={cn(
                          "text-xs font-medium",
                          evtConfig.className,
                        )}
                      >
                        {evtConfig.label}
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge
                      className={cn(
                        "text-xs font-medium",
                        statusCfg.className,
                      )}
                    >
                      {statusCfg.label}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    {item.dossier_numero ? (
                      <span className="text-sm font-mono">
                        {item.dossier_numero}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    {item.template_name ? (
                      <span className="text-sm">{item.template_name}</span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {item.reason ? (
                      <span className="text-sm text-muted-foreground">
                        {item.reason}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span className="text-sm text-muted-foreground">
                      {formatDate(item.created_at)}
                    </span>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      {/* Pagination */}
      <div className="flex items-center justify-between p-4 border-t">
        <p className="text-xs text-muted-foreground">
          {total} notification{total !== 1 ? "s" : ""}
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
              Page {page} / {totalPages}
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
    </Card>
  );
}
