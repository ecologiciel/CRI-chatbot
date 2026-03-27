"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { useAuth, ApiError } from "@/lib/auth-provider";

const loginSchema = z.object({
  email: z.string().email("Adresse email invalide"),
  password: z.string().min(1, "Mot de passe requis"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const router = useRouter();
  const { login, isAuthenticated, isLoading: authLoading } = useAuth();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  // If already authenticated, redirect to dashboard
  React.useEffect(() => {
    if (!authLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [authLoading, isAuthenticated, router]);

  async function onSubmit(data: LoginFormValues) {
    try {
      await login(data);
      router.push("/dashboard");
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 429) {
          toast.error("Compte verrouillé", {
            description:
              "Trop de tentatives échouées. Veuillez réessayer dans 30 minutes.",
          });
        } else if (error.status === 401) {
          toast.error("Identifiants invalides", {
            description: "Vérifiez votre email et mot de passe.",
          });
        } else {
          toast.error("Erreur de connexion", {
            description: error.message,
          });
        }
      } else {
        toast.error("Erreur de connexion", {
          description: "Impossible de contacter le serveur. Vérifiez votre connexion.",
        });
      }
    }
  }

  // Don't render the form while checking auth state
  if (authLoading) {
    return (
      <div className="flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
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
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="admin@cri-rsk.ma"
              autoComplete="email"
              {...register("email")}
            />
            {errors.email && (
              <p className="text-xs text-destructive">{errors.email.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Mot de passe</Label>
            <Input
              id="password"
              type="password"
              placeholder="••••••••"
              autoComplete="current-password"
              {...register("password")}
            />
            {errors.password && (
              <p className="text-xs text-destructive">
                {errors.password.message}
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Connexion en cours...
              </>
            ) : (
              "Se connecter"
            )}
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
