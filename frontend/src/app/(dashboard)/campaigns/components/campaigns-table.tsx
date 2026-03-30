"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Loader2,
  AlertCircle,
  RefreshCw,
  MoreHorizontal,
  Search,
  Eye,
  Play,
  Pause,
  RotateCw,
  Copy,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  useCampaigns,
  useLaunchCampaign,
  usePauseCampaign,
  useResumeCampaign,
} from "@/hooks/use-campaigns";
import type { Campaign, CampaignStatus } from "@/types/campaign";

// ---------------------------------------------------------------------------
// Status badge config
// ---------------------------------------------------------------------------

const statusConfig: Record<CampaignStatus, { label: string; className: string }> = {
  draft: {
    label: "Brouillon",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  scheduled: {
    label: "Planifiée",
    className: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-0",
  },
  sending: {
    label: "En cours",
    className: "bg-primary/10 text-primary border-0",
  },
  paused: {
    label: "En pause",
    className: "bg-muted text-muted-foreground border-0",
  },
  completed: {
    label: "Terminée",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  failed: {
    label: "Échouée",
    className: "bg-destructive/10 text-destructive border-0",
  },
};

// ---------------------------------------------------------------------------
// Relative date formatter
// ---------------------------------------------------------------------------

function formatRelativeDate(dateStr: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diff = now - date;
  const minutes = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);

  if (minutes < 1) return "À l'instant";
  if (minutes < 60) return `Il y a ${minutes} min`;
  if (hours < 24) return `Il y a ${hours}h`;
  if (days < 7) return `Il y a ${days}j`;
  return new Date(dateStr).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const statusFilterOptions: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tous les statuts" },
  { value: "draft", label: "Brouillon" },
  { value: "scheduled", label: "Planifiée" },
  { value: "sending", label: "En cours" },
  { value: "paused", label: "En pause" },
  { value: "completed", label: "Terminée" },
  { value: "failed", label: "Échouée" },
];

export function CampaignsTable() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");

  const launchCampaign = useLaunchCampaign();
  const pauseCampaign = usePauseCampaign();
  const resumeCampaign = useResumeCampaign();

  // Debounce search (300ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchDebounced(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isError, refetch } = useCampaigns({
    page,
    page_size: 20,
    status:
      statusFilter === "all"
        ? undefined
        : (statusFilter as CampaignStatus),
  });

  const campaigns = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Client-side name filter (backend doesn't have search param for campaigns)
  const filtered = searchDebounced
    ? campaigns.filter((c) =>
        c.name.toLowerCase().includes(searchDebounced.toLowerCase())
      )
    : campaigns;

  function handleStatusFilterChange(value: string) {
    setStatusFilter(value);
    setPage(1);
  }

  async function handleAction(
    action: "launch" | "pause" | "resume",
    campaign: Campaign
  ) {
    try {
      if (action === "launch") {
        await launchCampaign.mutateAsync(campaign.id);
        toast.success("Campagne lancée");
      } else if (action === "pause") {
        await pauseCampaign.mutateAsync(campaign.id);
        toast.success("Campagne mise en pause");
      } else {
        await resumeCampaign.mutateAsync(campaign.id);
        toast.success("Campagne reprise");
      }
    } catch {
      toast.error("Erreur lors de l'action");
    }
  }

  // Error state
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger les campagnes
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
          <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Rechercher une campagne…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="ps-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={handleStatusFilterChange}>
          <SelectTrigger className="w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {statusFilterOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-start">Nom</TableHead>
              <TableHead className="text-start hidden sm:table-cell">
                Template
              </TableHead>
              <TableHead className="text-start hidden md:table-cell">
                Audience
              </TableHead>
              <TableHead className="text-start">Statut</TableHead>
              <TableHead className="text-start hidden lg:table-cell">
                Envoyés / Lus
              </TableHead>
              <TableHead className="text-start hidden md:table-cell">
                Date
              </TableHead>
              <TableHead className="text-end w-12">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Chargement…</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  <p className="text-muted-foreground">
                    Aucune campagne trouvée
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((campaign) => {
                const status = statusConfig[campaign.status];
                return (
                  <TableRow
                    key={campaign.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => router.push(`/campaigns/${campaign.id}`)}
                  >
                    <TableCell>
                      <p className="font-medium text-sm">{campaign.name}</p>
                      {campaign.description && (
                        <p className="text-xs text-muted-foreground line-clamp-1">
                          {campaign.description}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <span className="text-sm">{campaign.template_name}</span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <span className="text-sm">
                        {campaign.audience_count.toLocaleString("fr-FR")}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={cn(
                          "text-xs font-medium",
                          status.className,
                          campaign.status === "sending" && "animate-pulse"
                        )}
                      >
                        {status.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <span className="text-sm">
                        {campaign.stats.sent.toLocaleString("fr-FR")} /{" "}
                        {campaign.stats.read.toLocaleString("fr-FR")}
                      </span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <span className="text-xs text-muted-foreground">
                        {formatRelativeDate(campaign.created_at)}
                      </span>
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
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              router.push(`/campaigns/${campaign.id}`);
                            }}
                          >
                            <Eye className="h-4 w-4 me-2" />
                            Voir
                          </DropdownMenuItem>
                          {campaign.status === "draft" && (
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAction("launch", campaign);
                              }}
                            >
                              <Play className="h-4 w-4 me-2" />
                              Lancer
                            </DropdownMenuItem>
                          )}
                          {campaign.status === "sending" && (
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAction("pause", campaign);
                              }}
                            >
                              <Pause className="h-4 w-4 me-2" />
                              Mettre en pause
                            </DropdownMenuItem>
                          )}
                          {campaign.status === "paused" && (
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAction("resume", campaign);
                              }}
                            >
                              <RotateCw className="h-4 w-4 me-2" />
                              Reprendre
                            </DropdownMenuItem>
                          )}
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
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            Page {page} / {totalPages} — {total} campagne
            {total > 1 ? "s" : ""}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Précédent
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Suivant
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
