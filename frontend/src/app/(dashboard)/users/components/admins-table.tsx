"use client";

import { useState } from "react";
import {
  Search,
  MoreHorizontal,
  Loader2,
  AlertCircle,
  RefreshCw,
  UserX,
  UserCheck,
  ShieldCheck,
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
  useAdmins,
  useUpdateAdmin,
  useDeactivateAdmin,
} from "@/hooks/use-users";
import { RoleBadge } from "./role-badge";
import type { Admin, AdminRole } from "@/types";

const PAGE_SIZE = 10;
const MAX_ADMINS = 10;

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
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

const ASSIGNABLE_ROLES: { value: AdminRole; label: string }[] = [
  { value: "admin_tenant", label: "Admin Tenant" },
  { value: "supervisor", label: "Superviseur" },
  { value: "viewer", label: "Analyste" },
];

export function AdminsTable() {
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [page, setPage] = useState(1);

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

  const { data, isLoading, isError, refetch } = useAdmins({
    page,
    page_size: PAGE_SIZE,
    search: searchDebounced || undefined,
    is_active: statusFilter === "all" ? undefined : statusFilter === "active",
  });

  const updateAdmin = useUpdateAdmin();
  const deactivateAdmin = useDeactivateAdmin();

  const admins = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  function handleRoleChange(admin: Admin, newRole: AdminRole) {
    updateAdmin.mutate(
      { id: admin.id, data: { role: newRole } },
      {
        onSuccess: () =>
          toast.success("Rôle mis à jour", {
            description: `${admin.full_name} est maintenant ${newRole}`,
          }),
        onError: (error) =>
          toast.error("Erreur", {
            description:
              error instanceof Error ? error.message : "Impossible de modifier le rôle",
          }),
      }
    );
  }

  function handleToggleActive(admin: Admin) {
    if (admin.is_active) {
      // Deactivate
      deactivateAdmin.mutate(admin.id, {
        onSuccess: () =>
          toast.success("Administrateur désactivé", {
            description: `${admin.full_name} a été désactivé`,
          }),
        onError: (error) =>
          toast.error("Erreur", {
            description:
              error instanceof Error
                ? error.message
                : "Impossible de désactiver le compte",
          }),
      });
    } else {
      // Reactivate
      updateAdmin.mutate(
        { id: admin.id, data: { is_active: true } },
        {
          onSuccess: () =>
            toast.success("Administrateur réactivé", {
              description: `${admin.full_name} a été réactivé`,
            }),
          onError: (error) =>
            toast.error("Erreur", {
              description:
                error instanceof Error
                  ? error.message
                  : "Impossible de réactiver le compte",
            }),
        }
      );
    }
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger les administrateurs
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
      {/* Counter + Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher par nom ou email..."
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

      {/* Admin count */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <ShieldCheck className="h-4 w-4" strokeWidth={1.75} />
        <span>
          {total} / {MAX_ADMINS} administrateur{total !== 1 ? "s" : ""}
        </span>
        {total >= MAX_ADMINS && (
          <Badge variant="outline" className="text-xs bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0">
            Limite atteinte
          </Badge>
        )}
      </div>

      {/* Table */}
      <div className="rounded-lg border bg-card shadow-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-start">Administrateur</TableHead>
              <TableHead className="text-start hidden sm:table-cell">
                Rôle
              </TableHead>
              <TableHead className="text-start hidden md:table-cell">
                Statut
              </TableHead>
              <TableHead className="text-start hidden lg:table-cell">
                Dernière connexion
              </TableHead>
              <TableHead className="text-end w-[50px]">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Chargement...</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : admins.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center">
                  <p className="text-muted-foreground">
                    Aucun administrateur trouvé
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              admins.map((admin) => (
                <TableRow key={admin.id} className="hover:bg-muted/50">
                  <TableCell>
                    <div className="font-medium">
                      {admin.full_name || "—"}
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {admin.email}
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <RoleBadge role={admin.role} />
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    {admin.is_active ? (
                      <Badge className="bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0 text-xs font-medium">
                        Actif
                      </Badge>
                    ) : (
                      <Badge className="bg-muted text-muted-foreground border-0 text-xs font-medium">
                        Inactif
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell text-muted-foreground text-sm">
                    {admin.last_login
                      ? formatRelativeDate(admin.last_login)
                      : "Jamais"}
                  </TableCell>
                  <TableCell className="text-end">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreHorizontal className="h-4 w-4" />
                          <span className="sr-only">Actions</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {/* Role change sub-items */}
                        {ASSIGNABLE_ROLES.filter(
                          (r) => r.value !== admin.role
                        ).map((r) => (
                          <DropdownMenuItem
                            key={r.value}
                            onClick={() => handleRoleChange(admin, r.value)}
                            disabled={updateAdmin.isPending}
                          >
                            <ShieldCheck className="h-4 w-4 me-2" />
                            Passer en {r.label}
                          </DropdownMenuItem>
                        ))}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className={
                            admin.is_active
                              ? "text-destructive focus:text-destructive"
                              : ""
                          }
                          onClick={() => handleToggleActive(admin)}
                          disabled={
                            deactivateAdmin.isPending || updateAdmin.isPending
                          }
                        >
                          {admin.is_active ? (
                            <>
                              <UserX className="h-4 w-4 me-2" />
                              Désactiver
                            </>
                          ) : (
                            <>
                              <UserCheck className="h-4 w-4 me-2" />
                              Réactiver
                            </>
                          )}
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
          {admins.length} résultat{admins.length !== 1 ? "s" : ""} sur {total}
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
  );
}
