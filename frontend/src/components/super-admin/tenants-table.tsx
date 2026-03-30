"use client";

import * as React from "react";
import { MoreHorizontal, Power, PowerOff, ExternalLink, Settings } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent } from "@/components/ui/card";
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
import { useTenants, useToggleTenant } from "@/hooks/use-super-admin";
import { TENANT_STATUS_STYLES } from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Status label map
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<string, string> = {
  active: "Actif",
  inactive: "Inactif",
  suspended: "Suspendu",
  provisioning: "Provisionnement",
};

// ---------------------------------------------------------------------------
// TenantsTable
// ---------------------------------------------------------------------------

export function TenantsTable() {
  const { data: tenants, isLoading } = useTenants();
  const toggleTenant = useToggleTenant();

  function handleToggle(slug: string, currentlyActive: boolean) {
    const action = currentlyActive ? "désactiver" : "activer";
    toggleTenant.mutate(
      { slug, active: !currentlyActive },
      {
        onSuccess: () => toast.success(`Tenant ${action === "activer" ? "activé" : "désactivé"}`),
        onError: () => toast.error(`Erreur lors de la tentative de ${action} le tenant`),
      }
    );
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-0">
          <div className="space-y-0 divide-y">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 p-4">
                <div className="h-4 w-40 bg-muted animate-pulse rounded" />
                <div className="h-4 w-20 bg-muted animate-pulse rounded hidden sm:block" />
                <div className="h-4 w-28 bg-muted animate-pulse rounded hidden md:block" />
                <div className="h-5 w-16 bg-muted animate-pulse rounded-full" />
                <div className="ms-auto h-4 w-12 bg-muted animate-pulse rounded" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!tenants || tenants.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-muted-foreground text-sm">
            Aucun tenant pour le moment.
          </p>
          <p className="text-muted-foreground text-xs mt-1">
            Créez votre premier tenant CRI pour commencer.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom CRI</TableHead>
              <TableHead className="hidden sm:table-cell">Slug</TableHead>
              <TableHead className="hidden md:table-cell">Région</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="hidden lg:table-cell">Messages</TableHead>
              <TableHead className="hidden lg:table-cell">Contacts</TableHead>
              <TableHead className="hidden xl:table-cell">Créé le</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tenants.map((tenant) => {
              const pct = tenant.messages_limit > 0
                ? Math.round((tenant.messages_used / tenant.messages_limit) * 100)
                : 0;
              const isActive = tenant.status === "active";

              return (
                <TableRow key={tenant.id}>
                  <TableCell className="font-medium">{tenant.name}</TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <code className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">
                      {tenant.slug}
                    </code>
                  </TableCell>
                  <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                    {tenant.region}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-xs",
                        TENANT_STATUS_STYLES[tenant.status]
                      )}
                    >
                      {STATUS_LABELS[tenant.status] ?? tenant.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <div className="flex items-center gap-2">
                      <Progress value={pct} className="h-2 w-20" />
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {tenant.messages_used.toLocaleString("fr-FR")} / {tenant.messages_limit.toLocaleString("fr-FR")}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell text-sm">
                    {tenant.contacts_count.toLocaleString("fr-FR")}
                  </TableCell>
                  <TableCell className="hidden xl:table-cell text-sm text-muted-foreground">
                    {new Date(tenant.created_at).toLocaleDateString("fr-FR")}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreHorizontal className="h-4 w-4" />
                          <span className="sr-only">Actions</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem>
                          <ExternalLink className="h-4 w-4" />
                          <span>Voir détails</span>
                        </DropdownMenuItem>
                        <DropdownMenuItem>
                          <Settings className="h-4 w-4" />
                          <span>Configurer</span>
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => handleToggle(tenant.slug, isActive)}
                          className={cn(
                            isActive
                              ? "text-destructive focus:text-destructive"
                              : "text-[#5F8B5F] focus:text-[#5F8B5F]"
                          )}
                        >
                          {isActive ? (
                            <>
                              <PowerOff className="h-4 w-4" />
                              <span>Désactiver</span>
                            </>
                          ) : (
                            <>
                              <Power className="h-4 w-4" />
                              <span>Activer</span>
                            </>
                          )}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
