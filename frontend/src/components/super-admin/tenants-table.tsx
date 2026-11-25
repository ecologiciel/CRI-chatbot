"use client";

import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useTenants, useToggleTenant } from "@/hooks/use-super-admin";
import { selectTenant } from "@/lib/api-client";

const statusLabels: Record<string, string> = {
  active: "Actif", inactive: "Inactif", suspended: "Suspendu", provisioning: "En cours",
};

export function TenantsTable() {
  const { data: tenants, isLoading, isError, refetch } = useTenants();
  const toggle = useToggleTenant();

  if (isLoading) return <p>Chargement des institutions…</p>;
  if (isError) return <div><p>Impossible de charger les institutions.</p><Button variant="outline" onClick={() => refetch()}>Réessayer</Button></div>;
  if (!tenants?.length) return <p>Aucune institution. Créez une démonstration pour commencer.</p>;

  return (
    <Card><CardContent className="p-0"><Table>
      <TableHeader><TableRow><TableHead>Institution</TableHead><TableHead>Code</TableHead><TableHead>Zone</TableHead><TableHead>Statut</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader>
      <TableBody>{tenants.map((tenant) => (
        <TableRow key={tenant.id}>
          <TableCell className="font-medium">{tenant.name}</TableCell>
          <TableCell>{tenant.slug}</TableCell>
          <TableCell>{tenant.region}</TableCell>
          <TableCell>{statusLabels[tenant.status] ?? tenant.status}</TableCell>
          <TableCell><div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={tenant.status !== "active"} onClick={() => {
              selectTenant(tenant.id, tenant.name);
              // A full reload clears cached data belonging to the previous institution.
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination
              window.location.assign(`${process.env.NEXT_PUBLIC_BASE_PATH || ""}/kb`);
            }}>Gérer les documents</Button>
            {tenant.status === "active" && tenant.public_config?.web_enabled === true && (
              <Button variant="outline" size="sm" asChild><a href={`/${tenant.slug}`} target="_blank" rel="noreferrer">Ouvrir le chatbot</a></Button>
            )}
            <Button variant="ghost" size="sm" disabled={toggle.isPending || !["active", "inactive"].includes(tenant.status)} onClick={() => {
              toggle.mutate({ id: tenant.id, active: tenant.status !== "active" }, {
                onSuccess: () => toast.success("Statut mis à jour"),
                onError: () => toast.error("Impossible de modifier le statut"),
              });
            }}>{tenant.status === "active" ? "Désactiver" : "Activer"}</Button>
          </div></TableCell>
        </TableRow>
      ))}</TableBody>
    </Table></CardContent></Card>
  );
}
