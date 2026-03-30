"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { WhatsAppPreview } from "./whatsapp-preview";
import { TEMPLATES } from "./step-template";
import type { UseFormSetValue, UseFormWatch } from "react-hook-form";
import type { CampaignWizardData } from "@/types/campaign";
import { useState } from "react";

const CONTACT_FIELDS = [
  { value: "contact.name", label: "Nom du contact" },
  { value: "contact.phone", label: "Téléphone" },
  { value: "contact.cin", label: "CIN" },
  { value: "contact.language", label: "Langue" },
  { value: "custom", label: "Texte personnalisé" },
];

interface StepVariablesProps {
  setValue: UseFormSetValue<CampaignWizardData>;
  watch: UseFormWatch<CampaignWizardData>;
}

export function StepVariables({ setValue, watch }: StepVariablesProps) {
  const templateId = watch("template_id");
  const variableMapping = watch("variable_mapping") ?? {};
  const [customTexts, setCustomTexts] = useState<Record<string, string>>({});

  const template = TEMPLATES.find((t) => t.id === templateId);

  if (!template || template.variables.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16 text-center">
        <p className="text-sm text-muted-foreground">
          Ce template ne contient pas de variables à configurer
        </p>
      </div>
    );
  }

  function handleFieldChange(varKey: string, fieldValue: string) {
    const next = { ...variableMapping };
    if (fieldValue === "custom") {
      next[varKey] = `custom:${customTexts[varKey] ?? ""}`;
    } else {
      next[varKey] = fieldValue;
    }
    setValue("variable_mapping", next);
  }

  function handleCustomTextChange(varKey: string, text: string) {
    setCustomTexts((prev) => ({ ...prev, [varKey]: text }));
    const next = { ...variableMapping };
    next[varKey] = `custom:${text}`;
    setValue("variable_mapping", next);
  }

  // Resolve variable mapping for preview
  function resolvePreviewVariables(): Record<string, string> {
    if (!template) return {};
    const resolved: Record<string, string> = {};
    for (const varKey of template.variables) {
      const mapping = variableMapping[varKey];
      if (!mapping) continue;
      if (mapping.startsWith("custom:")) {
        resolved[varKey] = mapping.slice(7) || `[texte ${varKey}]`;
      } else {
        const field = CONTACT_FIELDS.find((f) => f.value === mapping);
        resolved[varKey] = field ? `[${field.label}]` : `[${mapping}]`;
      }
    }
    return resolved;
  }

  function getSelectedField(varKey: string): string {
    const mapping = variableMapping[varKey];
    if (!mapping) return "";
    if (mapping.startsWith("custom:")) return "custom";
    return mapping;
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Variable mapping form */}
      <div className="space-y-4">
        <h3 className="text-sm font-medium text-muted-foreground">
          Associez chaque variable à un champ contact
        </h3>
        {template.variables.map((varKey) => (
          <div key={varKey} className="space-y-2">
            <Label className="text-sm">
              Variable{" "}
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                {`{{${varKey}}}`}
              </span>
            </Label>
            <Select
              value={getSelectedField(varKey)}
              onValueChange={(val) => handleFieldChange(varKey, val)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Sélectionner un champ" />
              </SelectTrigger>
              <SelectContent>
                {CONTACT_FIELDS.map((field) => (
                  <SelectItem key={field.value} value={field.value}>
                    {field.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {getSelectedField(varKey) === "custom" && (
              <Input
                placeholder="Saisissez le texte"
                value={customTexts[varKey] ?? ""}
                onChange={(e) =>
                  handleCustomTextChange(varKey, e.target.value)
                }
              />
            )}
          </div>
        ))}
      </div>

      {/* Live preview */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground">
          Aperçu avec variables
        </h3>
        <WhatsAppPreview
          body={template.body}
          variables={resolvePreviewVariables()}
          headerText={template.header}
          footerText={template.footer}
          buttons={template.buttons}
        />
      </div>
    </div>
  );
}
