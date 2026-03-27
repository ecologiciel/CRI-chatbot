"use client";

import { useState } from "react";
import {
  Search,
  MoreHorizontal,
  Eye,
  Trash2,
  Loader2,
  AlertCircle,
  RefreshCw,
  Download,
} from "lucide-react";
import { toast } from "sonner";
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
import { useContacts, useDeleteContact } from "@/hooks/use-contacts";
import { useApiClient } from "@/hooks/use-auth";
import { ContactDetailSheet } from "./contact-detail-sheet";
import type { OptInStatus, ContactLanguage } from "@/types/contact";

const optInConfig: Record<OptInStatus, { label: string; className: string }> = {
  opted_in: {
    label: "Opt-in",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  opted_out: {
    label: "Opt-out",
    className: "bg-destructive/10 text-destructive border-0",
  },
  pending: {
    label: "En attente",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
};

const languageLabels: Record<string, string> = {
  fr: "FR",
  ar: "AR",
  en: "EN",
};

const sourceLabels: Record<string, string> = {
  whatsapp: "WhatsApp",
  import_csv: "Import",
  manual: "Manuel",
};

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

export function ContactTable() {
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [optInFilter, setOptInFilter] = useState<string>("all");
  const [languageFilter, setLanguageFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);
  const api = useApiClient();

  // Debounce search
  const [debounceTimer, setDebounceTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  function handleSearchChange(value: string) {
    setSearch(value);
    if (debounceTimer) clearTimeout(debounceTimer);
    const timer = setTimeout(() => {
      setSearchDebounced(value);
      setPage(1);
    }, 300);
    setDebounceTimer(timer);
  }

  const { data, isLoading, isError, refetch } = useContacts({
    page,
    page_size: 20,
    search: searchDebounced || undefined,
    opt_in_status: optInFilter !== "all" ? (optInFilter as OptInStatus) : undefined,
    language: languageFilter !== "all" ? (languageFilter as ContactLanguage) : undefined,
  });

  const deleteContact = useDeleteContact();

  const contacts = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 20);

  function handleDelete(id: string, name: string | null) {
    const displayName = name || "ce contact";
    deleteContact.mutate(id, {
      onSuccess: () => toast.success(`Contact "${displayName}" supprimé`),
      onError: () => toast.error("Erreur lors de la suppression"),
    });
  }

  async function handleExport() {
    try {
      // Direct download via window
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${baseUrl}/api/v1/contacts/export?format=csv`, {
        headers: {
          Authorization: `Bearer ${(api as any)._accessTokenRef?.current || ""}`,
          "X-Tenant-ID": (api as any)._tenantId || "",
        },
      });
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "contacts_export.csv";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export terminé");
    } catch {
      toast.error("Erreur lors de l'export");
    }
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger les contacts
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
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Rechercher par nom, téléphone, CIN..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="ps-9"
            />
          </div>
          <Select
            value={optInFilter}
            onValueChange={(v) => {
              setOptInFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-full sm:w-[160px]">
              <SelectValue placeholder="Opt-in" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous statuts</SelectItem>
              {Object.entries(optInConfig).map(([key, { label }]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={languageFilter}
            onValueChange={(v) => {
              setLanguageFilter(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-full sm:w-[140px]">
              <SelectValue placeholder="Langue" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Toutes langues</SelectItem>
              <SelectItem value="fr">Français</SelectItem>
              <SelectItem value="ar">Arabe</SelectItem>
              <SelectItem value="en">Anglais</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-4 w-4 me-2" />
            Exporter
          </Button>
        </div>

        {/* Table */}
        <div className="rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-start">Contact</TableHead>
                <TableHead className="text-start hidden sm:table-cell">Langue</TableHead>
                <TableHead className="text-start hidden md:table-cell">Opt-in</TableHead>
                <TableHead className="text-start hidden lg:table-cell">Tags</TableHead>
                <TableHead className="text-start hidden md:table-cell">Source</TableHead>
                <TableHead className="text-start hidden lg:table-cell">Date</TableHead>
                <TableHead className="text-end w-[50px]">
                  <span className="sr-only">Actions</span>
                </TableHead>
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
              ) : contacts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-24 text-center">
                    <p className="text-muted-foreground">Aucun contact trouvé</p>
                  </TableCell>
                </TableRow>
              ) : (
                contacts.map((contact) => {
                  const optIn = optInConfig[contact.opt_in_status];
                  return (
                    <TableRow
                      key={contact.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => setSelectedContactId(contact.id)}
                    >
                      <TableCell>
                        <div className="font-medium">
                          {contact.name || "—"}
                        </div>
                        <div className="text-xs text-muted-foreground font-mono mt-0.5">
                          {contact.phone}
                        </div>
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <Badge variant="secondary" className="text-xs font-mono">
                          {languageLabels[contact.language] ?? contact.language}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        <Badge className={cn("text-xs font-medium", optIn.className)}>
                          {optIn.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        <div className="flex flex-wrap gap-1">
                          {contact.tags.length > 0 ? (
                            contact.tags.slice(0, 3).map((tag) => (
                              <Badge
                                key={tag}
                                variant="outline"
                                className="text-xs"
                              >
                                {tag}
                              </Badge>
                            ))
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                          {contact.tags.length > 3 && (
                            <Badge variant="outline" className="text-xs">
                              +{contact.tags.length - 3}
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                        {sourceLabels[contact.source] ?? contact.source}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-muted-foreground text-sm">
                        {formatRelativeDate(contact.created_at)}
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
                                setSelectedContactId(contact.id);
                              }}
                            >
                              <Eye className="h-4 w-4 me-2" />
                              Voir
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDelete(contact.id, contact.name);
                              }}
                              disabled={deleteContact.isPending}
                            >
                              <Trash2 className="h-4 w-4 me-2" />
                              Supprimer
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

        {/* Pagination + Count */}
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {contacts.length} contact{contacts.length !== 1 ? "s" : ""} sur {total}
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
      <ContactDetailSheet
        contactId={selectedContactId}
        open={!!selectedContactId}
        onOpenChange={(open) => {
          if (!open) setSelectedContactId(null);
        }}
      />
    </>
  );
}
