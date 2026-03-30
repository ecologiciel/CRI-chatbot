"use client";

import { Zap, Calendar } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QuotaIndicator } from "./quota-indicator";
import { useCampaignQuota } from "@/hooks/use-campaigns";
import type {
  UseFormRegister,
  UseFormSetValue,
  UseFormWatch,
  FieldErrors,
} from "react-hook-form";
import type { CampaignWizardData } from "@/types/campaign";

interface StepScheduleProps {
  register: UseFormRegister<CampaignWizardData>;
  setValue: UseFormSetValue<CampaignWizardData>;
  watch: UseFormWatch<CampaignWizardData>;
  errors: FieldErrors<CampaignWizardData>;
  audienceCount: number;
}

export function StepSchedule({
  register,
  setValue,
  watch,
  errors,
  audienceCount,
}: StepScheduleProps) {
  const sendMode = watch("send_mode") ?? "immediate";
  const { data: quota } = useCampaignQuota(audienceCount);

  // Minimum datetime = now + 5 minutes
  const minDatetime = new Date(Date.now() + 5 * 60_000)
    .toISOString()
    .slice(0, 16);

  return (
    <div className="space-y-6">
      {/* Campaign name & description */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="name">Nom de la campagne *</Label>
          <Input
            id="name"
            placeholder="Ex: Bienvenue nouveaux investisseurs"
            {...register("name")}
          />
          {errors.name && (
            <p className="text-xs text-destructive">
              {errors.name.message ?? "Le nom est requis"}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Input
            id="description"
            placeholder="Description optionnelle"
            {...register("description")}
          />
        </div>
      </div>

      {/* Send mode */}
      <div className="space-y-3">
        <Label>Mode d&apos;envoi</Label>
        <div className="grid gap-3 sm:grid-cols-2">
          <Card
            className={cn(
              "cursor-pointer transition-colors hover:border-primary/50",
              sendMode === "immediate" &&
                "border-primary ring-1 ring-primary/20"
            )}
            onClick={() => setValue("send_mode", "immediate")}
          >
            <CardContent className="flex items-center gap-3 p-4">
              <div
                className={cn(
                  "rounded-lg p-2",
                  sendMode === "immediate"
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground"
                )}
              >
                <Zap className="h-5 w-5" strokeWidth={1.75} />
              </div>
              <div>
                <p className="text-sm font-medium">Envoyer maintenant</p>
                <p className="text-xs text-muted-foreground">
                  La campagne sera lancée immédiatement
                </p>
              </div>
            </CardContent>
          </Card>
          <Card
            className={cn(
              "cursor-pointer transition-colors hover:border-primary/50",
              sendMode === "scheduled" &&
                "border-primary ring-1 ring-primary/20"
            )}
            onClick={() => setValue("send_mode", "scheduled")}
          >
            <CardContent className="flex items-center gap-3 p-4">
              <div
                className={cn(
                  "rounded-lg p-2",
                  sendMode === "scheduled"
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground"
                )}
              >
                <Calendar className="h-5 w-5" strokeWidth={1.75} />
              </div>
              <div>
                <p className="text-sm font-medium">Planifier</p>
                <p className="text-xs text-muted-foreground">
                  Choisir une date et heure d&apos;envoi
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Scheduled datetime */}
      {sendMode === "scheduled" && (
        <div className="space-y-2">
          <Label htmlFor="scheduled_at">Date et heure d&apos;envoi</Label>
          <Input
            id="scheduled_at"
            type="datetime-local"
            min={minDatetime}
            {...register("scheduled_at")}
          />
          {errors.scheduled_at && (
            <p className="text-xs text-destructive">
              {errors.scheduled_at.message ?? "Date requise"}
            </p>
          )}
        </div>
      )}

      {/* Quota + Summary */}
      <div className="grid gap-4 sm:grid-cols-2">
        {/* Quota */}
        {quota && (
          <Card>
            <CardContent className="flex items-center justify-center p-6">
              <QuotaIndicator
                used={quota.used}
                limit={quota.limit}
                percentage={quota.percentage}
              />
            </CardContent>
          </Card>
        )}

        {/* Summary */}
        <Card>
          <CardContent className="p-6">
            <h4 className="mb-3 text-sm font-medium">Récapitulatif</h4>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Template</dt>
                <dd className="font-medium">{watch("template_name") || "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Audience</dt>
                <dd className="font-medium">
                  {audienceCount > 0
                    ? `${audienceCount.toLocaleString("fr-FR")} contacts`
                    : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Mode</dt>
                <dd className="font-medium">
                  {sendMode === "immediate" ? "Immédiat" : "Planifié"}
                </dd>
              </div>
            </dl>
            {quota && !quota.allowed && (
              <div className="mt-3 rounded-lg bg-destructive/10 p-3 text-xs text-destructive">
                Quota insuffisant pour cette campagne
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
