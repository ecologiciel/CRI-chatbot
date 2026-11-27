"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useDurableImportRequests } from "@/hooks/use-dossiers";
import { useApiClient } from "@/hooks/use-auth";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";

const labels: Record<string, string> = {
  pending: "En attente", processing: "En cours", completed: "Terminé",
  failed: "Échoué", uncertain: "À examiner",
};

export function ImportRequests({ enabled }: { enabled: boolean }) {
  const api = useApiClient();
  const queryClient = useQueryClient();
  const [state, setState] = useState("uncertain");
  const [offset, setOffset] = useState(0);
  const [selection, setSelection] = useState<{id: string; action: "follow_up" | "close_applied" | "close_not_applied"} | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const requests = useDurableImportRequests(state, offset, enabled);
  const review = useMutation({
    mutationFn: ({id, action}: {id: string; action: "follow_up" | "close_applied" | "close_not_applied"}) => api.post(`/dossiers/imports/${id}/review`, {action}),
    onSuccess: () => { setMessage("Décision enregistrée. Aucun import n’a été relancé."); queryClient.invalidateQueries({queryKey: ["dossier-import-requests"]}); },
    onError: () => { setMessage("Décision non enregistrée. Actualisez le suivi avant de réessayer."); queryClient.invalidateQueries({queryKey: ["dossier-import-requests"]}); },
  });
  if (!enabled) return null;
  return (
    <Card><CardContent className="space-y-4 p-5">
      <div><h2 className="font-semibold">Suivi des imports</h2>
        <p className="text-sm text-muted-foreground">Retrouvez les demandes et examinez les résultats incertains avant toute nouvelle tentative.</p></div>
      {requests.isError && <p role="alert">Impossible de charger le suivi. <Button variant="outline" onClick={() => requests.refetch()}>Réessayer</Button></p>}
      {message && <p role="status">{message}</p>}
      {requests.isLoading && <p>Chargement…</p>}
      {requests.data && !requests.data.active && <p role="status">Les nouveaux imports durables sont désactivés.</p>}
      {requests.data && !requests.data.available && <p>Le suivi durable n’est pas encore installé.</p>}
      {requests.data?.available && <>
        <label className="block text-sm">Statut {" "}
          <select className="rounded-md border bg-background p-2" value={state} onChange={(event) => { setState(event.target.value); setOffset(0); }}>
            <option value="">Tous</option>
            {Object.entries(labels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select>
        </label>
        {requests.data.items.length === 0 && <p>Aucune demande dans cette page.</p>}
        {requests.data.items.map((item) => <div key={item.request_id} className="rounded-md border p-3 text-sm">
          <p>Référence : {item.request_id}</p>
          <p>{labels[item.state]} · {new Date(item.created_at).toLocaleString("fr-FR")}</p>
          {item.state === "uncertain" && <p role="status">{item.outcome_code === "configuration_changed" ? "Le paramétrage a changé après le dépôt." : "Résultat technique non confirmé."} {item.review_state === "closed" ? "Le suivi administratif est clôturé." : "Faites examiner cette demande par un administrateur."}</p>}
          {item.state === "uncertain" && <div className="space-y-2 mt-2">
            <p>Suivi : {item.review_state === "closed" ? `clôturé — ${item.review_outcome === "applied" ? "effets constatés" : "aucun effet constaté"}` : item.review_state === "follow_up" ? "à suivre" : "à examiner"}</p>
            {item.review_state !== "closed" && <div className="flex flex-wrap gap-2">
              {item.review_state === "open" && <Button variant="outline" disabled={review.isPending} onClick={() => setSelection({id: item.request_id, action: "follow_up"})}>À suivre</Button>}
              <Button variant="outline" disabled={review.isPending} onClick={() => setSelection({id: item.request_id, action: "close_applied"})}>Clôturer : effets constatés</Button>
              <Button variant="outline" disabled={review.isPending} onClick={() => setSelection({id: item.request_id, action: "close_not_applied"})}>Clôturer : aucun effet constaté</Button>
            </div>}
          </div>}
          {item.state === "completed" && item.outcome_code === "completed_with_errors" && <p>Import terminé avec des erreurs : consultez les journaux de synchronisation.</p>}
        </div>)}
        <div className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Précédent</Button>
          <Button variant="outline" disabled={!requests.data.has_more || offset >= 10000} onClick={() => setOffset(offset + 25)}>Suivant</Button></div>
        {offset >= 10000 && requests.data.has_more && <p>Limite de navigation atteinte. Filtrez les demandes par statut.</p>}
      </>}
      <AlertDialog open={selection !== null} onOpenChange={(open) => { if (!open) setSelection(null); }}>
        <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Confirmer la décision</AlertDialogTitle>
          <AlertDialogDescription>{selection?.action === "follow_up" ? "La demande sera marquée à suivre." : selection?.action === "close_applied" ? "Vous confirmez avoir constaté les effets de cet import après vérification." : "Vous confirmez avoir vérifié qu’aucun effet de cet import n’a été constaté."} Cette décision est journalisée et ne relance pas l’import.</AlertDialogDescription>
        </AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Annuler</AlertDialogCancel><AlertDialogAction onClick={() => { if (selection) review.mutate(selection); setSelection(null); }}>Confirmer</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
      </AlertDialog>
    </CardContent></Card>
  );
}
