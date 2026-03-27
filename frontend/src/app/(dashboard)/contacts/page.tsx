"use client";

import { useState } from "react";
import { Plus, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ContactTable } from "./components/contact-table";
import { ImportWizard } from "./components/import-wizard";

export default function ContactsPage() {
  const [importOpen, setImportOpen] = useState(false);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Contacts</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Gérez les contacts WhatsApp et importez des listes
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setImportOpen(true)}>
            <Upload className="h-4 w-4 me-2" strokeWidth={1.75} />
            Importer
          </Button>
        </div>
      </div>

      {/* Contact table with search, filters, pagination */}
      <ContactTable />

      {/* Import wizard dialog */}
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
}
