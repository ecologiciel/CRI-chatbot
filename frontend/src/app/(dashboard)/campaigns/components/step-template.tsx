"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { WhatsAppPreview } from "./whatsapp-preview";
import type { UseFormSetValue, UseFormWatch, FieldErrors } from "react-hook-form";
import type { CampaignWizardData, WhatsAppTemplate } from "@/types/campaign";

// TODO: Replace with API call when /templates endpoint is available
const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: "welcome_investor",
    name: "Bienvenue Investisseur",
    language: "fr",
    body: "Bonjour {{1}}, bienvenue au CRI Rabat-Salé-Kénitra ! Nous sommes à votre disposition pour accompagner votre projet d'investissement.",
    footer: "CRI RSK",
    variables: ["1"],
  },
  {
    id: "dossier_update",
    name: "Mise à jour dossier",
    language: "fr",
    body: "Bonjour {{1}}, votre dossier {{2}} a changé de statut. Nouveau statut : {{3}}. Contactez-nous pour plus d'informations.",
    variables: ["1", "2", "3"],
  },
  {
    id: "rappel_complement",
    name: "Rappel complément",
    language: "fr",
    body: "Bonjour {{1}}, nous vous rappelons que des documents complémentaires sont attendus pour votre dossier. Merci de les fournir dans les meilleurs délais.",
    footer: "CRI RSK",
    buttons: ["📞 Nous contacter"],
    variables: ["1"],
  },
  {
    id: "welcome_ar",
    name: "ترحيب بالمستثمر",
    language: "ar",
    body: "مرحباً {{1}}، أهلاً بكم في المركز الجهوي للاستثمار الرباط-سلا-القنيطرة! نحن في خدمتكم لمرافقة مشروعكم الاستثماري.",
    footer: "CRI RSK",
    variables: ["1"],
  },
];

const languageLabels: Record<string, string> = {
  fr: "Français",
  ar: "العربية",
  en: "English",
};

interface StepTemplateProps {
  setValue: UseFormSetValue<CampaignWizardData>;
  watch: UseFormWatch<CampaignWizardData>;
  errors: FieldErrors<CampaignWizardData>;
}

export function StepTemplate({ setValue, watch, errors }: StepTemplateProps) {
  const selectedId = watch("template_id");
  const selectedTemplate = TEMPLATES.find((t) => t.id === selectedId);

  function handleSelect(template: WhatsAppTemplate) {
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
          Sélectionnez un template WhatsApp
        </h3>
        {errors.template_id && (
          <p className="text-xs text-destructive">
            Sélectionnez un template
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {TEMPLATES.map((template) => (
            <Card
              key={template.id}
              className={cn(
                "cursor-pointer transition-colors hover:border-primary/50",
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

// Re-export TEMPLATES for use in other steps
export { TEMPLATES };
