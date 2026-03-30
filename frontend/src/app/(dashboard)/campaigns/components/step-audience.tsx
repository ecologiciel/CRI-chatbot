"use client";

import { useState, useEffect } from "react";
import { Users, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useAudiencePreview,
  useCreateCampaign,
  useUpdateCampaign,
} from "@/hooks/use-campaigns";
import type { UseFormSetValue, UseFormWatch, FieldErrors } from "react-hook-form";
import type { CampaignWizardData, AudiencePreview } from "@/types/campaign";

// Common tags for CRI investors
const AVAILABLE_TAGS = [
  "investisseur_actif",
  "nouveau",
  "industrie",
  "commerce",
  "services",
  "agriculture",
  "immobilier",
  "tourisme",
  "artisanat",
  "tech",
];

const languageOptions = [
  { value: "all", label: "Toutes les langues" },
  { value: "fr", label: "Français" },
  { value: "ar", label: "العربية" },
  { value: "en", label: "English" },
];

interface StepAudienceProps {
  setValue: UseFormSetValue<CampaignWizardData>;
  watch: UseFormWatch<CampaignWizardData>;
  errors: FieldErrors<CampaignWizardData>;
  draftId: string | null;
  onDraftCreated: (id: string) => void;
}

export function StepAudience({
  setValue,
  watch,
  errors,
  draftId,
  onDraftCreated,
}: StepAudienceProps) {
  const selectedTags = watch("audience_tags") ?? [];
  const selectedLanguage = watch("audience_language") ?? "all";
  const templateId = watch("template_id");
  const templateName = watch("template_name");
  const templateLanguage = watch("template_language");

  const [preview, setPreview] = useState<AudiencePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const createCampaign = useCreateCampaign();
  const updateCampaign = useUpdateCampaign();
  const audiencePreview = useAudiencePreview();

  // Debounced preview fetch
  useEffect(() => {
    if (selectedTags.length === 0) {
      setPreview(null);
      return;
    }

    const filter: Record<string, unknown> = {};
    if (selectedTags.length > 0) filter.tags = selectedTags;
    if (selectedLanguage !== "all") filter.language = selectedLanguage;

    const timer = setTimeout(async () => {
      setPreviewLoading(true);

      let campaignId = draftId;

      // Lazy draft creation
      if (!campaignId) {
        try {
          const draft = await createCampaign.mutateAsync({
            name: `Brouillon ${new Date().toLocaleDateString("fr-FR")}`,
            template_id: templateId,
            template_name: templateName,
            template_language: templateLanguage,
            audience_filter: filter,
          });
          campaignId = draft.id;
          onDraftCreated(draft.id);
        } catch {
          setPreviewLoading(false);
          return;
        }
      } else {
        // Update existing draft
        try {
          await updateCampaign.mutateAsync({
            id: campaignId,
            data: { audience_filter: filter },
          });
        } catch {
          setPreviewLoading(false);
          return;
        }
      }

      // Fetch audience preview
      try {
        const result = await audiencePreview.mutateAsync(campaignId);
        setPreview(result);
      } catch {
        // Silently fail — preview is optional
      }
      setPreviewLoading(false);
    }, 300);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTags.join(","), selectedLanguage]);

  function toggleTag(tag: string) {
    const current = selectedTags;
    const next = current.includes(tag)
      ? current.filter((t) => t !== tag)
      : [...current, tag];
    setValue("audience_tags", next, { shouldValidate: true });
  }

  function handleLanguageChange(value: string) {
    setValue("audience_language", value);
  }

  return (
    <div className="space-y-6">
      {/* Tags selection */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground">
          Tags de ciblage
        </h3>
        {errors.audience_tags && (
          <p className="text-xs text-destructive">
            Sélectionnez au moins un critère
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_TAGS.map((tag) => {
            const isSelected = selectedTags.includes(tag);
            return (
              <Badge
                key={tag}
                variant={isSelected ? "default" : "outline"}
                className={cn(
                  "cursor-pointer select-none transition-colors",
                  isSelected && "bg-primary hover:bg-primary/90"
                )}
                onClick={() => toggleTag(tag)}
              >
                {tag.replace(/_/g, " ")}
                {isSelected && <X className="ms-1 h-3 w-3" />}
              </Badge>
            );
          })}
        </div>
      </div>

      {/* Language filter */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground">
          Langue (optionnel)
        </h3>
        <Select value={selectedLanguage} onValueChange={handleLanguageChange}>
          <SelectTrigger className="w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languageOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Audience count preview */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2">
              <Users className="h-5 w-5 text-primary" strokeWidth={1.75} />
            </div>
            <div>
              {previewLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Calcul en cours…
                </div>
              ) : preview ? (
                <>
                  <p className="text-2xl font-heading font-bold">
                    {preview.count.toLocaleString("fr-FR")}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    contacts correspondant à vos critères
                  </p>
                </>
              ) : selectedTags.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Sélectionnez des critères pour voir l&apos;audience estimée
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Estimation en attente…
                </p>
              )}
            </div>
          </div>

          {/* Sample contacts */}
          {preview && preview.sample.length > 0 && (
            <div className="mt-4 border-t pt-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground">
                Échantillon
              </p>
              <div className="space-y-1.5">
                {preview.sample.map((contact, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                  >
                    <div className="h-5 w-5 rounded-full bg-muted flex items-center justify-center text-[10px] font-medium">
                      {String(contact.name ?? "?").charAt(0).toUpperCase()}
                    </div>
                    <span>{String(contact.name ?? "Inconnu")}</span>
                    <span className="font-mono text-[10px]">
                      {String(contact.phone ?? "")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
