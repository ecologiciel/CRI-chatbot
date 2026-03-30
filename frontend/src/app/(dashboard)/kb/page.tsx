"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLearningStats } from "@/hooks/use-learning";
import { DocumentTable } from "./components/document-table";
import { UploadModal } from "./components/upload-modal";
import { UnansweredTab } from "./components/unanswered-tab";

export default function KBPage() {
  const [uploadOpen, setUploadOpen] = useState(false);
  const { data: statsData } = useLearningStats();
  const pendingCount = statsData?.by_status?.pending ?? 0;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading text-foreground">
            Base de connaissances
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Gérez les documents et questions de la base de connaissances
          </p>
        </div>
        <Button onClick={() => setUploadOpen(true)}>
          <Plus className="h-4 w-4 me-2" strokeWidth={1.75} />
          Ajouter un document
        </Button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="documents">
        <TabsList>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="unanswered">
            Questions non couvertes
            {pendingCount > 0 && (
              <Badge className="ms-2 h-5 min-w-[20px] px-1.5 text-xs bg-[hsl(var(--warning))]/15 text-[hsl(var(--warning))] border-0">
                {pendingCount}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="documents">
          <DocumentTable />
        </TabsContent>

        <TabsContent value="unanswered">
          <UnansweredTab />
        </TabsContent>
      </Tabs>

      {/* Upload modal */}
      <UploadModal open={uploadOpen} onOpenChange={setUploadOpen} />
    </div>
  );
}
