"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { WhatsAppPreview } from "./whatsapp-preview";
import { useCampaignTemplates } from "@/hooks/use-campaigns";
import type { UseFormSetValue, UseFormWatch, FieldErrors } from "react-hook-form";
import type { CampaignWizardData, WhatsAppTemplate } from "@/types/campaign";

const languageLabels: Record<string, string> = {
  fr: "Français",
  ar: "العربية",
  en: "English",
};

interface StepTemplateProps {
  setValue: UseFormSetValue<CampaignWizardData>;
  watch: UseFormWatch<CampaignWizardData>;
  errors: FieldErrors<CampaignWizardData>;
  locked: boolean;
}

export function StepTemplate({ setValue, watch, errors, locked }: StepTemplateProps) {
  const { data, isLoading, isError, refetch } = useCampaignTemplates();
  const templates = data?.items ?? [];
  const selectedId = watch("template_id");
  const selectedTemplate = templates.find((t) => t.id === selectedId);

  function handleSelect(template: WhatsAppTemplate) {
    if (locked && template.id !== selectedId) return;
    setValue("template_id", template.id, { shouldValidate: true });
    setValue("template_name", template.name);
    setValue("template_language", template.language);
    // Reset variable mapping when template changes
    setValue("variable_mapping", {});
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Template list */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground">
          Sélectionnez un modèle WhatsApp approuvé
        </h3>
        {isLoading && <p className="text-sm text-muted-foreground">Chargement des modèles Meta…</p>}
        {isError && <div className="text-sm text-destructive">Impossible de charger les modèles Meta. <button type="button" className="underline" onClick={() => refetch()}>Réessayer</button></div>}
        {data && !data.configured && <p className="text-sm text-muted-foreground">Le compte WhatsApp de cette institution doit être configuré pour accéder aux modèles approuvés.</p>}
        {data?.configured && templates.length === 0 && <p className="text-sm text-muted-foreground">Aucun modèle approuvé compatible n’est disponible.</p>}
        {data?.truncated && <p className="text-sm text-muted-foreground">Seuls les 1 000 premiers modèles ont été examinés.</p>}
        {locked && <p className="text-sm text-muted-foreground">Le modèle est fixé pour ce brouillon ; créez une nouvelle campagne pour en choisir un autre.</p>}
        {errors.template_id && (
          <p className="text-xs text-destructive">
            Sélectionnez un template
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {templates.map((template) => (
            <Card
              key={template.id}
              className={cn(
                "cursor-pointer transition-colors hover:border-primary/50",
                locked && selectedId !== template.id && "cursor-not-allowed opacity-50",
                selectedId === template.id &&
                  "border-primary ring-1 ring-primary/20"
              )}
              onClick={() => handleSelect(template)}
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h4 className="text-sm font-medium leading-tight">
                    {template.name}
                  </h4>
                  <Badge
                    variant="secondary"
                    className="shrink-0 text-[10px]"
                  >
                    {languageLabels[template.language] ?? template.language}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-3">
                  {template.body}
                </p>
                {template.variables.length > 0 && (
                  <p className="mt-2 text-[10px] text-muted-foreground">
                    {template.variables.length} variable
                    {template.variables.length > 1 ? "s" : ""}
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* WhatsApp preview */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground">
          Aperçu du message
        </h3>
        {selectedTemplate ? (
          <WhatsAppPreview
            body={selectedTemplate.body}
            headerText={selectedTemplate.header}
            footerText={selectedTemplate.footer}
            buttons={selectedTemplate.buttons}
          />
        ) : (
          <div className="flex items-center justify-center rounded-lg border border-dashed py-16 text-sm text-muted-foreground">
            Sélectionnez un template pour voir l&apos;aperçu
          </div>
        )}
      </div>
    </div>
  );
}

