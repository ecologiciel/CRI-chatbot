import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TenantWizard } from "@/components/super-admin/tenant-wizard";

export default function NewTenantPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/sa/tenants">
            <ArrowLeft className="h-4 w-4 rtl:rotate-180" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold font-heading">Créer une démonstration</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Préparez un espace pour une institution.
          </p>
        </div>
      </div>

      <TenantWizard />
    </div>
  );
}
