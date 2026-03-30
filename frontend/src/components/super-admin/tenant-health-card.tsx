"use client";

import {
  MessageSquare,
  MessagesSquare,
  Users,
  Clock,
  Wifi,
  WifiOff,
  Database,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { MonitoringTenantHealth } from "@/types/super-admin";
import { TENANT_STATUS_STYLES } from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "Aucune activité";
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "À l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours}h`;
  const days = Math.floor(hours / 24);
  return `il y a ${days}j`;
}

const STATUS_LABELS: Record<string, string> = {
  active: "Actif",
  inactive: "Inactif",
  suspended: "Suspendu",
  provisioning: "Provisionnement",
};

// ---------------------------------------------------------------------------
// TenantHealthCard
// ---------------------------------------------------------------------------

interface TenantHealthCardProps {
  health: MonitoringTenantHealth;
}

export function TenantHealthCard({ health }: TenantHealthCardProps) {
  const { tenant, is_healthy, messages_today, conversations_active, whatsapp_connected, qdrant_collection_size } = health;

  return (
    <Card className="relative">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            {/* Health dot */}
            <div
              className={cn(
                "h-2.5 w-2.5 rounded-full shrink-0",
                is_healthy ? "bg-[#5F8B5F]" : "bg-[#B5544B]"
              )}
            />
            <h3 className="text-sm font-semibold font-heading truncate">
              {tenant.name}
            </h3>
          </div>
          <Badge
            variant="outline"
            className={cn("text-[10px] shrink-0", TENANT_STATUS_STYLES[tenant.status])}
          >
            {STATUS_LABELS[tenant.status] ?? tenant.status}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground font-mono">{tenant.slug}</p>
      </CardHeader>

      <CardContent className="space-y-2.5 pt-0">
        {/* Metrics */}
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <MessageSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            <span className="text-xs">Messages&nbsp;:</span>
            <span className="text-foreground font-medium text-xs">
              {messages_today}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <MessagesSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            <span className="text-xs">Actives&nbsp;:</span>
            <span className="text-foreground font-medium text-xs">
              {conversations_active}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Users className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            <span className="text-xs">Contacts&nbsp;:</span>
            <span className="text-foreground font-medium text-xs">
              {tenant.contacts_count.toLocaleString("fr-FR")}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            <span className="text-xs truncate">
              {formatRelativeTime(tenant.last_activity)}
            </span>
          </div>
        </div>

        {/* Status row */}
        <div className="flex items-center justify-between pt-1 border-t text-xs">
          <div className="flex items-center gap-1.5">
            {whatsapp_connected ? (
              <Wifi className="h-3.5 w-3.5 text-[#5F8B5F]" strokeWidth={1.75} />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-[#B5544B]" strokeWidth={1.75} />
            )}
            <span className={whatsapp_connected ? "text-[#5F8B5F]" : "text-[#B5544B]"}>
              WhatsApp {whatsapp_connected ? "connecté" : "déconnecté"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Database className="h-3.5 w-3.5" strokeWidth={1.75} />
            <span>{qdrant_collection_size.toLocaleString("fr-FR")} vecteurs</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
