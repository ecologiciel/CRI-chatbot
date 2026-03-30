"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { FileText, Users, Settings, Send, Check } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  useCreateCampaign,
  useUpdateCampaign,
  useLaunchCampaign,
  useScheduleCampaign,
} from "@/hooks/use-campaigns";
import { StepTemplate } from "./step-template";
import { StepAudience } from "./step-audience";
import { StepVariables } from "./step-variables";
import { StepSchedule } from "./step-schedule";
import type { CampaignWizardData } from "@/types/campaign";

// ---------------------------------------------------------------------------
// Validation schemas
// ---------------------------------------------------------------------------

const wizardSchema = z
  .object({
    // Step 1
    template_id: z.string().min(1, "Sélectionnez un template"),
    template_name: z.string().min(1),
    template_language: z.string().min(1),
    // Step 2
    audience_tags: z
      .array(z.string())
      .min(1, "Sélectionnez au moins un critère"),
    audience_language: z.string(),
    // Step 3
    variable_mapping: z.record(z.string(), z.string()),
    // Step 4
    name: z.string().min(1, "Le nom est requis").max(200),
    description: z.string(),
    send_mode: z.enum(["immediate", "scheduled"]),
    scheduled_at: z.string(),
  })
  .refine(
    (data) => {
      if (data.send_mode === "scheduled") {
        return data.scheduled_at.length > 0;
      }
      return true;
    },
    { message: "La date est requise", path: ["scheduled_at"] }
  );

// Fields to validate per step (used by trigger())
const STEP_FIELDS: Array<Array<keyof CampaignWizardData>> = [
  ["template_id", "template_name", "template_language"],
  ["audience_tags"],
  ["variable_mapping"],
  ["name", "send_mode", "scheduled_at"],
];

const STEPS = [
  { label: "Template", icon: FileText },
  { label: "Audience", icon: Users },
  { label: "Variables", icon: Settings },
  { label: "Envoi", icon: Send },
];

export function CampaignWizard() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [audienceCount, setAudienceCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const createCampaign = useCreateCampaign();
  const updateCampaign = useUpdateCampaign();
  const launchCampaign = useLaunchCampaign();
  const scheduleCampaign = useScheduleCampaign();

  const {
    register,
    setValue,
    watch,
    trigger,
    handleSubmit,
    formState: { errors },
  } = useForm<CampaignWizardData>({
    resolver: zodResolver(wizardSchema),
    defaultValues: {
      template_id: "",
      template_name: "",
      template_language: "fr",
      audience_tags: [],
      audience_language: "all",
      variable_mapping: {},
      name: "",
      description: "",
      send_mode: "immediate",
      scheduled_at: "",
    },
  });

  async function handleNext() {
    const fields = STEP_FIELDS[currentStep];
    const valid = await trigger(fields);
    if (valid) {
      setCurrentStep((prev) => Math.min(prev + 1, STEPS.length - 1));
    }
  }

  function handlePrev() {
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }

  async function onSubmit(data: CampaignWizardData) {
    setSubmitting(true);
    try {
      const filter: Record<string, unknown> = {};
      if (data.audience_tags.length > 0) filter.tags = data.audience_tags;
      if (data.audience_language !== "all")
        filter.language = data.audience_language;

      let campaignId = draftId;

      if (campaignId) {
        // Update the existing draft with final data
        await updateCampaign.mutateAsync({
          id: campaignId,
          data: {
            name: data.name,
            description: data.description || undefined,
            audience_filter: filter,
            variable_mapping: data.variable_mapping,
          },
        });
      } else {
        // Create new campaign
        const campaign = await createCampaign.mutateAsync({
          name: data.name,
          description: data.description || undefined,
          template_id: data.template_id,
          template_name: data.template_name,
          template_language: data.template_language,
          audience_filter: filter,
          variable_mapping: data.variable_mapping,
        });
        campaignId = campaign.id;
      }

      // Launch or schedule
      if (data.send_mode === "immediate") {
        await launchCampaign.mutateAsync(campaignId);
        toast.success("Campagne lancée avec succès");
      } else {
        await scheduleCampaign.mutateAsync({
          id: campaignId,
          scheduled_at: new Date(data.scheduled_at).toISOString(),
        });
        toast.success("Campagne planifiée avec succès");
      }

      router.push(`/campaigns/${campaignId}`);
    } catch {
      toast.error("Erreur lors de la création de la campagne");
    }
    setSubmitting(false);
  }

  function handleDraftCreated(id: string) {
    setDraftId(id);
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">
      {/* Stepper */}
      <nav className="flex items-center justify-center">
        {STEPS.map((step, index) => {
          const Icon = step.icon;
          const isActive = index === currentStep;
          const isCompleted = index < currentStep;

          return (
            <div key={step.label} className="flex items-center">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-full border-2 transition-colors",
                    isActive &&
                      "border-primary bg-primary text-primary-foreground",
                    isCompleted &&
                      "border-[hsl(var(--success))] bg-[hsl(var(--success))] text-white",
                    !isActive &&
                      !isCompleted &&
                      "border-muted-foreground/30 text-muted-foreground"
                  )}
                >
                  {isCompleted ? (
                    <Check className="h-4 w-4" strokeWidth={2.5} />
                  ) : (
                    <Icon className="h-4 w-4" strokeWidth={1.75} />
                  )}
                </div>
                <span
                  className={cn(
                    "text-xs font-medium",
                    isActive && "text-primary",
                    isCompleted && "text-[hsl(var(--success))]",
                    !isActive &&
                      !isCompleted &&
                      "text-muted-foreground"
                  )}
                >
                  {step.label}
                </span>
              </div>
              {index < STEPS.length - 1 && (
                <div
                  className={cn(
                    "mx-3 mt-[-1.25rem] h-0.5 w-12 sm:w-20",
                    index < currentStep
                      ? "bg-[hsl(var(--success))]"
                      : "bg-muted"
                  )}
                />
              )}
            </div>
          );
        })}
      </nav>

      {/* Step content */}
      <div className="min-h-[400px]">
        {currentStep === 0 && (
          <StepTemplate
            setValue={setValue}
            watch={watch}
            errors={errors}
          />
        )}
        {currentStep === 1 && (
          <StepAudience
            setValue={setValue}
            watch={watch}
            errors={errors}
            draftId={draftId}
            onDraftCreated={(id) => {
              handleDraftCreated(id);
              // Track audience count from the draft
              setAudienceCount(0);
            }}
          />
        )}
        {currentStep === 2 && (
          <StepVariables setValue={setValue} watch={watch} />
        )}
        {currentStep === 3 && (
          <StepSchedule
            register={register}
            setValue={setValue}
            watch={watch}
            errors={errors}
            audienceCount={audienceCount}
          />
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between border-t pt-6">
        <Button
          type="button"
          variant="outline"
          onClick={handlePrev}
          className={cn(currentStep === 0 && "invisible")}
        >
          Précédent
        </Button>

        {currentStep < STEPS.length - 1 ? (
          <Button type="button" onClick={handleNext}>
            Suivant
          </Button>
        ) : (
          <Button type="submit" disabled={submitting}>
            {submitting ? "Création…" : "Créer la campagne"}
          </Button>
        )}
      </div>
    </form>
  );
}
