"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    router.push("/dashboard");
  }

  return (
    <Card className="w-full max-w-[420px] shadow-elevated">
      <CardHeader className="items-center space-y-4 pb-2">
        <div className="flex items-center gap-3">
          <Building2 className="h-12 w-12 text-primary" strokeWidth={1.5} />
        </div>
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold font-heading">CRI Platform</h1>
          <p className="text-sm text-muted-foreground">
            Plateforme de gestion des chatbots
          </p>
        </div>
      </CardHeader>

      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="admin@cri-rsk.ma"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Mot de passe</Label>
            <Input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <Button type="submit" className="w-full">
            Se connecter
          </Button>
        </form>
      </CardContent>

      <CardFooter className="justify-center">
        <p className="text-xs text-muted-foreground">
          &copy; 2026 CRI Rabat-Salé-Kénitra
        </p>
      </CardFooter>
    </Card>
  );
}
