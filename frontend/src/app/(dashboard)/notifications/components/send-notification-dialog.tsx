"use client";

import { useState, useEffect, useRef } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Search, User, FileText, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useContacts } from "@/hooks/use-contacts";
import { useSendNotification } from "@/hooks/use-notifications";
import { useApiClient } from "@/hooks/use-auth";
import type { NotificationEventType } from "@/types/notification";

// ---------------------------------------------------------------------------
// Zod schema
// ---------------------------------------------------------------------------

const sendNotificationSchema = z.object({
  contact_id: z.string().uuid("Sélectionnez un contact"),
  dossier_id: z.string().uuid("Sélectionnez un dossier"),
  event_type: z.enum(
    [
      "decision_finale",
      "complement_request",
      "status_update",
      "dossier_incomplet",
    ],
    { message: "Type d'événement requis" },
  ),
});

type FormValues = z.infer<typeof sendNotificationSchema>;

// ---------------------------------------------------------------------------
// Event type labels
// ---------------------------------------------------------------------------

const EVENT_TYPE_OPTIONS: { value: NotificationEventType; label: string }[] = [
  { value: "decision_finale", label: "Décision finale" },
  { value: "complement_request", label: "Demande de complément" },
  { value: "status_update", label: "Mise à jour du statut" },
  { value: "dossier_incomplet", label: "Dossier incomplet" },
];

// ---------------------------------------------------------------------------
// Dossier search hook (minimal, uses existing API)
// ---------------------------------------------------------------------------

interface DossierSearchItem {
  id: string;
  numero: string;
  statut: string;
}

function useDossierSearch(search: string) {
  const api = useApiClient();
  const [results, setResults] = useState<DossierSearchItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (search.length < 2) {
      setResults([]);
      return;
    }

    let cancelled = false;
    setIsLoading(true);

    api
      .get<{ items: DossierSearchItem[] }>("/dossiers", {
        search,
        page_size: 10,
      })
      .then((data) => {
        if (!cancelled) setResults(data.items);
      })
      .catch(() => {
        if (!cancelled) setResults([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [search, api]);

  return { results, isLoading };
}

// ---------------------------------------------------------------------------
// Searchable picker component
// ---------------------------------------------------------------------------

interface SearchablePickerProps {
  label: string;
  placeholder: string;
  icon: React.ReactNode;
  selectedLabel: string | null;
  onClear: () => void;
  searchValue: string;
  onSearchChange: (val: string) => void;
  isLoading: boolean;
  children: React.ReactNode;
  showDropdown: boolean;
  error?: string;
}

function SearchablePicker({
  label,
  placeholder,
  icon,
  selectedLabel,
  onClear,
  searchValue,
  onSearchChange,
  isLoading,
  children,
  showDropdown,
  error,
}: SearchablePickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  return (
    <div className="space-y-2" ref={containerRef}>
      <Label>{label}</Label>
      {selectedLabel ? (
        <div className="flex items-center gap-2 rounded-md border px-3 py-2 bg-muted/30">
          {icon}
          <span className="flex-1 text-sm truncate">{selectedLabel}</span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={onClear}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      ) : (
        <div className="relative">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={placeholder}
            value={searchValue}
            onChange={(e) => onSearchChange(e.target.value)}
            className="ps-9"
          />
          {isLoading && (
            <Loader2 className="absolute end-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
          )}
          {showDropdown && (
            <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-elevated max-h-48 overflow-y-auto">
              {children}
            </div>
          )}
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main dialog
// ---------------------------------------------------------------------------

interface SendNotificationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SendNotificationDialog({
  open,
  onOpenChange,
}: SendNotificationDialogProps) {
  const sendMutation = useSendNotification();

  const {
    setValue,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(sendNotificationSchema),
    defaultValues: {
      contact_id: "",
      dossier_id: "",
      event_type: undefined,
    },
  });

  // Contact search state
  const [contactSearch, setContactSearch] = useState("");
  const [contactLabel, setContactLabel] = useState<string | null>(null);
  const [contactDebounced, setContactDebounced] = useState("");

  // Dossier search state
  const [dossierSearch, setDossierSearch] = useState("");
  const [dossierLabel, setDossierLabel] = useState<string | null>(null);
  const [dossierDebounced, setDossierDebounced] = useState("");

  // Debounce contact search
  useEffect(() => {
    const t = setTimeout(() => setContactDebounced(contactSearch), 300);
    return () => clearTimeout(t);
  }, [contactSearch]);

  // Debounce dossier search
  useEffect(() => {
    const t = setTimeout(() => setDossierDebounced(dossierSearch), 300);
    return () => clearTimeout(t);
  }, [dossierSearch]);

  // Fetch contacts
  const { data: contactsData, isLoading: contactsLoading } = useContacts(
    contactDebounced.length >= 2
      ? { search: contactDebounced, page_size: 10 }
      : undefined,
  );

  // Fetch dossiers
  const { results: dossierResults, isLoading: dossiersLoading } =
    useDossierSearch(dossierDebounced);

  const eventType = watch("event_type");

  function resetForm() {
    reset();
    setContactSearch("");
    setContactLabel(null);
    setDossierSearch("");
    setDossierLabel(null);
  }

  async function onSubmit(data: FormValues) {
    try {
      const result = await sendMutation.mutateAsync(data);

      if (result.status === "sent") {
        toast.success("Notification envoyée avec succès");
        resetForm();
        onOpenChange(false);
      } else if (result.status === "skipped") {
        toast.warning(`Notification ignorée : ${result.reason ?? "raison inconnue"}`);
      } else {
        toast.error(`Échec de l'envoi : ${result.reason ?? "erreur inconnue"}`);
      }
    } catch {
      toast.error("Erreur lors de l'envoi de la notification");
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(val) => {
        if (!val) resetForm();
        onOpenChange(val);
      }}
    >
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle className="font-heading">
            Envoyer une notification
          </DialogTitle>
          <DialogDescription>
            Envoyez une notification WhatsApp manuelle à un investisseur.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Contact picker */}
          <SearchablePicker
            label="Contact"
            placeholder="Rechercher un contact..."
            icon={<User className="h-4 w-4 text-muted-foreground" />}
            selectedLabel={contactLabel}
            onClear={() => {
              setValue("contact_id", "");
              setContactLabel(null);
              setContactSearch("");
            }}
            searchValue={contactSearch}
            onSearchChange={setContactSearch}
            isLoading={contactsLoading}
            showDropdown={
              contactDebounced.length >= 2 &&
              !contactLabel &&
              (contactsData?.items?.length ?? 0) > 0
            }
            error={errors.contact_id?.message}
          >
            {contactsData?.items?.map((c) => (
              <button
                key={c.id}
                type="button"
                className="w-full text-start px-3 py-2 hover:bg-muted/50 text-sm"
                onClick={() => {
                  setValue("contact_id", c.id, { shouldValidate: true });
                  setContactLabel(
                    `${c.name || "Sans nom"} — ${c.phone}`,
                  );
                  setContactSearch("");
                }}
              >
                <span className="font-medium">{c.name || "Sans nom"}</span>
                <span className="text-muted-foreground ms-2 font-mono text-xs">
                  {c.phone}
                </span>
              </button>
            ))}
          </SearchablePicker>

          {/* Dossier picker */}
          <SearchablePicker
            label="Dossier"
            placeholder="Rechercher un dossier (numéro)..."
            icon={<FileText className="h-4 w-4 text-muted-foreground" />}
            selectedLabel={dossierLabel}
            onClear={() => {
              setValue("dossier_id", "");
              setDossierLabel(null);
              setDossierSearch("");
            }}
            searchValue={dossierSearch}
            onSearchChange={setDossierSearch}
            isLoading={dossiersLoading}
            showDropdown={
              dossierDebounced.length >= 2 &&
              !dossierLabel &&
              dossierResults.length > 0
            }
            error={errors.dossier_id?.message}
          >
            {dossierResults.map((d) => (
              <button
                key={d.id}
                type="button"
                className="w-full text-start px-3 py-2 hover:bg-muted/50 text-sm"
                onClick={() => {
                  setValue("dossier_id", d.id, { shouldValidate: true });
                  setDossierLabel(`${d.numero} — ${d.statut}`);
                  setDossierSearch("");
                }}
              >
                <span className="font-medium font-mono">{d.numero}</span>
                <span className="text-muted-foreground ms-2 text-xs">
                  {d.statut}
                </span>
              </button>
            ))}
          </SearchablePicker>

          {/* Event type */}
          <div className="space-y-2">
            <Label>Type d&apos;événement</Label>
            <Select
              value={eventType}
              onValueChange={(v) =>
                setValue("event_type", v as NotificationEventType, {
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Sélectionner un type" />
              </SelectTrigger>
              <SelectContent>
                {EVENT_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.event_type && (
              <p className="text-xs text-destructive">
                {errors.event_type.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                resetForm();
                onOpenChange(false);
              }}
            >
              Annuler
            </Button>
            <Button type="submit" disabled={sendMutation.isPending}>
              {sendMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 me-2 animate-spin" />
                  Envoi...
                </>
              ) : (
                "Envoyer"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
