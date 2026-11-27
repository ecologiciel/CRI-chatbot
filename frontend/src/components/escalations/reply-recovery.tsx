"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient, useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ResponseInput } from "./response-input";

type ReplyMode = { durable: boolean; worker_seen: boolean | null };
type ReplyEvent = {
  id: string;
  escalation_id: string;
  state: "pending" | "processing" | "uncertain" | "follow_up";
  created_at: string;
  mine: boolean;
};
type ReplyList = { has_more: boolean; events: ReplyEvent[] };
type Decision = "confirmed_delivered" | "confirmed_not_sent" | "unknown_no_retry";
type Review = { event: ReplyEvent; action: "follow_up" | "resolve"; decision?: Decision };

const labels: Record<ReplyEvent["state"], string> = {
  pending: "En attente", processing: "En cours", uncertain: "Résultat incertain", follow_up: "À suivre",
};
const decisions: { value: Decision; label: string }[] = [
  { value: "confirmed_delivered", label: "J’ai vérifié que le message a été livré" },
  { value: "confirmed_not_sent", label: "J’ai vérifié que le message n’a pas été envoyé" },
  { value: "unknown_no_retry", label: "Résultat inconnu, sans renvoi" },
];

/** No automatic resend: a review records the operator's declaration only. */
function RecoveryPanel({ escalationId, mode }: { escalationId: string; mode: ReplyMode }) {
  const api = useApiClient();
  const { admin } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = api.getTenantId();
  const [selected, setSelected] = useState<Review | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const queryKey = ["agent-reply-open", tenantId, admin?.id, escalationId] as const;
  const events = useQuery({
    queryKey,
    queryFn: () => api.get<ReplyList>(`/escalations/${escalationId}/reply-requests`),
    enabled: !!tenantId && !!admin?.id,
    refetchInterval: 10_000,
    retry: false,
  });
  const review = useMutation({
    retry: 0,
    mutationFn: ({ event, action, decision }: Review) => api.post(
      `/escalations/${event.escalation_id}/reply-requests/${event.id}/review`,
      { action, decision: decision ?? null },
    ),
    onSuccess: () => {
      setFeedback("Décision enregistrée. Elle ne constitue pas une preuve de livraison.");
      void queryClient.invalidateQueries({ queryKey });
    },
    onError: () => {
      setFeedback("Résultat de la décision non confirmé. Actualisez la liste avant toute nouvelle action.");
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  return <div className="shrink-0 border-t border-border px-4 py-3 space-y-3 text-sm">
    <p className="font-medium">Suivi des réponses de cette conversation</p>
    {mode.worker_seen !== true && <p role="alert">La disponibilité du traitement ne peut pas être confirmée ; des réponses peuvent rester en attente.</p>}
    <p className="text-muted-foreground">Un worker détecté ne confirme pas la livraison. L’envoi depuis cette interface est en cours de préparation.</p>
    {(!tenantId || !admin?.id || events.isError) && <p role="alert">Impossible de charger le suivi. Actualisez avant toute décision.</p>}
    {events.isLoading && <p>Chargement du suivi…</p>}
    {events.data?.events.length === 0 && <p>Aucune demande en cours ou à examiner.</p>}
    {events.data?.events.map((event) => <div key={event.id} className="rounded-md border p-3 space-y-2">
      <p>{labels[event.state]} · {new Date(event.created_at).toLocaleString("fr-FR")} {event.mine ? "· votre demande" : "· demande d’un autre agent"}</p>
      {event.escalation_id !== escalationId && <p>Demande liée à une autre escalade de cette conversation.</p>}
      {(event.state === "uncertain" || event.state === "follow_up") && <div className="flex flex-wrap gap-2">
        {event.state === "uncertain" && <Button variant="outline" size="sm" disabled={review.isPending || events.isError} onClick={() => setSelected({ event, action: "follow_up" })}>Placer en suivi</Button>}
        {decisions.map((decision) => <Button key={decision.value} variant="outline" size="sm" disabled={review.isPending || events.isError} onClick={() => setSelected({ event, action: "resolve", decision: decision.value })}>{decision.label}</Button>)}
      </div>}
    </div>)}
    {events.data?.has_more && <p role="alert">D’autres demandes existent ; cette liste est limitée. Faites examiner la conversation avant un nouvel envoi.</p>}
    {feedback && <p role="status">{feedback}</p>}
    <AlertDialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
      <AlertDialogContent><AlertDialogHeader>
        <AlertDialogTitle>Enregistrer cette décision ?</AlertDialogTitle>
        <AlertDialogDescription>Choix : {selected?.action === "follow_up" ? "placer en suivi" : decisions.find((decision) => decision.value === selected?.decision)?.label}. Cette déclaration sera journalisée ; elle ne prouve pas la livraison. Clôturer le suivi peut permettre le traitement de réponses déjà en attente dans cette conversation. Aucun renvoi de cette demande ne sera déclenché.</AlertDialogDescription>
      </AlertDialogHeader><AlertDialogFooter>
        <AlertDialogCancel>Annuler</AlertDialogCancel>
        <AlertDialogAction onClick={() => { if (selected) review.mutate(selected); setSelected(null); }}>Enregistrer</AlertDialogAction>
      </AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
  </div>;
}

export function EscalationReplyArea({ escalationId, active }: { escalationId: string; active: boolean }) {
  const api = useApiClient();
  const { admin } = useAuth();
  const tenantId = api.getTenantId();
  const mode = useQuery({
    queryKey: ["agent-reply-mode", tenantId, admin?.id],
    queryFn: () => api.get<ReplyMode>("/escalations/reply-mode"),
    enabled: !!tenantId && !!admin?.id,
    refetchInterval: 30_000,
    retry: false,
  });
  if (!tenantId || !admin?.id || mode.isError) return <p role="alert" className="border-t p-3 text-sm">Mode de réponse indisponible. Actualisez avant d’envoyer un message.</p>;
  if (!mode.data) return <p className="border-t p-3 text-sm">Vérification du mode de réponse…</p>;
  if (mode.data.durable) return <RecoveryPanel key={`${tenantId}:${admin.id}:${escalationId}`} escalationId={escalationId} mode={mode.data} />;
  return active ? <ResponseInput escalationId={escalationId} /> : null;
}
