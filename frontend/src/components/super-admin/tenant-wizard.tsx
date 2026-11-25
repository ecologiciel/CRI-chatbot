"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateTenant } from "@/hooks/use-super-admin";

function institutionCode(name: string): string {
  const code = name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]/g, "").slice(0, 50);
  return /^[a-z]/.test(code) ? code : code ? `i${code}`.slice(0, 50) : "";
}

export function TenantWizard() {
  const router = useRouter();
  const createTenant = useCreateTenant();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [region, setRegion] = useState("National");
  const [codeEdited, setCodeEdited] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^[a-z][a-z0-9]{1,49}$/.test(slug)) {
      toast.error("Le code doit contenir 2 à 50 lettres minuscules ou chiffres et commencer par une lettre.");
      return;
    }
    try {
      await createTenant.mutateAsync({
        name: name.trim(), slug, region: region.trim(),
        is_demo: true, conversation_retention_days: 7,
        public_config: {
          web_enabled: true,
          disclaimer: "Prototype de démonstration non officiel. Vérifiez les informations auprès des canaux officiels de l’institution.",
        },
      });
      toast.success("Institution créée");
      router.push("/sa/tenants");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Création impossible");
    }
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader><CardTitle>Nouvelle démonstration</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="institution-name">Nom de l’institution</Label>
            <Input id="institution-name" required minLength={2} maxLength={255} value={name}
              onChange={(event) => { setName(event.target.value); if (!codeEdited) setSlug(institutionCode(event.target.value)); }} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="institution-code">Code de la démonstration</Label>
            <Input id="institution-code" required value={slug} maxLength={50}
              onChange={(event) => { setCodeEdited(true); setSlug(event.target.value); }} />
            <p className="text-sm text-muted-foreground">Lettres minuscules et chiffres, sans espaces. Ce code apparaîtra dans le lien du chatbot.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="institution-region">Zone couverte</Label>
            <Input id="institution-region" required minLength={2} maxLength={255} value={region}
              onChange={(event) => setRegion(event.target.value)} />
          </div>
          <p className="text-sm text-muted-foreground">Le chat web sera activé. Les conversations de démonstration seront conservées 7 jours.</p>
          <Button type="submit" disabled={createTenant.isPending}>
            {createTenant.isPending ? "Création…" : "Créer la démonstration"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
