"use client";

import * as React from "react";
import { ChevronDown, ChevronUp, Search, Filter } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
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
import { useAuditLogs, useTenants } from "@/hooks/use-super-admin";
import { AUDIT_ACTIONS } from "@/types/super-admin";
import type { AuditLogFilters, AuditLogEntry } from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Expandable JSON details
// ---------------------------------------------------------------------------

function DetailsCell({ details }: { details: Record<string, unknown> | null }) {
  const [expanded, setExpanded] = React.useState(false);

  if (!details || Object.keys(details).length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-xs text-primary hover:underline"
      >
        {expanded ? (
          <ChevronUp className="h-3 w-3" />
        ) : (
          <ChevronDown className="h-3 w-3" />
        )}
        {expanded ? "Masquer" : "Détails"}
      </button>
      {expanded && (
        <pre className="mt-2 text-[11px] font-mono bg-muted p-2 rounded-md overflow-x-auto max-w-[300px]">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AuditTable
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

export function AuditTable() {
  const [filters, setFilters] = React.useState<AuditLogFilters>({
    page: 1,
    page_size: PAGE_SIZE,
  });

  const { data: tenantsData } = useTenants();
  const { data, isLoading } = useAuditLogs(filters);

  function updateFilter(key: keyof AuditLogFilters, value: string | undefined) {
    setFilters((prev) => ({
      ...prev,
      [key]: value || undefined,
      page: 1, // reset page on filter change
    }));
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div className="space-y-4">
      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Filter className="h-4 w-4" />
              <span className="font-medium">Filtres</span>
            </div>

            {/* Tenant filter */}
            <div className="space-y-1">
              <Label className="text-xs">Tenant</Label>
              <Select
                value={filters.tenant_slug ?? "all"}
                onValueChange={(v) =>
                  updateFilter("tenant_slug", v === "all" ? undefined : v)
                }
              >
                <SelectTrigger className="w-[180px] h-9">
                  <SelectValue placeholder="Tous les tenants" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tous les tenants</SelectItem>
                  {tenantsData?.map((t) => (
                    <SelectItem key={t.slug} value={t.slug}>
                      {t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* User filter */}
            <div className="space-y-1">
              <Label className="text-xs">Utilisateur</Label>
              <div className="relative">
                <Search className="absolute start-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Email ou ID"
                  className="w-[160px] h-9 ps-8 text-sm"
                  value={filters.user_id ?? ""}
                  onChange={(e) => updateFilter("user_id", e.target.value || undefined)}
                />
              </div>
            </div>

            {/* Action filter */}
            <div className="space-y-1">
              <Label className="text-xs">Action</Label>
              <Select
                value={filters.action ?? "all"}
                onValueChange={(v) =>
                  updateFilter("action", v === "all" ? undefined : v)
                }
              >
                <SelectTrigger className="w-[140px] h-9">
                  <SelectValue placeholder="Toutes" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Toutes</SelectItem>
                  {AUDIT_ACTIONS.map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Date from */}
            <div className="space-y-1">
              <Label className="text-xs">Du</Label>
              <Input
                type="date"
                className="w-[140px] h-9 text-sm"
                value={filters.date_from ?? ""}
                onChange={(e) => updateFilter("date_from", e.target.value || undefined)}
              />
            </div>

            {/* Date to */}
            <div className="space-y-1">
              <Label className="text-xs">Au</Label>
              <Input
                type="date"
                className="w-[140px] h-9 text-sm"
                value={filters.date_to ?? ""}
                onChange={(e) => updateFilter("date_to", e.target.value || undefined)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-0 divide-y">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 p-4">
                  <div className="h-4 w-28 bg-muted animate-pulse rounded" />
                  <div className="h-4 w-16 bg-muted animate-pulse rounded" />
                  <div className="h-4 w-24 bg-muted animate-pulse rounded hidden sm:block" />
                  <div className="h-4 w-16 bg-muted animate-pulse rounded hidden md:block" />
                  <div className="h-4 w-20 bg-muted animate-pulse rounded hidden lg:block" />
                  <div className="ms-auto h-4 w-12 bg-muted animate-pulse rounded" />
                </div>
              ))}
            </div>
          ) : !data || data.items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <p className="text-muted-foreground text-sm">
                Aucun log d&apos;audit trouvé pour ces critères.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Tenant</TableHead>
                  <TableHead className="hidden sm:table-cell">Utilisateur</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead className="hidden md:table-cell">Ressource</TableHead>
                  <TableHead className="hidden lg:table-cell">IP</TableHead>
                  <TableHead className="hidden xl:table-cell">Détails</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((log: AuditLogEntry) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-xs whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString("fr-FR", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px] font-mono">
                        {log.tenant_slug}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell text-sm">
                      {log.user_id ?? (
                        <span className="text-muted-foreground italic">system</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className="text-[10px]"
                      >
                        {log.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-xs text-muted-foreground">
                      {log.resource_type}
                      {log.resource_id && (
                        <span className="font-mono ms-1">#{log.resource_id.slice(0, 8)}</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-xs font-mono text-muted-foreground">
                      {log.ip_address ?? "—"}
                    </TableCell>
                    <TableCell className="hidden xl:table-cell">
                      <DetailsCell details={log.details} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {data.total.toLocaleString("fr-FR")} résultats — Page{" "}
            {filters.page ?? 1} / {totalPages}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={(filters.page ?? 1) <= 1}
              onClick={() =>
                setFilters((prev) => ({ ...prev, page: (prev.page ?? 1) - 1 }))
              }
            >
              Précédent
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={(filters.page ?? 1) >= totalPages}
              onClick={() =>
                setFilters((prev) => ({ ...prev, page: (prev.page ?? 1) + 1 }))
              }
            >
              Suivant
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
