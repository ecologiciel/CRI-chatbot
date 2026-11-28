"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { MonitoringTenantHealth } from "@/types/super-admin";

function presence(value: boolean | null): string {
  return value === null ? "Vérification indisponible" : value ? "Présent" : "Absent";
}

export function TenantHealthCard({ health }: { health: MonitoringTenantHealth }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <h3 className="font-semibold">{health.name}</h3>
        <p className="text-xs text-muted-foreground">{health.slug} · {health.status}</p>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>Schéma de base : {presence(health.schema_present)}</p>
        <p>Collection documentaire : {presence(health.collection_present)}</p>
        <p>Stockage des fichiers : {presence(health.bucket_present)}</p>
        <p>Chat web : {health.web_enabled ? "Activé" : "Non activé"}</p>
        <p>WhatsApp : {health.whatsapp_configured === null ? "Vérification indisponible" : health.whatsapp_configured ? "Identifiants renseignés, connexion non vérifiée" : "Identifiants incomplets ou absents"}</p>
      </CardContent>
    </Card>
  );
}
