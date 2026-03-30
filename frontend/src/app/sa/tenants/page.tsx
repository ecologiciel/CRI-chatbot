import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TenantsTable } from "@/components/super-admin/tenants-table";

export default function TenantsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Tenants CRI</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Gérez les Centres Régionaux d&apos;Investissement de la plateforme.
          </p>
        </div>
        <Button asChild>
          <Link href="/sa/tenants/new">
            <Plus className="h-4 w-4 me-2" />
            Créer un tenant
          </Link>
        </Button>
      </div>

      <TenantsTable />
    </div>
  );
}
