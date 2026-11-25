import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TenantsTable } from "@/components/super-admin/tenants-table";

export default function TenantsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Institutions</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Créez et gérez vos démonstrations de chatbot.
          </p>
        </div>
        <Button asChild>
          <Link href="/sa/tenants/new">
            <Plus className="h-4 w-4 me-2" />
            Créer une démonstration
          </Link>
        </Button>
      </div>

      <TenantsTable />
    </div>
  );
}
