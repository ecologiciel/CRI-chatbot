"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient, useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ResponseInput } from "./response-input";
import { acquireReplyKey, readReplyKey, releaseReplyKey, replyStorageName } from "./reply-request-storage";

type ReplyState = "pending" | "processing" | "accepted" | "uncertain" | "follow_up" | "resolved" | "canceled";
type ReplyStatus = { id: string; state: ReplyState; outcome_code: string | null };
type ReplyResult = { id: string; state: ReplyState; created: boolean };

/** A disabled durable mode must not silently bypass unresolved work. */
export function LegacyReplyGuard({ escalationId }: { escalationId: string }) {
  const api = useApiClient();
  const { admin } = useAuth();
  const tenant = api.getTenantId();
  const name = tenant && admin?.id ? replyStorageName(tenant, admin.id, escalationId) : null;
  const [storageState, setStorageState] = useState<"checking" | "clear" | "blocked">("checking");
  const events = useQuery({
    queryKey: ["agent-reply-open", tenant, admin?.id, escalationId],
    queryFn: () => api.get<{ events: unknown[]; has_more: boolean }>(`/escalations/${escalationId}/reply-requests`),
    enabled: !!name,
    refetchInterval: 10_000,
    retry: false,
  });
  useEffect(() => {
    if (!name) return;
    let live = true;
    const check = async () => {
      try {
        const key = await readReplyKey(name);
        if (live) setStorageState(key ? "blocked" : "clear");
      } catch { if (live) setStorageState("blocked"); }
    };
    void check();
    const onStorage = (event: StorageEvent) => { if (event.key === name) void check(); };
    window.addEventListener("storage", onStorage);
    return () => { live = false; window.removeEventListener("storage", onStorage); };
  }, [name]);
  if (storageState !== "clear" || !events.isSuccess || events.isError || events.data.has_more || events.data.events.length) {
    return <p role="alert" className="border-t p-3 text-sm">Envoi suspendu : vérifiez les demandes précédentes et le mode de réponse avant de continuer.</p>;
  }
  return <ResponseInput escalationId={escalationId} />;
}

export function DurableReplyInput({ escalationId, maySend }: { escalationId: string; maySend: boolean }) {
  const api = useApiClient();
  const { admin } = useAuth();
  const tenant = api.getTenantId();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [requestKey, setRequestKey] = useState<string | null>(null);
  const [storageReady, setStorageReady] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef(false);
  const name = tenant && admin?.id ? replyStorageName(tenant, admin.id, escalationId) : null;
  const openKey = ["agent-reply-open", tenant, admin?.id, escalationId] as const;

  useEffect(() => {
    if (!name) return;
    let live = true;
    const load = async () => {
      try {
        const key = await readReplyKey(name);
        if (live) { setRequestKey(key); setStorageReady(true); }
      } catch {
        if (live) { setStorageError(true); setStorageReady(true); }
      }
    };
    void load();
    const onStorage = (event: StorageEvent) => { if (event.key === name) void load(); };
    window.addEventListener("storage", onStorage);
    return () => { live = false; window.removeEventListener("storage", onStorage); };
  }, [name]);

  const status = useQuery({
    queryKey: ["agent-reply-status", tenant, admin?.id, escalationId, requestKey],
    queryFn: () => api.get<ReplyStatus>(`/escalations/${escalationId}/reply-requests/${requestKey}`),
    enabled: !!requestKey,
    retry: false,
    refetchInterval: 5000,
  });
  const send = useMutation({
    retry: 0,
    mutationFn: ({ key, text }: { key: string; text: string }) => api.post<ReplyResult>(
      `/escalations/${escalationId}/reply-requests`, { request_key: key, message: text },
    ),
    onSuccess: () => {
      setMessage("");
      setNotice("Demande enregistrée. L’acceptation par la plateforme ne confirme pas la livraison.");
      void queryClient.invalidateQueries({ queryKey: openKey });
      void queryClient.invalidateQueries({ queryKey: ["agent-reply-status", tenant, admin?.id, escalationId] });
    },
    onError: () => {
      setNotice("Résultat non confirmé. Vérifiez le suivi ci-dessous avant toute nouvelle action ; conservez la même référence.");
      void queryClient.invalidateQueries({ queryKey: openKey });
      void queryClient.invalidateQueries({ queryKey: ["agent-reply-status", tenant, admin?.id, escalationId] });
    },
  });

  async function sendMessage() {
    const text = message.trim();
    if (!name || !text || !maySend || inFlight.current || send.isPending) return;
    const token = api.getAccessToken();
    if (!token || !tenant) return;
    inFlight.current = true;
    let key: string;
    try {
      key = await acquireReplyKey(name);
    } catch {
      setStorageError(true);
      inFlight.current = false;
      return;
    }
    setRequestKey(key);
    if (api.getAccessToken() !== token || api.getTenantId() !== tenant) {
      setNotice("La session a changé. Vérifiez la demande avant de continuer.");
      inFlight.current = false;
      return;
    }
    try {
      await send.mutateAsync({ key, text });
    } catch {
      // onError reports the ambiguous result; retain the same stored key.
    } finally {
      inFlight.current = false;
    }
  }

  async function clearTerminal() {
    if (!name || !requestKey || !status.data || !["accepted", "resolved", "canceled"].includes(status.data.state)) return;
    try {
      const remaining = await releaseReplyKey(name, requestKey);
      setRequestKey(remaining);
      setNotice(null);
    } catch { setStorageError(true); }
  }

  const missing = status.error instanceof ApiError && status.error.status === 404;
  const retryAllowed = !!requestKey && missing;
  const allowed = storageReady && !storageError && maySend && (!requestKey || retryAllowed);
  return <div className="space-y-2 rounded-md border p-3">
    <p className="font-medium">Répondre au citoyen</p>
    {storageError && <p role="alert">Le stockage de la référence ou la synchronisation entre onglets est indisponible. Envoi désactivé sur ce navigateur.</p>}
    {requestKey && <p>Référence de demande : <span className="font-mono">{requestKey}</span></p>}
    {status.data && <p role="status">État : {status.data.state}. {status.data.state === "accepted" && "Accepté par le fournisseur ; livraison non confirmée."}</p>}
    {requestKey && missing && <p role="alert">La demande est introuvable pour le moment. Si vous réessayez, saisissez exactement le même message : la même référence sera utilisée. Cela ne prouve pas que la première tentative a échoué.</p>}
    {requestKey && status.isError && !missing && <p role="alert">Impossible de vérifier la demande. Aucun nouvel envoi n’est autorisé tant que son état est inconnu.</p>}
    {notice && <p role="status">{notice}</p>}
    {status.data && ["accepted", "resolved", "canceled"].includes(status.data.state) && <Button variant="outline" size="sm" onClick={() => void clearTerminal()}>J’ai pris connaissance du résultat</Button>}
    <Textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={2} disabled={!allowed || send.isPending} placeholder={retryAllowed ? "Saisissez à nouveau le message identique" : "Tapez votre réponse…"} />
    <Button disabled={!allowed || !message.trim() || send.isPending} onClick={() => void sendMessage()}>{send.isPending ? "Enregistrement…" : retryAllowed ? "Réessayer avec la même référence" : "Enregistrer la réponse"}</Button>
  </div>;
}
