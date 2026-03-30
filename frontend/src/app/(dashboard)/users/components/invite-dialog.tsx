"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateAdmin } from "@/hooks/use-users";

const inviteSchema = z.object({
  email: z.string().email("Adresse email invalide"),
  full_name: z.string().min(1, "Nom requis"),
  password: z
    .string()
    .min(12, "12 caractères minimum")
    .regex(/[A-Z]/, "Au moins une majuscule")
    .regex(/\d/, "Au moins un chiffre")
    .regex(/[!@#$%^&*(),.?":{}|<>\-_=+[\]\\;'/`~]/, "Au moins un caractère spécial"),
  role: z.enum(["admin_tenant", "supervisor", "viewer"], {
    message: "Rôle requis",
  }),
});

type InviteFormValues = z.infer<typeof inviteSchema>;

const ROLE_OPTIONS = [
  { value: "admin_tenant", label: "Admin Tenant", desc: "Accès complet au tenant" },
  { value: "supervisor", label: "Superviseur", desc: "KB, conversations, contacts" },
  { value: "viewer", label: "Analyste", desc: "Lecture seule" },
] as const;

interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InviteDialog({ open, onOpenChange }: InviteDialogProps) {
  const createAdmin = useCreateAdmin();

  const {
    register,
    handleSubmit,
    setValue,
    reset,
    formState: { errors },
  } = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", full_name: "", password: "", role: undefined },
  });

  function onSubmit(data: InviteFormValues) {
    createAdmin.mutate(data, {
      onSuccess: () => {
        toast.success("Administrateur créé", {
          description: `Un compte a été créé pour ${data.email}`,
        });
        reset();
        onOpenChange(false);
      },
      onError: (error) => {
        const message =
          error instanceof Error ? error.message : "Erreur lors de la création";
        toast.error("Erreur", { description: message });
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">
            Inviter un administrateur
          </DialogTitle>
          <DialogDescription>
            Créez un compte administrateur pour le back-office CRI.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Email */}
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="admin@cri.ma"
              {...register("email")}
            />
            {errors.email && (
              <p className="text-xs text-destructive">{errors.email.message}</p>
            )}
          </div>

          {/* Full name */}
          <div className="space-y-2">
            <Label htmlFor="full_name">Nom complet</Label>
            <Input
              id="full_name"
              placeholder="Ahmed Benali"
              {...register("full_name")}
            />
            {errors.full_name && (
              <p className="text-xs text-destructive">{errors.full_name.message}</p>
            )}
          </div>

          {/* Password */}
          <div className="space-y-2">
            <Label htmlFor="password">Mot de passe initial</Label>
            <Input
              id="password"
              type="password"
              placeholder="Min. 12 caractères"
              {...register("password")}
            />
            {errors.password && (
              <p className="text-xs text-destructive">{errors.password.message}</p>
            )}
          </div>

          {/* Role */}
          <div className="space-y-2">
            <Label>Rôle</Label>
            <Select
              onValueChange={(value) =>
                setValue("role", value as InviteFormValues["role"], {
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Sélectionner un rôle" />
              </SelectTrigger>
              <SelectContent>
                {ROLE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    <span className="font-medium">{opt.label}</span>
                    <span className="text-muted-foreground ms-2 text-xs">
                      — {opt.desc}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.role && (
              <p className="text-xs text-destructive">{errors.role.message}</p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Annuler
            </Button>
            <Button type="submit" disabled={createAdmin.isPending}>
              {createAdmin.isPending && (
                <Loader2 className="h-4 w-4 me-2 animate-spin" />
              )}
              Inviter
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
