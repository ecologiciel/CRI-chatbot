import { cn } from "@/lib/utils";

const labels: Record<string, string> = {
  unconfirmed: "Envoi WhatsApp non confirmé",
  accepted: "Accepté par WhatsApp · livraison non confirmée",
  sent: "Envoyé selon WhatsApp · livraison non confirmée",
  delivered: "Distribué selon WhatsApp",
  read: "Lu selon WhatsApp",
  failed: "Échec signalé par WhatsApp",
};

export function DeliveryStatus({ state, reviewRequired }: {
  state?: string | null;
  reviewRequired?: boolean | null;
}) {
  if (reviewRequired) {
    return <p className="text-xs text-destructive mt-1">Statut WhatsApp contradictoire ou non reconnu · examen nécessaire</p>;
  }
  if (!state || !labels[state]) return null;
  return <p className={cn("text-xs mt-1", state === "failed" || state === "unconfirmed" ? "text-destructive" : "text-muted-foreground")}>{labels[state]}</p>;
}
