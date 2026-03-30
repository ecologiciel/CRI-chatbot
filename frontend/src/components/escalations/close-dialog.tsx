"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCloseEscalation } from "@/hooks/use-escalations";

interface CloseDialogProps {
  escalationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onClosed?: () => void;
}

export function CloseDialog({
  escalationId,
  open,
  onOpenChange,
  onClosed,
}: CloseDialogProps) {
  const [notes, setNotes] = useState("");
  const closeMutation = useCloseEscalation();

  const handleSubmit = () => {
    const trimmed = notes.trim();
    if (!trimmed) return;

    closeMutation.mutate(
      { id: escalationId, data: { resolution_notes: trimmed } },
      {
        onSuccess: () => {
          toast.success("Escalade clôturée");
          setNotes("");
          onOpenChange(false);
          onClosed?.();
        },
        onError: () => {
          toast.error("Échec de la clôture");
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="font-heading">
            Clôturer l&apos;escalade
          </DialogTitle>
          <DialogDescription>
            La conversation reviendra en mode automatique.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 py-2">
          <Label htmlFor="resolution-notes">Notes de résolution</Label>
          <Textarea
            id="resolution-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Décrivez la résolution..."
            rows={4}
            className="resize-none text-sm"
          />
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={closeMutation.isPending}
          >
            Annuler
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!notes.trim() || closeMutation.isPending}
          >
            {closeMutation.isPending && (
              <Loader2 className="h-4 w-4 animate-spin me-2" />
            )}
            Clôturer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
