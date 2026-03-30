import { Settings, Construction } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export default function ConfigurationPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-heading">Configuration</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Paramètres globaux de la plateforme.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 text-center">
          <div className="flex items-center justify-center h-14 w-14 rounded-full bg-muted mb-4">
            <Construction className="h-7 w-7 text-muted-foreground" strokeWidth={1.5} />
          </div>
          <h2 className="text-lg font-semibold font-heading mb-1">
            En construction
          </h2>
          <p className="text-sm text-muted-foreground max-w-sm">
            La page de configuration globale sera disponible prochainement.
            Elle permettra de gérer les paramètres partagés entre tous les tenants.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
