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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useRejectQuestion } from "@/hooks/use-learning";

const rejectSchema = z.object({
  review_note: z.string().min(1, "Motif de rejet requis"),
});

type RejectFormValues = z.infer<typeof rejectSchema>;

interface RejectDialogProps {
  questionId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RejectDialog({
  questionId,
  open,
  onOpenChange,
}: RejectDialogProps) {
  const rejectMutation = useRejectQuestion();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<RejectFormValues>({
    resolver: zodResolver(rejectSchema),
    defaultValues: { review_note: "" },
  });

  function handleClose(value: boolean) {
    if (!value) reset();
    onOpenChange(value);
  }

  function onSubmit(data: RejectFormValues) {
    if (!questionId) return;
    rejectMutation.mutate(
      { questionId, data: { review_note: data.review_note } },
      {
        onSuccess: () => {
          toast.success("Question rejetée");
          reset();
          onOpenChange(false);
        },
        onError: () => {
          toast.error("Erreur lors du rejet");
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Rejeter la question</DialogTitle>
          <DialogDescription>
            Cette question ne sera pas ajoutée à la base de connaissances.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="review_note">Motif du rejet</Label>
            <Textarea
              id="review_note"
              placeholder="Expliquez pourquoi cette question est rejetée..."
              rows={4}
              {...register("review_note")}
            />
            {errors.review_note && (
              <p className="text-xs text-destructive">
                {errors.review_note.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleClose(false)}
            >
              Annuler
            </Button>
            <Button
              type="submit"
              variant="destructive"
              disabled={rejectMutation.isPending}
            >
              {rejectMutation.isPending && (
                <Loader2 className="h-4 w-4 me-2 animate-spin" />
              )}
              Rejeter
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
