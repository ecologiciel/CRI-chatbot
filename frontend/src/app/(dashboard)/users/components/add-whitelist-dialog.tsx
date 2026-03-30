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
import { useCreateWhitelistEntry } from "@/hooks/use-whitelist";

const whitelistSchema = z.object({
  phone: z
    .string()
    .regex(/^\+[1-9]\d{6,14}$/, "Format E.164 requis (ex: +212612345678)"),
  label: z.string().optional(),
  note: z.string().optional(),
});

type WhitelistFormValues = z.infer<typeof whitelistSchema>;

interface AddWhitelistDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddWhitelistDialog({
  open,
  onOpenChange,
}: AddWhitelistDialogProps) {
  const createEntry = useCreateWhitelistEntry();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<WhitelistFormValues>({
    resolver: zodResolver(whitelistSchema),
    defaultValues: { phone: "", label: "", note: "" },
  });

  function onSubmit(data: WhitelistFormValues) {
    createEntry.mutate(
      {
        phone: data.phone,
        label: data.label || undefined,
        note: data.note || undefined,
      },
      {
        onSuccess: () => {
          toast.success("Numéro ajouté", {
            description: `${data.phone} a été ajouté à la liste blanche`,
          });
          reset();
          onOpenChange(false);
        },
        onError: (error) => {
          const message =
            error instanceof Error ? error.message : "Erreur lors de l'ajout";
          // Handle 409 duplicate
          if (message.toLowerCase().includes("already")) {
            toast.error("Ce numéro est déjà dans la liste blanche");
          } else {
            toast.error("Erreur", { description: message });
          }
        },
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">
            Ajouter un numéro à la liste blanche
          </DialogTitle>
          <DialogDescription>
            Ce numéro pourra accéder à l&apos;agent interne (lecture seule) via
            WhatsApp.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Phone */}
          <div className="space-y-2">
            <Label htmlFor="phone">Numéro de téléphone</Label>
            <Input
              id="phone"
              placeholder="+212612345678"
              className="font-mono"
              {...register("phone")}
            />
            {errors.phone && (
              <p className="text-xs text-destructive">{errors.phone.message}</p>
            )}
          </div>

          {/* Label */}
          <div className="space-y-2">
            <Label htmlFor="label">Libellé (optionnel)</Label>
            <Input
              id="label"
              placeholder="Nom du collaborateur"
              {...register("label")}
            />
          </div>

          {/* Note */}
          <div className="space-y-2">
            <Label htmlFor="note">Note (optionnel)</Label>
            <Input
              id="note"
              placeholder="Poste ou département"
              {...register("note")}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Annuler
            </Button>
            <Button type="submit" disabled={createEntry.isPending}>
              {createEntry.isPending && (
                <Loader2 className="h-4 w-4 me-2 animate-spin" />
              )}
              Ajouter
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
