"use client";

import { useEffect, useState } from "react";
import {
  Search,
  MoreHorizontal,
  Eye,
  RefreshCw,
  Trash2,
  Loader2,
  AlertCircle,
  Download,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
  useDocuments,
  useDocumentCategories,
  useDeleteDocument,
  useReindexDocument,
  useValidateDocument,
} from "@/hooks/use-documents";
import type { KBDocumentStatus } from "@/types/kb";
import type { KBDocument } from "@/types/kb";
import { useApiClient } from "@/hooks/use-auth";

const statusConfig: Record<
  KBDocumentStatus,
  { label: string; className: string }
> = {
  pending: {
    label: "En attente",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  pending_validation: {
    label: "À valider",
    className: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  indexing: {
    label: "En cours",
    className:
      "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  indexed: {
    label: "Indexé",
    className:
      "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  rejected: {
    label: "Refusé",
    className: "bg-destructive/10 text-destructive border-0",
  },
  expired: {
    label: "Expiré",
    className: "bg-destructive/10 text-destructive border-0",
  },
  error: {
    label: "Erreur",
    className: "bg-destructive/10 text-destructive border-0",
  },
};

const languageLabels: Record<string, string> = {
  fr: "FR",
  ar: "AR",
  en: "EN",
};

const safeIngestionMessages = new Set([
  "La génération des représentations a échoué. Vérifiez le service d’IA et réessayez.",
  "Le découpage du document a échoué. Vérifiez son contenu et réessayez.",
  "Un document au contenu identique est déjà indexé.",
  "Le traitement a dépassé le délai prévu. Réessayez.",
  "Impossible de placer le document en file de traitement. Réessayez.",
  "Le traitement a échoué. Consultez les journaux du service.",
]);

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

function safeSourceUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function DocumentTable() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [selectedDocument, setSelectedDocument] = useState<KBDocument | null>(null);
  const [downloading, setDownloading] = useState(false);
  const api = useApiClient();
  const { data: categories = [] } = useDocumentCategories();

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isError, refetch } = useDocuments({
    page,
    page_size: 20,
    status: statusFilter !== "all" ? (statusFilter as KBDocumentStatus) : undefined,
    category: categoryFilter !== "all" ? categoryFilter.slice(4) : undefined,
    search: debouncedSearch || undefined,
  });

  const deleteDoc = useDeleteDocument();
  const reindexDoc = useReindexDocument();
  const validateDoc = useValidateDocument();

  const documents = data?.items ?? [];
  const total = data?.total ?? 0;

  const filtered = documents;

  function handleDelete(id: string, title: string) {
    deleteDoc.mutate(id, {
      onSuccess: () => toast.success(`Document "${title}" supprimé`),
      onError: () => toast.error("Erreur lors de la suppression"),
    });
  }

  function handleReindex(id: string, title: string) {
    reindexDoc.mutate(id, {
      onSuccess: () => toast.success(`Réindexation de "${title}" lancée`),
      onError: () => toast.error("Erreur lors de la réindexation"),
    });
  }

  function handleValidate(doc: (typeof documents)[number]) {
    if (!doc.source_authority?.trim() || !doc.source_reference?.trim() || !doc.source_version?.trim()) {
      toast.error("Renseignez l'autorité, la référence et la version. La date de publication est facultative si elle est inconnue.");
      return;
    }
    if (doc.source_url?.trim() && !safeSourceUrl(doc.source_url.trim())) {
      toast.error("Indiquez une URL de source HTTP ou HTTPS valide.");
      return;
    }
    validateDoc.mutate(doc, {
      onSuccess: () => { toast.success(`Document "${doc.title}" validé et envoyé à l'indexation`); setSelectedDocument(null); },
      onError: () => toast.error("Les métadonnées de preuve sont incomplètes"),
    });
  }

  async function downloadDocument(doc: KBDocument) {
    setDownloading(true);
    try {
      const file = await api.download(`/kb/documents/${doc.id}/file`);
      const objectUrl = URL.createObjectURL(file);
      const extension = doc.file_path?.match(/\.(pdf|docx|txt|md|csv)$/i)?.[0] || "";
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `document-${doc.id}${extension}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch {
      toast.error("Téléchargement impossible", { description: "Vérifiez la disponibilité du fichier et du contrôle antivirus." });
    } finally {
      setDownloading(false);
    }
  }

  function updateEvidence(
    field: "source_authority" | "source_reference" | "source_version" | "source_url" | "published_at" | "expires_at",
    value: string,
  ) {
    setSelectedDocument((doc) => doc ? { ...doc, [field]: value || null } : null);
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger les documents
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
      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher un document..."
            value={search}
            maxLength={200}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="ps-9"
          />
        </div>
        <Select
          value={categoryFilter}
          onValueChange={(v) => {
            setCategoryFilter(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-full sm:w-[180px]">
            <SelectValue placeholder="Catégorie" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Toutes catégories</SelectItem>
            {categories.map((cat) => (
              <SelectItem key={cat} value={`cat:${cat}`}>
                {cat}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
        >
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
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Chargement...</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : filtered.length === 0 ? (
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
                          status.className,
                        )}
                      >
                        {doc.status === "indexing" && (
                          <Loader2 className="h-3 w-3 me-1 animate-spin" />
                        )}
                        {status.label}
                      </Badge>
                      {(doc.status === "pending" || doc.status === "indexing") && (
                        <p className="mt-1 text-xs text-muted-foreground">Mis à jour {formatRelativeDate(doc.updated_at).toLowerCase()}</p>
                      )}
                      {doc.status === "error" && (
                        <p className="mt-1 max-w-xs text-xs text-destructive">
                          {doc.error_message && safeIngestionMessages.has(doc.error_message)
                            ? doc.error_message
                            : "Le traitement a échoué. Consultez les journaux du service."}
                        </p>
                      )}
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
                          <DropdownMenuItem onClick={() => setSelectedDocument(doc)}>
                            <Eye className="h-4 w-4 me-2" />
                            Voir
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => setSelectedDocument(doc)}
                            disabled={doc.status !== "pending_validation" || validateDoc.isPending}
                          >
                            Valider et indexer
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => handleReindex(doc.id, doc.title)}
                            disabled={reindexDoc.isPending}
                          >
                            <RefreshCw className="h-4 w-4 me-2" />
                            Réindexer
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() => handleDelete(doc.id, doc.title)}
                            disabled={deleteDoc.isPending}
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
          {filtered.length} document{filtered.length !== 1 ? "s" : ""} sur{" "}
          {total}
        </p>
        {total > 20 && (
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
              Page {page} / {Math.ceil(total / 20)}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= Math.ceil(total / 20)}
              onClick={() => setPage((p) => p + 1)}
            >
              Suivant
            </Button>
          </div>
        )}
      </div>

      <Dialog open={selectedDocument !== null} onOpenChange={(open) => { if (!open) setSelectedDocument(null); }}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{selectedDocument?.title || "Document"}</DialogTitle>
            <DialogDescription>Consultez le fichier et vérifiez les informations de source avant validation.</DialogDescription>
          </DialogHeader>
          {selectedDocument && (
            <div className="space-y-4 text-sm">
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {[
                  ["Catégorie", selectedDocument.category],
                  ["Langue", languageLabels[selectedDocument.language] ?? selectedDocument.language],
                  ["Statut", statusConfig[selectedDocument.status].label],
                ].map(([label, value]) => (
                  <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="break-words">{value || "—"}</dd></div>
                ))}
              </dl>
              {selectedDocument.status === "pending_validation" ? (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {([
                    ["source_authority", "Autorité source", "text", 300],
                    ["source_reference", "Référence", "text", 500],
                    ["source_version", "Version", "text", 100],
                    ["published_at", "Date de publication (si connue)", "date", undefined],
                    ["expires_at", "Date d'expiration", "date", undefined],
                    ["source_url", "URL de la source", "url", 1000],
                  ] as const).map(([field, label, type, maxLength]) => (
                    <div key={field} className="space-y-1">
                      <label htmlFor={`evidence-${field}`} className="text-muted-foreground">{label}</label>
                      <Input id={`evidence-${field}`} type={type} maxLength={maxLength}
                        value={selectedDocument[field] || ""}
                        onChange={(event) => updateEvidence(field, event.target.value)} />
                    </div>
                  ))}
                </div>
              ) : (
                <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {[
                    ["Autorité source", selectedDocument.source_authority],
                    ["Référence", selectedDocument.source_reference],
                    ["Version", selectedDocument.source_version],
                    ["Date de publication", selectedDocument.published_at],
                    ["Date d'expiration", selectedDocument.expires_at],
                  ].map(([label, value]) => (
                    <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="break-words">{value || "—"}</dd></div>
                  ))}
                </dl>
              )}
              <div>
                <span className="text-muted-foreground">Source en ligne : </span>
                {safeSourceUrl(selectedDocument.source_url) ? (
                  <a className="break-all underline" href={safeSourceUrl(selectedDocument.source_url) || undefined} target="_blank" rel="noopener noreferrer">{selectedDocument.source_url}</a>
                ) : <span>—</span>}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => downloadDocument(selectedDocument)} disabled={!selectedDocument.file_path || downloading}>
                  <Download className="me-2 h-4 w-4" />{downloading ? "Vérification…" : "Télécharger le fichier"}
                </Button>
                {selectedDocument.status === "pending_validation" && (
                  <Button onClick={() => handleValidate(selectedDocument)} disabled={validateDoc.isPending}>
                    {validateDoc.isPending ? "Validation…" : "Valider et indexer"}
                  </Button>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
