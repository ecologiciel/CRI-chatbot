"use client";

import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { Loader2, AlertCircle } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useDossier } from "@/hooks/use-dossiers";
import { STATUT_CONFIG } from "@/types/dossier";
import { DossierTimeline } from "./dossier-timeline";

interface DossierDetailSheetProps {
  dossierId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-4 py-2">
      <span className="text-sm text-muted-foreground shrink-0">{label}</span>
      <span className="text-sm font-medium text-end">{value}</span>
    </div>
  );
}

export function DossierDetailSheet({
  dossierId,
  open,
  onOpenChange,
}: DossierDetailSheetProps) {
  const { data: dossier, isLoading, isError } = useDossier(dossierId);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[480px] overflow-y-auto">
        <SheetHeader className="pb-4">
          <SheetTitle className="font-heading">Détail du dossier</SheetTitle>
        </SheetHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : isError || !dossier ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <AlertCircle className="h-8 w-8 text-destructive mb-3" />
            <p className="text-sm text-muted-foreground">
              Impossible de charger le dossier
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Header — N° + statut badge */}
            <div className="flex items-center justify-between gap-3">
              <p className="text-lg font-bold font-heading font-mono">
                {dossier.numero}
              </p>
              <Badge
                className={cn(
                  "text-xs font-medium",
                  STATUT_CONFIG[dossier.statut].className,
                )}
              >
                {STATUT_CONFIG[dossier.statut].label}
              </Badge>
            </div>

            {/* Information section */}
            <div>
              <h3 className="text-sm font-semibold font-heading uppercase tracking-wide text-muted-foreground mb-2">
                Informations
              </h3>
              <div className="divide-y divide-border">
                <InfoRow label="Raison sociale" value={dossier.raison_sociale} />
                <InfoRow label="Type de projet" value={dossier.type_projet} />
                <InfoRow label="Région" value={dossier.region} />
                <InfoRow label="Secteur" value={dossier.secteur} />
                <InfoRow
                  label="Montant"
                  value={
                    dossier.montant_investissement
                      ? `${Number(dossier.montant_investissement).toLocaleString("fr-FR")} MAD`
                      : null
                  }
                />
                <InfoRow
                  label="Date de dépôt"
                  value={
                    dossier.date_depot
                      ? format(new Date(dossier.date_depot), "dd/MM/yyyy", { locale: fr })
                      : null
                  }
                />
                <InfoRow
                  label="Dernière MAJ"
                  value={
                    dossier.date_derniere_maj
                      ? format(new Date(dossier.date_derniere_maj), "dd/MM/yyyy", { locale: fr })
                      : null
                  }
                />
              </div>
            </div>

            {/* Observations */}
            {dossier.observations && (
              <div>
                <h3 className="text-sm font-semibold font-heading uppercase tracking-wide text-muted-foreground mb-2">
                  Observations
                </h3>
                <p className="text-sm text-foreground whitespace-pre-wrap">
                  {dossier.observations}
                </p>
              </div>
            )}

            <Separator />

            {/* Timeline */}
            <div>
              <h3 className="text-sm font-semibold font-heading uppercase tracking-wide text-muted-foreground mb-3">
                Historique des modifications
              </h3>
              <DossierTimeline history={dossier.history} />
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
