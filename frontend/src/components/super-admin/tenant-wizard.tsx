"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Building,
  MessageSquare,
  Palette,
  Check,
  Eye,
  EyeOff,
  Upload,
  X,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useCreateTenant } from "@/hooks/use-super-admin";
import { REGIONS_MAROC } from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const wizardSchema = z.object({
  // Step 1
  name: z.string().min(3, "Le nom doit contenir au moins 3 caractères").max(100),
  slug: z
    .string()
    .min(2, "Le slug doit contenir au moins 2 caractères")
    .max(50)
    .regex(/^[a-z0-9][a-z0-9-]*$/, "Slug invalide (minuscules, chiffres, tirets)"),
  region: z.string().min(1, "Sélectionnez une région"),
  // Step 2
  whatsapp_phone_number_id: z.string().min(1, "Phone Number ID requis"),
  whatsapp_access_token: z.string().min(1, "Access Token requis"),
  whatsapp_app_secret: z.string().min(1, "App Secret requis"),
  // Step 3
  accent_color: z.string().regex(/^#[0-9a-fA-F]{6}$/, "Couleur hexadécimale invalide"),
});

type WizardData = z.infer<typeof wizardSchema>;

const STEP_FIELDS: Array<Array<keyof WizardData>> = [
  ["name", "slug", "region"],
  ["whatsapp_phone_number_id", "whatsapp_access_token", "whatsapp_app_secret"],
  ["accent_color"],
];

const STEPS = [
  { label: "Informations", icon: Building },
  { label: "WhatsApp", icon: MessageSquare },
  { label: "Personnalisation", icon: Palette },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

// ---------------------------------------------------------------------------
// TenantWizard
// ---------------------------------------------------------------------------

export function TenantWizard() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const createTenant = useCreateTenant();

  const {
    register,
    setValue,
    watch,
    trigger,
    handleSubmit,
    formState: { errors },
  } = useForm<WizardData>({
    resolver: zodResolver(wizardSchema),
    defaultValues: {
      name: "",
      slug: "",
      region: "",
      whatsapp_phone_number_id: "",
      whatsapp_access_token: "",
      whatsapp_app_secret: "",
      accent_color: "#C4704B",
    },
  });

  const watchedName = watch("name");
  const watchedSlug = watch("slug");
  const watchedRegion = watch("region");
  const watchedAccent = watch("accent_color");

  // Auto-generate slug from name
  function handleNameChange(e: React.ChangeEvent<HTMLInputElement>) {
    const name = e.target.value;
    setValue("name", name);
    setValue("slug", slugify(name));
  }

  // Logo upload
  function handleLogoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate type
    if (!["image/png", "image/svg+xml"].includes(file.type)) {
      toast.error("Format accepté : PNG ou SVG");
      return;
    }

    // Validate size (500KB)
    if (file.size > 500 * 1024) {
      toast.error("Taille maximale : 500 KB");
      return;
    }

    setLogoFile(file);
    const url = URL.createObjectURL(file);
    setLogoPreview(url);
  }

  function removeLogo() {
    setLogoFile(null);
    if (logoPreview) {
      URL.revokeObjectURL(logoPreview);
      setLogoPreview(null);
    }
  }

  // Navigation
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

  // Submit
  async function onSubmit(data: WizardData) {
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("name", data.name);
      formData.append("slug", data.slug);
      formData.append("region", data.region);
      formData.append("whatsapp_phone_number_id", data.whatsapp_phone_number_id);
      formData.append("whatsapp_access_token", data.whatsapp_access_token);
      formData.append("whatsapp_app_secret", data.whatsapp_app_secret);
      formData.append("accent_color", data.accent_color);
      if (logoFile) {
        formData.append("logo_file", logoFile);
      }

      await createTenant.mutateAsync(formData);
      toast.success("Tenant créé avec succès");
      router.push("/sa/tenants");
    } catch {
      toast.error("Erreur lors de la création du tenant");
    }
    setSubmitting(false);
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
                    isActive && "border-primary bg-primary text-primary-foreground",
                    isCompleted && "border-[hsl(var(--success))] bg-[hsl(var(--success))] text-white",
                    !isActive && !isCompleted && "border-muted-foreground/30 text-muted-foreground"
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
                    !isActive && !isCompleted && "text-muted-foreground"
                  )}
                >
                  {step.label}
                </span>
              </div>
              {index < STEPS.length - 1 && (
                <div
                  className={cn(
                    "mx-3 mt-[-1.25rem] h-0.5 w-12 sm:w-20",
                    index < currentStep ? "bg-[hsl(var(--success))]" : "bg-muted"
                  )}
                />
              )}
            </div>
          );
        })}
      </nav>

      {/* Step content */}
      <div className="min-h-[400px]">
        {/* ── Step 1: Informations ───────────────────────────────────────────── */}
        {currentStep === 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-heading">
                Informations du tenant
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Nom */}
              <div className="space-y-2">
                <Label htmlFor="name">Nom du CRI *</Label>
                <Input
                  id="name"
                  placeholder="Ex: CRI Tanger-Tétouan-Al Hoceima"
                  {...register("name")}
                  onChange={handleNameChange}
                />
                {errors.name && (
                  <p className="text-xs text-destructive">{errors.name.message}</p>
                )}
              </div>

              {/* Slug */}
              <div className="space-y-2">
                <Label htmlFor="slug">Slug (identifiant technique) *</Label>
                <Input
                  id="slug"
                  placeholder="cri-tanger-tetouan-al-hoceima"
                  className="font-mono text-sm"
                  {...register("slug")}
                />
                {watchedSlug && (
                  <p className="text-xs text-muted-foreground font-mono">
                    tenant_{watchedSlug}
                  </p>
                )}
                {errors.slug && (
                  <p className="text-xs text-destructive">{errors.slug.message}</p>
                )}
              </div>

              {/* Région */}
              <div className="space-y-2">
                <Label>Région *</Label>
                <Select
                  value={watchedRegion}
                  onValueChange={(val) => setValue("region", val)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Sélectionnez une région" />
                  </SelectTrigger>
                  <SelectContent>
                    {REGIONS_MAROC.map((region) => (
                      <SelectItem key={region} value={region}>
                        {region}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {errors.region && (
                  <p className="text-xs text-destructive">{errors.region.message}</p>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Step 2: Configuration WhatsApp ─────────────────────────────────── */}
        {currentStep === 1 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-heading">
                Configuration WhatsApp
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Phone Number ID */}
              <div className="space-y-2">
                <Label htmlFor="phone_id">Phone Number ID *</Label>
                <Input
                  id="phone_id"
                  placeholder="1234567890"
                  {...register("whatsapp_phone_number_id")}
                />
                {errors.whatsapp_phone_number_id && (
                  <p className="text-xs text-destructive">
                    {errors.whatsapp_phone_number_id.message}
                  </p>
                )}
              </div>

              {/* Access Token */}
              <div className="space-y-2">
                <Label htmlFor="token">Access Token *</Label>
                <div className="relative">
                  <Input
                    id="token"
                    type={showToken ? "text" : "password"}
                    placeholder="EAAxxxxxxx..."
                    className="pe-10"
                    {...register("whatsapp_access_token")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken((v) => !v)}
                    className="absolute end-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showToken ? "Masquer" : "Afficher"}
                  >
                    {showToken ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                {errors.whatsapp_access_token && (
                  <p className="text-xs text-destructive">
                    {errors.whatsapp_access_token.message}
                  </p>
                )}
              </div>

              {/* App Secret */}
              <div className="space-y-2">
                <Label htmlFor="secret">App Secret *</Label>
                <div className="relative">
                  <Input
                    id="secret"
                    type={showSecret ? "text" : "password"}
                    placeholder="xxxxxxxxxxxxxxxx"
                    className="pe-10"
                    {...register("whatsapp_app_secret")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowSecret((v) => !v)}
                    className="absolute end-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showSecret ? "Masquer" : "Afficher"}
                  >
                    {showSecret ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                {errors.whatsapp_app_secret && (
                  <p className="text-xs text-destructive">
                    {errors.whatsapp_app_secret.message}
                  </p>
                )}
              </div>

              <p className="text-xs text-muted-foreground">
                Ces informations sont disponibles dans votre Meta Business Manager.
              </p>
            </CardContent>
          </Card>
        )}

        {/* ── Step 3: Personnalisation + Review ──────────────────────────────── */}
        {currentStep === 2 && (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg font-heading">
                  Personnalisation
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Logo upload */}
                <div className="space-y-2">
                  <Label>Logo (optionnel)</Label>
                  <p className="text-xs text-muted-foreground">
                    SVG ou PNG, max 200x60px, 500 KB
                  </p>
                  {logoPreview ? (
                    <div className="flex items-center gap-3 p-3 border rounded-lg bg-muted/30">
                      {/* eslint-disable-next-line @next/next/no-img-element -- blob URL preview, not optimizable */}
                      <img
                        src={logoPreview}
                        alt="Aperçu logo"
                        className="h-10 max-w-[160px] object-contain"
                      />
                      <span className="text-xs text-muted-foreground flex-1 truncate">
                        {logoFile?.name}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={removeLogo}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  ) : (
                    <label className="flex flex-col items-center justify-center h-24 border-2 border-dashed rounded-lg cursor-pointer hover:bg-muted/30 transition-colors">
                      <Upload className="h-5 w-5 text-muted-foreground mb-1" />
                      <span className="text-xs text-muted-foreground">
                        Cliquez ou glissez un fichier
                      </span>
                      <input
                        type="file"
                        accept=".svg,.png,image/svg+xml,image/png"
                        className="hidden"
                        onChange={handleLogoChange}
                      />
                    </label>
                  )}
                </div>

                {/* Color picker */}
                <div className="space-y-2">
                  <Label htmlFor="accent">Couleur accent</Label>
                  <div className="flex items-center gap-3">
                    <input
                      type="color"
                      id="accent"
                      value={watchedAccent}
                      onChange={(e) => setValue("accent_color", e.target.value)}
                      className="h-9 w-12 rounded border cursor-pointer"
                    />
                    <Input
                      value={watchedAccent}
                      onChange={(e) => setValue("accent_color", e.target.value)}
                      className="w-28 font-mono text-sm"
                      maxLength={7}
                    />
                    <div
                      className="h-9 w-9 rounded-md border"
                      style={{ backgroundColor: watchedAccent }}
                    />
                  </div>
                  {errors.accent_color && (
                    <p className="text-xs text-destructive">
                      {errors.accent_color.message}
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Review summary */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg font-heading">
                  Récapitulatif
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                  <span className="text-muted-foreground">Nom</span>
                  <span className="font-medium">{watchedName || "—"}</span>

                  <span className="text-muted-foreground">Slug</span>
                  <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded w-fit">
                    {watchedSlug || "—"}
                  </code>

                  <span className="text-muted-foreground">Région</span>
                  <span className="font-medium">{watchedRegion || "—"}</span>

                  <Separator className="col-span-2 my-1" />

                  <span className="text-muted-foreground">Phone Number ID</span>
                  <span className="font-mono text-xs">
                    {watch("whatsapp_phone_number_id") || "—"}
                  </span>

                  <span className="text-muted-foreground">Access Token</span>
                  <span className="font-mono text-xs">
                    {watch("whatsapp_access_token")
                      ? "••••••" + watch("whatsapp_access_token").slice(-4)
                      : "—"}
                  </span>

                  <span className="text-muted-foreground">App Secret</span>
                  <span className="font-mono text-xs">
                    {watch("whatsapp_app_secret")
                      ? "••••••" + watch("whatsapp_app_secret").slice(-4)
                      : "—"}
                  </span>

                  <Separator className="col-span-2 my-1" />

                  <span className="text-muted-foreground">Logo</span>
                  <span className="text-sm">
                    {logoFile ? logoFile.name : "Aucun"}
                  </span>

                  <span className="text-muted-foreground">Couleur accent</span>
                  <div className="flex items-center gap-2">
                    <div
                      className="h-4 w-4 rounded border"
                      style={{ backgroundColor: watchedAccent }}
                    />
                    <span className="font-mono text-xs">{watchedAccent}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
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
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin me-2" />
                Provisionnement...
              </>
            ) : (
              "Créer le tenant"
            )}
          </Button>
        )}
      </div>
    </form>
  );
}
