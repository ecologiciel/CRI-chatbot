"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CampaignWizard } from "../components/campaign-wizard";

export default function NewCampaignPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/campaigns">
            <ArrowLeft className="h-4 w-4" strokeWidth={1.75} />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-heading font-bold">
            Nouvelle campagne
          </h1>
          <p className="text-sm text-muted-foreground">
            Créez une campagne de publipostage WhatsApp en 4 étapes
          </p>
        </div>
      </div>

      {/* Wizard */}
      <CampaignWizard />
    </div>
  );
}
