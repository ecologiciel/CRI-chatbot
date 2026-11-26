"use client";

import { useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TenantHealthCard } from "@/components/super-admin/tenant-health-card";
import { useTenantsHealth } from "@/hooks/use-super-admin";

export default function MonitoringPage() {
  const [page, setPage] = useState(1);
  const { data: healthData, isLoading, isError, dataUpdatedAt, refetch, isFetching } = useTenantsHealth(page);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Monitoring</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Présence des ressources à cet instant. Ces vérifications ne testent ni les réponses du chatbot ni la connexion à Meta.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {!isError && dataUpdatedAt > 0 && (
            <span className="text-xs text-muted-foreground hidden sm:inline">
              Mis à jour à{" "}
              {new Date(dataUpdatedAt).toLocaleTimeString("fr-FR", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`h-4 w-4 me-2 ${isFetching ? "animate-spin" : ""}`} />
            Rafraîchir
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <div className="h-2.5 w-2.5 bg-muted animate-pulse rounded-full" />
                  <div className="h-4 w-32 bg-muted animate-pulse rounded" />
                </div>
                <div className="h-3 w-20 bg-muted animate-pulse rounded" />
                <div className="space-y-2 pt-2">
                  <div className="h-3 w-full bg-muted animate-pulse rounded" />
                  <div className="h-3 w-3/4 bg-muted animate-pulse rounded" />
                  <div className="h-3 w-1/2 bg-muted animate-pulse rounded" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center" role="alert">
            <Activity className="h-10 w-10 text-destructive mb-3" strokeWidth={1.5} />
            <p className="text-sm text-destructive">La surveillance des institutions est indisponible.</p>
            <p className="text-xs text-muted-foreground mt-2">L’état des canaux et des services ne peut pas être confirmé depuis cette page.</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()} disabled={isFetching}>
              Réessayer
            </Button>
          </CardContent>
        </Card>
      ) : !healthData || healthData.items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Activity className="h-10 w-10 text-muted-foreground/50 mb-3" strokeWidth={1.5} />
            <p className="text-muted-foreground text-sm">
              {page === 1 ? "Aucune institution à surveiller." : "Aucune institution sur cette page."}
            </p>
            {page > 1 && <Button variant="outline" size="sm" className="mt-4" onClick={() => setPage(page - 1)}>Page précédente</Button>}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {healthData.items.map((health) => <TenantHealthCard key={health.id} health={health} />)}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Précédent</Button>
            <span className="text-sm">Page {page} · {healthData.total} institution(s)</span>
            <Button variant="outline" size="sm" disabled={page * healthData.page_size >= healthData.total} onClick={() => setPage(page + 1)}>Suivant</Button>
          </div>
        </>
      )}
    </div>
  );
}
