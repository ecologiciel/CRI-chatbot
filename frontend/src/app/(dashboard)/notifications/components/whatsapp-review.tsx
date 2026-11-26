"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";

type Kind = "message" | "status";
type ReviewState = "uncertain" | "follow_up";
type Event = { id: string; state: string; attempts: number; created_at: string; redacted_at: string | null };
type Detail = { id: string; provider_message_id: string; recipient_masked: string; event_type: string; view: string };

export function WhatsAppReview() {
  const api = useApiClient();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<Kind>("message");
  const [state, setState] = useState<ReviewState>("uncertain");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<{ id: string; action: "follow_up" | "resolve" } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const availability = useQuery({
    queryKey: ["wa-operations", "availability"],
    queryFn: () => api.get<{ intake_enabled: boolean }>("/whatsapp/operations/availability"),
  });
  const events = useQuery({
    queryKey: ["wa-operations", kind, state, offset],
    queryFn: () => api.get<{ events: Event[] }>("/whatsapp/operations/events", { kind, state, limit: 50, offset }),
  });
  const details = useMutation({
    mutationFn: async (id: string) => {
      const result = await api.get<Omit<Detail, "view">>(`/whatsapp/operations/events/${id}/detail`, { kind });
      return { ...result, view: `${kind}:${state}:${offset}` };
    },
    onSuccess: (data) => { setDetail(data); setMessage(null); },
    onError: () => setMessage("Impossible de consulter les détails. Réessayez."),
  });
  const review = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "follow_up" | "resolve" }) =>
      api.post(`/whatsapp/operations/events/${id}/review?kind=${kind}`, { action }),
    onSuccess: () => {
      setDetail(null);
      setMessage("Décision enregistrée. Aucun message n’a été renvoyé.");
      queryClient.invalidateQueries({ queryKey: ["wa-operations"] });
    },
    onError: () => setMessage("Décision non enregistrée. Actualisez la liste avant de réessayer."),
  });

  function changeView(nextKind: Kind, nextState: ReviewState) {
    setKind(nextKind); setState(nextState); setOffset(0); setDetail(null); setMessage(null);
  }

  return (
    <Card><CardContent className="space-y-4 p-5">
      <div>
        <h2 className="font-semibold">Suivi des événements WhatsApp</h2>
        <p className="text-sm text-muted-foreground">Examinez les traitements dont le résultat est incertain. Les consultations et décisions sont journalisées ; aucune action ici ne renvoie de message.</p>
      </div>
      {availability.isError && <p role="alert">Impossible de vérifier si la réception durable est activée.</p>}
      {availability.data && !availability.data.intake_enabled && <p role="status">La réception durable est désactivée. Les nouveaux événements ne sont pas enregistrés dans ce suivi.</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant={kind === "message" ? "default" : "outline"} onClick={() => changeView("message", state)}>Messages</Button>
        <Button variant={kind === "status" ? "default" : "outline"} onClick={() => changeView("status", state)}>Statuts de livraison</Button>
        <Button variant={state === "uncertain" ? "default" : "outline"} onClick={() => changeView(kind, "uncertain")}>À examiner</Button>
        <Button variant={state === "follow_up" ? "default" : "outline"} onClick={() => changeView(kind, "follow_up")}>À suivre</Button>
      </div>
      {message && <p role="status" className="text-sm">{message}</p>}
      {events.isLoading && <p>Chargement…</p>}
      {events.isError && <p role="alert">Impossible de charger les événements. <Button variant="outline" onClick={() => events.refetch()}>Réessayer</Button></p>}
      {events.data?.events.length === 0 && <p>Aucun événement dans cette page.</p>}
      {events.data?.events.map((event) => (
        <div key={event.id} className="flex flex-wrap items-center justify-between gap-3 border rounded-md p-3">
          <div className="text-sm"><p>Événement {event.id}</p><p className="text-muted-foreground">{new Date(event.created_at).toLocaleString("fr-FR")} · {event.attempts} tentative(s)</p>{event.redacted_at && <p>Détails expirés selon la durée de conservation.</p>}</div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={details.isPending || !!event.redacted_at} onClick={() => details.mutate(event.id)}>Voir les détails</Button>
            {state === "uncertain" && <Button variant="outline" disabled={review.isPending} onClick={() => setSelected({ id: event.id, action: "follow_up" })}>À suivre</Button>}
            <Button variant="outline" disabled={review.isPending} onClick={() => setSelected({ id: event.id, action: "resolve" })}>Clôturer le suivi</Button>
          </div>
        </div>
      ))}
      {detail && detail.view === `${kind}:${state}:${offset}` && <div className="rounded-md border p-3 text-sm" aria-live="polite">
        <p>Événement : {detail.id}</p><p>Identifiant fournisseur : {detail.provider_message_id}</p>
        <p>Contact masqué : {detail.recipient_masked}</p><p>Type : {detail.event_type}</p>
        <p className="text-muted-foreground">Ces informations ne prouvent pas la livraison.</p>
        <Button variant="ghost" onClick={() => setDetail(null)}>Masquer</Button>
      </div>}
      <div className="flex gap-2">
        <Button variant="outline" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 50)); setDetail(null); }}>Précédent</Button>
        <Button variant="outline" disabled={(events.data?.events.length ?? 0) < 50} onClick={() => { setOffset(offset + 50); setDetail(null); }}>Suivant</Button>
      </div>
      <AlertDialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
        <AlertDialogContent><AlertDialogHeader>
          <AlertDialogTitle>{selected?.action === "follow_up" ? "Placer en suivi ?" : "Clôturer le suivi ?"}</AlertDialogTitle>
          <AlertDialogDescription>Votre décision sera enregistrée dans le journal d’audit. Elle ne confirme pas la livraison et ne déclenche aucun renvoi.</AlertDialogDescription>
        </AlertDialogHeader><AlertDialogFooter>
          <AlertDialogCancel>Annuler</AlertDialogCancel>
          <AlertDialogAction onClick={() => { if (selected) review.mutate(selected); setSelected(null); }}>Enregistrer</AlertDialogAction>
        </AlertDialogFooter></AlertDialogContent>
      </AlertDialog>
    </CardContent></Card>
  );
}
