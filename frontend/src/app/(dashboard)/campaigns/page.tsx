"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CampaignsTable } from "./components/campaigns-table";
import { QuotaIndicator } from "./components/quota-indicator";
import { useCampaignQuota } from "@/hooks/use-campaigns";

export default function CampaignsPage() {
  const { data: quota } = useCampaignQuota();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-4">
          <div>
            <h1 className="text-2xl font-heading font-bold">Campagnes</h1>
            <p className="text-sm text-muted-foreground">
              Gérez vos campagnes de publipostage WhatsApp
            </p>
          </div>
          {quota && (
            <QuotaIndicator
              used={quota.used}
              limit={quota.limit}
              percentage={quota.percentage}
              className="hidden lg:flex"
            />
          )}
        </div>
        <Button asChild>
          <Link href="/campaigns/new">
            <Plus className="h-4 w-4 me-2" strokeWidth={1.75} />
            Nouvelle campagne
          </Link>
        </Button>
      </div>

      {/* Table */}
      <CampaignsTable />
    </div>
  );
}
