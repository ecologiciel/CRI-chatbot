import { AuditTable } from "@/components/super-admin/audit-table";

export default function AuditPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-heading">Logs d&apos;audit</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Historique centralisé des actions sur la plateforme. Lecture seule.
        </p>
      </div>

      <AuditTable />
    </div>
  );
}
