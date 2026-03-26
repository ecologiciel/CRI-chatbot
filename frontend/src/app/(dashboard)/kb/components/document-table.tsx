"use client";

import { useState } from "react";
import {
  Search,
  MoreHorizontal,
  Eye,
  RefreshCw,
  Trash2,
  Loader2,
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
import { mockKBDocuments } from "@/lib/mock-data";
import type { KBDocumentStatus } from "@/types/kb";

const statusConfig: Record<
  KBDocumentStatus,
  { label: string; className: string }
> = {
  pending: {
    label: "En attente",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  processing: {
    label: "En cours",
    className:
      "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  indexed: {
    label: "Indexé",
    className:
      "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  failed: {
    label: "Échec",
    className: "bg-destructive/10 text-destructive border-0",
  },
  archived: {
    label: "Archivé",
    className: "bg-muted text-muted-foreground border-0",
  },
};

const languageLabels: Record<string, string> = {
  fr: "FR",
  ar: "AR",
  en: "EN",
};

const categories = ["Procédures", "Incitations", "Juridique", "Général"];

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / 1_048_576).toFixed(1)} Mo`;
}

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
  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
  });
}

export function DocumentTable() {
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filtered = mockKBDocuments.filter((doc) => {
    const matchesSearch = doc.title
      .toLowerCase()
      .includes(search.toLowerCase());
    const matchesCategory =
      categoryFilter === "all" || doc.category === categoryFilter;
    const matchesStatus =
      statusFilter === "all" || doc.status === statusFilter;
    return matchesSearch && matchesCategory && matchesStatus;
  });

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher un document..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="ps-9"
          />
        </div>
        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="w-full sm:w-[180px]">
            <SelectValue placeholder="Catégorie" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Toutes catégories</SelectItem>
            {categories.map((cat) => (
              <SelectItem key={cat} value={cat}>
                {cat}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-[160px]">
            <SelectValue placeholder="Statut" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tous statuts</SelectItem>
            {Object.entries(statusConfig).map(([key, { label }]) => (
              <SelectItem key={key} value={key}>
                {label}
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
              <TableHead className="text-start">Titre</TableHead>
              <TableHead className="text-start hidden md:table-cell">
                Catégorie
              </TableHead>
              <TableHead className="text-start hidden sm:table-cell">
                Langue
              </TableHead>
              <TableHead className="text-start hidden lg:table-cell">
                Chunks
              </TableHead>
              <TableHead className="text-start">Statut</TableHead>
              <TableHead className="text-start hidden md:table-cell">
                Date
              </TableHead>
              <TableHead className="text-end w-[50px]">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  <p className="text-muted-foreground">Aucun document trouvé</p>
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((doc) => {
                const status = statusConfig[doc.status];
                return (
                  <TableRow key={doc.id}>
                    <TableCell>
                      <div className="font-medium">{doc.title}</div>
                      <div className="text-xs text-muted-foreground mt-0.5 md:hidden">
                        {doc.category ?? "—"} · {formatFileSize(doc.file_size)}
                      </div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {doc.category ? (
                        <Badge variant="outline">{doc.category}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <Badge
                        variant="secondary"
                        className="text-xs font-mono"
                      >
                        {languageLabels[doc.language] ?? doc.language}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell font-mono text-muted-foreground">
                      {doc.chunk_count || "—"}
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={cn(
                          "text-xs font-medium",
                          status.className
                        )}
                      >
                        {doc.status === "processing" && (
                          <Loader2 className="h-3 w-3 me-1 animate-spin" />
                        )}
                        {status.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-muted-foreground text-sm">
                      {formatRelativeDate(doc.created_at)}
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
                          <DropdownMenuItem>
                            <Eye className="h-4 w-4 me-2" />
                            Voir
                          </DropdownMenuItem>
                          <DropdownMenuItem>
                            <RefreshCw className="h-4 w-4 me-2" />
                            Réindexer
                          </DropdownMenuItem>
                          <DropdownMenuItem className="text-destructive focus:text-destructive">
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

      {/* Count */}
      <p className="text-xs text-muted-foreground">
        {filtered.length} document{filtered.length !== 1 ? "s" : ""} sur{" "}
        {mockKBDocuments.length}
      </p>
    </div>
  );
}
