"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useDurableImportRequests } from "@/hooks/use-dossiers";

const labels: Record<string, string> = {
  pending: "En attente", processing: "En cours", completed: "Terminé",
  failed: "Échoué", uncertain: "À examiner",
};

export function ImportRequests({ enabled }: { enabled: boolean }) {
  const [state, setState] = useState("uncertain");
  const [offset, setOffset] = useState(0);
  const requests = useDurableImportRequests(state, offset, enabled);
  if (!enabled) return null;
  return (
    <Card><CardContent className="space-y-4 p-5">
      <div><h2 className="font-semibold">Suivi des imports</h2>
        <p className="text-sm text-muted-foreground">Retrouvez les demandes et examinez les résultats incertains avant toute nouvelle tentative.</p></div>
      {requests.isError && <p role="alert">Impossible de charger le suivi. <Button variant="outline" onClick={() => requests.refetch()}>Réessayer</Button></p>}
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
          {item.state === "uncertain" && <p role="status">{item.outcome_code === "configuration_changed" ? "Le paramétrage a changé après le dépôt." : "Résultat non confirmé."} Faites examiner cette demande par un administrateur.</p>}
          {item.state === "completed" && item.outcome_code === "completed_with_errors" && <p>Import terminé avec des erreurs : consultez les journaux de synchronisation.</p>}
        </div>)}
        <div className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Précédent</Button>
          <Button variant="outline" disabled={!requests.data.has_more || offset >= 10000} onClick={() => setOffset(offset + 25)}>Suivant</Button></div>
        {offset >= 10000 && requests.data.has_more && <p>Limite de navigation atteinte. Filtrez les demandes par statut.</p>}
      </>}
    </CardContent></Card>
  );
}
