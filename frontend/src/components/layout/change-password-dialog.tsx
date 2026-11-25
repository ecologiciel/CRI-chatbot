"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiClient, useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api-client";

export function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (value: boolean) => void }) {
  const api = useApiClient();
  const { endSession } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function changeOpen(value: boolean) {
    if (submitting) return;
    if (!value) { setCurrent(""); setNext(""); setConfirmation(""); setError(""); }
    onOpenChange(value);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirmation) { setError("Les nouveaux mots de passe ne correspondent pas."); return; }
    if (next.length < 12 || !/[A-Z]/.test(next) || !/\d/.test(next) || !/[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;'/`~]/.test(next)) {
      setError("Utilisez au moins 12 caractères, une majuscule, un chiffre et un caractère spécial.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.post<void>("/auth/change-password", { current_password: current, new_password: next });
      setCurrent(""); setNext(""); setConfirmation("");
      endSession();
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 422
        ? "Vérifiez le mot de passe actuel et choisissez un nouveau mot de passe différent."
        : cause instanceof ApiError && cause.status === 429
          ? "Trop de tentatives. Réessayez plus tard."
          : "Impossible de modifier le mot de passe. Réessayez.");
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Modifier le mot de passe</DialogTitle>
          <DialogDescription>Après modification, reconnectez-vous avec le nouveau mot de passe.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2"><Label htmlFor="current-password">Mot de passe actuel</Label><Input id="current-password" type="password" autoComplete="current-password" required maxLength={4096} value={current} onChange={(event) => setCurrent(event.target.value)} /></div>
          <div className="space-y-2"><Label htmlFor="new-password">Nouveau mot de passe</Label><Input id="new-password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={next} onChange={(event) => setNext(event.target.value)} /></div>
          <div className="space-y-2"><Label htmlFor="confirm-password">Confirmer le nouveau mot de passe</Label><Input id="confirm-password" type="password" autoComplete="new-password" required maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></div>
          <p className="text-xs text-muted-foreground">12 caractères minimum, dont une majuscule, un chiffre et un caractère spécial.</p>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <DialogFooter><Button type="submit" disabled={submitting}>{submitting ? "Modification…" : "Modifier le mot de passe"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
