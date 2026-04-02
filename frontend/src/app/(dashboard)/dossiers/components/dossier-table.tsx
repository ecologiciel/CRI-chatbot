"use client";

import { useState } from "react";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import {
  Search,
  MoreHorizontal,
  Eye,
  History,
  Loader2,
  AlertCircle,
  RefreshCw,
  CalendarIcon,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { useDossiers } from "@/hooks/use-dossiers";
import type { DossierStatut } from "@/types/dossier";
import { STATUT_CONFIG } from "@/types/dossier";
import { DossierDetailSheet } from "./dossier-detail-sheet";

// ---------------------------------------------------------------------------
// Relative date formatting
// ---------------------------------------------------------------------------

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return "À l'instant";
  if (diffMins < 60) return `Il y a ${diffMins} min`;
  if (diffHours < 24) return `Il y a ${diffHours}h`;
  if (diffDays < 7) return `Il y a ${diffDays}j`;
  return format(date, "dd/MM/yyyy", { locale: fr });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DossierTable() {
  // Filters
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [debounceTimer, setDebounceTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  const [statutFilter, setStatutFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState<Date | undefined>();
  const [dateTo, setDateTo] = useState<Date | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  // Detail sheet
  const [selectedDossierId, setSelectedDossierId] = useState<string | null>(null);

  // Search debounce
  function handleSearchChange(value: string) {
    setSearch(value);
    if (debounceTimer) clearTimeout(debounceTimer);
    const timer = setTimeout(() => {
      setSearchDebounced(value);
      setPage(1);
    }, 300);
    setDebounceTimer(timer);
  }

  // Data fetching
  const { data, isLoading, isError, refetch } = useDossiers({
    page,
    page_size: pageSize,
    statut: statutFilter !== "all" ? (statutFilter as DossierStatut) : undefined,
    search: searchDebounced || undefined,
    date_depot_from: dateFrom ? format(dateFrom, "yyyy-MM-dd") : undefined,
    date_depot_to: dateTo ? format(dateTo, "yyyy-MM-dd") : undefined,
  });

  const dossiers = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / pageSize);

  const hasFilters =
    searchDebounced || statutFilter !== "all" || dateFrom || dateTo;

  function resetFilters() {
    setSearch("");
    setSearchDebounced("");
    setStatutFilter("all");
    setDateFrom(undefined);
    setDateTo(undefined);
    setPage(1);
  }

  // Error state
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger les dossiers
        </p>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 me-2" />
          Réessayer
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {/* Filters */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:flex-wrap">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Rechercher par N° ou raison sociale..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="ps-9"
            />
          </div>

          {/* Statut filter */}
          <Select
            value={statutFilter}
            onValueChange={(v) => {
              setStatutFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-full sm:w-[160px]">
              <SelectValue placeholder="Statut" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous statuts</SelectItem>
              {Object.entries(STATUT_CONFIG).map(([key, cfg]) => (
                <SelectItem key={key} value={key}>
                  {cfg.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Date from */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className={cn(
                  "w-full sm:w-[150px] justify-start text-start font-normal",
                  !dateFrom && "text-muted-foreground",
                )}
              >
                <CalendarIcon className="h-4 w-4 me-2 shrink-0" />
                {dateFrom ? format(dateFrom, "dd/MM/yyyy") : "Date début"}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={dateFrom}
                onSelect={(d) => {
                  setDateFrom(d ?? undefined);
                  setPage(1);
                }}
                locale={fr}
              />
            </PopoverContent>
          </Popover>

          {/* Date to */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className={cn(
                  "w-full sm:w-[150px] justify-start text-start font-normal",
                  !dateTo && "text-muted-foreground",
                )}
              >
                <CalendarIcon className="h-4 w-4 me-2 shrink-0" />
                {dateTo ? format(dateTo, "dd/MM/yyyy") : "Date fin"}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={dateTo}
                onSelect={(d) => {
                  setDateTo(d ?? undefined);
                  setPage(1);
                }}
                locale={fr}
              />
            </PopoverContent>
          </Popover>

          {/* Reset filters */}
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              <X className="h-4 w-4 me-1" />
              Réinitialiser
            </Button>
          )}
        </div>

        {/* Table */}
        <div className="rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-start">N° Dossier</TableHead>
                <TableHead className="text-start">Investisseur</TableHead>
                <TableHead className="text-start hidden sm:table-cell">Type projet</TableHead>
                <TableHead className="text-start hidden md:table-cell">Région</TableHead>
                <TableHead className="text-start">Statut</TableHead>
                <TableHead className="text-start hidden md:table-cell">Date dépôt</TableHead>
                <TableHead className="text-start hidden lg:table-cell">Dernière MAJ</TableHead>
                <TableHead className="text-end w-[50px]">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-24 text-center">
                    <div className="flex items-center justify-center gap-2 text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Chargement...</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : dossiers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-24 text-center">
                    <p className="text-muted-foreground">
                      {hasFilters
                        ? "Aucun dossier ne correspond aux filtres"
                        : "Aucun dossier importé"}
                    </p>
                  </TableCell>
                </TableRow>
              ) : (
                dossiers.map((dossier) => {
                  const cfg = STATUT_CONFIG[dossier.statut];
                  return (
                    <TableRow
                      key={dossier.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => setSelectedDossierId(dossier.id)}
                    >
                      <TableCell className="font-mono text-sm font-medium">
                        {dossier.numero}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium text-sm">
                          {dossier.raison_sociale || "—"}
                        </div>
                      </TableCell>
                      <TableCell className="hidden sm:table-cell text-sm text-muted-foreground">
                        {dossier.type_projet || "—"}
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                        {dossier.region || "—"}
                      </TableCell>
                      <TableCell>
                        <Badge className={cn("text-xs font-medium", cfg.className)}>
                          {cfg.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                        {dossier.date_depot
                          ? format(new Date(dossier.date_depot), "dd/MM/yyyy", { locale: fr })
                          : "—"}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-sm text-muted-foreground">
                        {dossier.updated_at
                          ? formatRelativeDate(dossier.updated_at)
                          : "—"}
                      </TableCell>
                      <TableCell className="text-end">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                              <span className="sr-only">Actions</span>
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedDossierId(dossier.id);
                              }}
                            >
                              <Eye className="h-4 w-4 me-2" />
                              Voir détail
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedDossierId(dossier.id);
                              }}
                            >
                              <History className="h-4 w-4 me-2" />
                              Historique
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
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
            {total > 0
              ? `${(page - 1) * pageSize + 1}-${Math.min(page * pageSize, total)} sur ${total.toLocaleString("fr-FR")}`
              : "0 dossier"}
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
      </div>

      {/* Detail sheet */}
      <DossierDetailSheet
        dossierId={selectedDossierId}
        open={!!selectedDossierId}
        onOpenChange={(open) => {
          if (!open) setSelectedDossierId(null);
        }}
      />
    </>
  );
}
