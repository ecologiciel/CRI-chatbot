"use client";

import { useState } from "react";
import {
  Search,
  Plus,
  MoreHorizontal,
  Loader2,
  AlertCircle,
  RefreshCw,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Shield,
} from "lucide-react";
import { toast } from "sonner";
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  useWhitelistEntries,
  useUpdateWhitelistEntry,
  useDeleteWhitelistEntry,
} from "@/hooks/use-whitelist";
import { AddWhitelistDialog } from "./add-whitelist-dialog";
import type { WhitelistEntry } from "@/types/whitelist";

const PAGE_SIZE = 20;

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function WhitelistSection() {
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WhitelistEntry | null>(null);

  // Debounce search
  const [debounceTimer, setDebounceTimer] = useState<ReturnType<
    typeof setTimeout
  > | null>(null);
  function handleSearchChange(value: string) {
    setSearch(value);
    if (debounceTimer) clearTimeout(debounceTimer);
    const timer = setTimeout(() => {
      setSearchDebounced(value);
      setPage(1);
    }, 300);
    setDebounceTimer(timer);
  }

  const { data, isLoading, isError, refetch } = useWhitelistEntries({
    page,
    page_size: PAGE_SIZE,
    search: searchDebounced || undefined,
    is_active: statusFilter === "all" ? undefined : statusFilter === "active",
  });

  const updateEntry = useUpdateWhitelistEntry();
  const deleteEntry = useDeleteWhitelistEntry();

  const entries = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  function handleToggleActive(entry: WhitelistEntry) {
    const newActive = !entry.is_active;
    updateEntry.mutate(
      { id: entry.id, data: { is_active: newActive } },
      {
        onSuccess: () =>
          toast.success(
            newActive ? "Numéro activé" : "Numéro désactivé",
            { description: entry.phone }
          ),
        onError: (error) =>
          toast.error("Erreur", {
            description:
              error instanceof Error
                ? error.message
                : "Impossible de modifier le statut",
          }),
      }
    );
  }

  function confirmDelete() {
    if (!deleteTarget) return;
    deleteEntry.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success("Numéro supprimé", {
          description: `${deleteTarget.phone} a été retiré de la liste blanche`,
        });
        setDeleteTarget(null);
      },
      onError: (error) => {
        toast.error("Erreur", {
          description:
            error instanceof Error
              ? error.message
              : "Impossible de supprimer le numéro",
        });
        setDeleteTarget(null);
      },
    });
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger la liste blanche
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
        {/* Header */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-muted-foreground" strokeWidth={1.75} />
            <div>
              <h2 className="text-lg font-semibold font-heading">
                Agent Interne — Numéros autorisés
              </h2>
              <p className="text-xs text-muted-foreground">
                Les numéros ci-dessous peuvent accéder à l&apos;Agent 2 (lecture
                seule) via WhatsApp.
              </p>
            </div>
          </div>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 me-2" strokeWidth={1.75} />
            Ajouter un numéro
          </Button>
        </div>

        {/* Filters */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Rechercher par numéro ou libellé..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="ps-9"
            />
          </div>
          <Select
            value={statusFilter}
            onValueChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-full sm:w-[150px]">
              <SelectValue placeholder="Statut" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous statuts</SelectItem>
              <SelectItem value="active">Actif</SelectItem>
              <SelectItem value="inactive">Inactif</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Table */}
        <div className="rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-start">Téléphone</TableHead>
                <TableHead className="text-start hidden sm:table-cell">
                  Libellé
                </TableHead>
                <TableHead className="text-start hidden lg:table-cell">
                  Note
                </TableHead>
                <TableHead className="text-start hidden md:table-cell">
                  Statut
                </TableHead>
                <TableHead className="text-start hidden md:table-cell">
                  Date ajout
                </TableHead>
                <TableHead className="text-end w-[50px]">
                  <span className="sr-only">Actions</span>
                </TableHead>
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
              ) : entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-24 text-center">
                    <p className="text-muted-foreground">
                      Aucun numéro dans la liste blanche
                    </p>
                  </TableCell>
                </TableRow>
              ) : (
                entries.map((entry) => (
                  <TableRow key={entry.id} className="hover:bg-muted/50">
                    <TableCell>
                      <span className="font-mono text-sm">{entry.phone}</span>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell text-sm">
                      {entry.label || "—"}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-sm text-muted-foreground max-w-[200px] truncate">
                      {entry.note || "—"}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {entry.is_active ? (
                        <Badge className="bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0 text-xs font-medium">
                          Actif
                        </Badge>
                      ) : (
                        <Badge className="bg-muted text-muted-foreground border-0 text-xs font-medium">
                          Inactif
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-muted-foreground text-sm">
                      {formatDate(entry.created_at)}
                    </TableCell>
                    <TableCell className="text-end">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                          >
                            <MoreHorizontal className="h-4 w-4" />
                            <span className="sr-only">Actions</span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={() => handleToggleActive(entry)}
                            disabled={updateEntry.isPending}
                          >
                            {entry.is_active ? (
                              <>
                                <ToggleLeft className="h-4 w-4 me-2" />
                                Désactiver
                              </>
                            ) : (
                              <>
                                <ToggleRight className="h-4 w-4 me-2" />
                                Activer
                              </>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() => setDeleteTarget(entry)}
                          >
                            <Trash2 className="h-4 w-4 me-2" />
                            Supprimer
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {entries.length} numéro{entries.length !== 1 ? "s" : ""} sur {total}
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

      {/* Add dialog */}
      <AddWhitelistDialog open={addOpen} onOpenChange={setAddOpen} />

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open: boolean) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Supprimer ce numéro ?</AlertDialogTitle>
            <AlertDialogDescription>
              Le numéro{" "}
              <span className="font-mono font-medium">
                {deleteTarget?.phone}
              </span>{" "}
              sera définitivement retiré de la liste blanche. Cette action est
              irréversible.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteEntry.isPending && (
                <Loader2 className="h-4 w-4 me-2 animate-spin" />
              )}
              Supprimer
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
