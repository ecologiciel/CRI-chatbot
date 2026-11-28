"use client";

import { useId, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiClient } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api-client";
import type { TenantRecord } from "@/types/super-admin";

export function WhatsAppChannelDialog({ tenant }: { tenant: TenantRecord }) {
  const api = useApiClient();
  const queryClient = useQueryClient();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [account, setAccount] = useState("");
  const [access, setAccess] = useState("");
  const [verification, setVerification] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function clear() {
    setPhone(""); setAccount(""); setAccess(""); setVerification(""); setSecret(""); setError("");
  }

  function changeOpen(value: boolean) {
    if (submitting) return;
    if (!value) clear();
    setOpen(value);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^[0-9]{1,32}$/.test(phone) || (account && !/^[0-9]{1,32}$/.test(account))) {
      setError("Les identifiants Meta doivent contenir uniquement des chiffres.");
      return;
    }
    if (!access.trim() || !verification.trim() || !secret.trim()) {
      setError("Renseignez tous les identifiants secrets.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.put(`/tenants/${tenant.id}/whatsapp-channel`, {
        phone_number_id: phone, business_account_id: account,
        access_token: access, verify_token: verification, app_secret: secret,
      });
      clear();
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["sa-tenants-health"] });
      toast.success("Identifiants enregistrés. La connexion Meta reste à vérifier.");
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 409
        ? "Ce numéro est déjà associé à une autre institution."
        : cause instanceof ApiError && cause.status === 422
          ? "Vérifiez les identifiants saisis."
          : "Enregistrement impossible. Vérifiez votre accès et réessayez.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>Configurer WhatsApp</Button>
      <Dialog open={open} onOpenChange={changeOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>WhatsApp — {tenant.name}</DialogTitle>
            <DialogDescription>Renseignez les identifiants propres à cette institution. Les secrets existants ne sont jamais affichés ; une modification exige leur nouvelle saisie.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-4" autoComplete="off">
            <div className="space-y-2"><Label htmlFor={`${id}-phone`}>Identifiant du numéro Meta</Label><Input id={`${id}-phone`} inputMode="numeric" pattern="[0-9]{1,32}" required maxLength={32} value={phone} onChange={(event) => setPhone(event.target.value)} /></div>
            <div className="space-y-2"><Label htmlFor={`${id}-account`}>Identifiant du compte professionnel Meta (facultatif)</Label><Input id={`${id}-account`} inputMode="numeric" pattern="[0-9]{1,32}" maxLength={32} value={account} onChange={(event) => setAccount(event.target.value)} /></div>
            <div className="space-y-2"><Label htmlFor={`${id}-access`}>Jeton d’accès</Label><Input id={`${id}-access`} type="password" autoComplete="new-password" required maxLength={4096} value={access} onChange={(event) => setAccess(event.target.value)} /></div>
            <div className="space-y-2"><Label htmlFor={`${id}-verification`}>Jeton de vérification du webhook</Label><Input id={`${id}-verification`} type="password" autoComplete="new-password" required maxLength={4096} value={verification} onChange={(event) => setVerification(event.target.value)} /></div>
            <div className="space-y-2"><Label htmlFor={`${id}-secret`}>Secret de l’application Meta</Label><Input id={`${id}-secret`} type="password" autoComplete="new-password" required maxLength={4096} value={secret} onChange={(event) => setSecret(event.target.value)} /></div>
            <p className="text-sm text-muted-foreground">Les réglages de notification sont conservés. L’enregistrement ne vérifie pas la connexion à Meta ; la réception doit être activée séparément.</p>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <DialogFooter><Button type="submit" disabled={submitting}>{submitting ? "Enregistrement…" : "Enregistrer les identifiants"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
