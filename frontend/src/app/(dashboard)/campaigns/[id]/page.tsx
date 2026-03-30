"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  RefreshCw,
  Play,
  Pause,
  RotateCw,
  Calendar,
  Users,
  FileText,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  useCampaign,
  useCampaignStats,
  useCampaignRecipients,
  useLaunchCampaign,
  usePauseCampaign,
  useResumeCampaign,
} from "@/hooks/use-campaigns";
import { CampaignStats } from "../components/campaign-stats";
import { FunnelChart } from "../components/funnel-chart";
import type { CampaignStatus, RecipientStatus } from "@/types/campaign";

// ---------------------------------------------------------------------------
// Config
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

const recipientStatusConfig: Record<
  RecipientStatus,
  { label: string; className: string }
> = {
  pending: {
    label: "En attente",
    className: "bg-muted text-muted-foreground border-0",
  },
  sent: {
    label: "Envoyé",
    className: "bg-[hsl(var(--info))]/10 text-[hsl(var(--info))] border-0",
  },
  delivered: {
    label: "Délivré",
    className: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-0",
  },
  read: {
    label: "Lu",
    className: "bg-primary/10 text-primary border-0",
  },
  failed: {
    label: "Échoué",
    className: "bg-destructive/10 text-destructive border-0",
  },
};

const recipientFilterOptions = [
  { value: "all", label: "Tous" },
  { value: "pending", label: "En attente" },
  { value: "sent", label: "Envoyé" },
  { value: "delivered", label: "Délivré" },
  { value: "read", label: "Lu" },
  { value: "failed", label: "Échoué" },
];

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString("fr-FR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CampaignDetailPage() {
  const params = useParams();
  const campaignId = typeof params.id === "string" ? params.id : null;

  const [recipientPage, setRecipientPage] = useState(1);
  const [recipientFilter, setRecipientFilter] = useState("all");

  const {
    data: campaign,
    isLoading,
    isError,
    refetch,
  } = useCampaign(campaignId);
  const { data: stats, isLoading: statsLoading } =
    useCampaignStats(campaignId);
  const { data: recipientsData, isLoading: recipientsLoading } =
    useCampaignRecipients(campaignId, {
      page: recipientPage,
      page_size: 50,
      status:
        recipientFilter === "all"
          ? undefined
          : (recipientFilter as RecipientStatus),
    });

  const launchCampaign = useLaunchCampaign();
  const pauseCampaign = usePauseCampaign();
  const resumeCampaign = useResumeCampaign();

  const recipients = recipientsData?.items ?? [];
  const recipientsTotal = recipientsData?.total ?? 0;
  const recipientsTotalPages = Math.max(
    1,
    Math.ceil(recipientsTotal / (recipientsData?.page_size ?? 50))
  );

  async function handleAction(action: "launch" | "pause" | "resume") {
    if (!campaignId) return;
    try {
      if (action === "launch") {
        await launchCampaign.mutateAsync(campaignId);
        toast.success("Campagne lancée");
      } else if (action === "pause") {
        await pauseCampaign.mutateAsync(campaignId);
        toast.success("Campagne mise en pause");
      } else {
        await resumeCampaign.mutateAsync(campaignId);
        toast.success("Campagne reprise");
      }
    } catch {
      toast.error("Erreur lors de l'action");
    }
  }

  // Loading
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Error
  if (isError || !campaign) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive mb-3" />
        <p className="text-sm text-muted-foreground mb-3">
          Impossible de charger la campagne
        </p>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 me-2" />
          Réessayer
        </Button>
      </div>
    );
  }

  const status = statusConfig[campaign.status];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/campaigns">
              <ArrowLeft className="h-4 w-4" strokeWidth={1.75} />
            </Link>
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-heading font-bold">
                {campaign.name}
              </h1>
              <Badge
                className={cn(
                  "text-xs font-medium",
                  status.className,
                  campaign.status === "sending" && "animate-pulse"
                )}
              >
                {status.label}
              </Badge>
            </div>
            {campaign.description && (
              <p className="mt-1 text-sm text-muted-foreground">
                {campaign.description}
              </p>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          {(campaign.status === "draft" ||
            campaign.status === "scheduled") && (
            <Button onClick={() => handleAction("launch")}>
              <Play className="h-4 w-4 me-2" strokeWidth={1.75} />
              Lancer
            </Button>
          )}
          {campaign.status === "sending" && (
            <Button
              variant="outline"
              onClick={() => handleAction("pause")}
            >
              <Pause className="h-4 w-4 me-2" strokeWidth={1.75} />
              Mettre en pause
            </Button>
          )}
          {campaign.status === "paused" && (
            <Button onClick={() => handleAction("resume")}>
              <RotateCw className="h-4 w-4 me-2" strokeWidth={1.75} />
              Reprendre
            </Button>
          )}
        </div>
      </div>

      {/* Campaign info cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="rounded-lg bg-primary/10 p-2">
              <FileText
                className="h-5 w-5 text-primary"
                strokeWidth={1.75}
              />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Template</p>
              <p className="text-sm font-medium">{campaign.template_name}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="rounded-lg bg-[hsl(var(--info))]/10 p-2">
              <Users
                className="h-5 w-5 text-[hsl(var(--info))]"
                strokeWidth={1.75}
              />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Audience</p>
              <p className="text-sm font-medium">
                {campaign.audience_count.toLocaleString("fr-FR")} contacts
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="rounded-lg bg-[hsl(var(--warning))]/10 p-2">
              <Calendar
                className="h-5 w-5 text-[hsl(var(--warning))]"
                strokeWidth={1.75}
              />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">
                {campaign.scheduled_at ? "Planifiée" : "Créée"}
              </p>
              <p className="text-sm font-medium">
                {formatDateTime(
                  campaign.scheduled_at ?? campaign.created_at
                )}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Stats KPIs */}
      <CampaignStats stats={stats} isLoading={statsLoading} />

      {/* Funnel chart */}
      {stats && stats.total > 0 && <FunnelChart stats={stats} />}

      {/* Recipients table */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-heading font-semibold">
            Destinataires
          </h2>
          <Select
            value={recipientFilter}
            onValueChange={(v) => {
              setRecipientFilter(v);
              setRecipientPage(1);
            }}
          >
            <SelectTrigger className="w-[150px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {recipientFilterOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-start">Contact</TableHead>
                <TableHead className="text-start">Statut</TableHead>
                <TableHead className="text-start hidden sm:table-cell">
                  Envoyé le
                </TableHead>
                <TableHead className="text-start hidden md:table-cell">
                  Délivré le
                </TableHead>
                <TableHead className="text-start hidden lg:table-cell">
                  Lu le
                </TableHead>
                <TableHead className="text-start hidden md:table-cell">
                  Erreur
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recipientsLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-24 text-center">
                    <div className="flex items-center justify-center gap-2 text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Chargement…</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : recipients.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-24 text-center">
                    <p className="text-muted-foreground">
                      Aucun destinataire
                    </p>
                  </TableCell>
                </TableRow>
              ) : (
                recipients.map((r) => {
                  const rStatus = recipientStatusConfig[r.status];
                  return (
                    <TableRow key={r.id}>
                      <TableCell>
                        <span className="text-sm font-mono">
                          {r.contact_id.slice(0, 8)}…
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          className={cn(
                            "text-xs font-medium",
                            rStatus.className
                          )}
                        >
                          {rStatus.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden sm:table-cell text-xs text-muted-foreground">
                        {formatDateTime(r.sent_at)}
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-xs text-muted-foreground">
                        {formatDateTime(r.delivered_at)}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">
                        {formatDateTime(r.read_at)}
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {r.error_message && (
                          <span className="text-xs text-destructive line-clamp-1">
                            {r.error_message}
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        {recipientsTotalPages > 1 && (
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              Page {recipientPage} / {recipientsTotalPages} —{" "}
              {recipientsTotal} destinataire
              {recipientsTotal > 1 ? "s" : ""}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={recipientPage <= 1}
                onClick={() => setRecipientPage((p) => p - 1)}
              >
                Précédent
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={recipientPage >= recipientsTotalPages}
                onClick={() => setRecipientPage((p) => p + 1)}
              >
                Suivant
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
