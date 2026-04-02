"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDossierStats } from "@/hooks/use-dossiers";
import { DossierStats } from "./components/dossier-stats";
import { DossierTable } from "./components/dossier-table";
import { ImportWizard } from "./components/import-wizard";

export default function DossiersPage() {
  const [importOpen, setImportOpen] = useState(false);
  const { data: stats, isLoading: statsLoading } = useDossierStats();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Dossiers</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Suivi des dossiers d&apos;investissement importés du SI
          </p>
        </div>
        <Button onClick={() => setImportOpen(true)}>
          <Upload className="h-4 w-4 me-2" strokeWidth={1.75} />
          Importer
        </Button>
      </div>

      {/* KPI Cards */}
      <DossierStats stats={stats} isLoading={statsLoading} />

      {/* Table */}
      <DossierTable />

      {/* Import Wizard */}
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
}
