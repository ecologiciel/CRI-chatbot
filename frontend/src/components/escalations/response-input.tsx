"use client";

import { useRef, useCallback, useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useRespondEscalation } from "@/hooks/use-escalations";

interface ResponseInputProps {
  escalationId: string;
  disabled?: boolean;
}

export function ResponseInput({
  escalationId,
  disabled,
}: ResponseInputProps) {
  const [message, setMessage] = useState("");
  const [reviewRequired, setReviewRequired] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inFlightRef = useRef(false);
  const respondMutation = useRespondEscalation();

  const handleSend = useCallback(() => {
    const trimmed = message.trim();
    if (!trimmed || disabled || reviewRequired || respondMutation.isPending || inFlightRef.current) return;
    inFlightRef.current = true;

    respondMutation.mutate(
      { id: escalationId, data: { message: trimmed } },
      {
        onSuccess: () => {
          setMessage("");
          toast.success("Message accepté par WhatsApp ; livraison non confirmée.");
          textareaRef.current?.focus();
        },
        onError: () => {
          setReviewRequired(true);
          toast.error("Résultat de l’envoi non confirmé.");
        },
        onSettled: () => { inFlightRef.current = false; },
      },
    );
  }, [message, escalationId, respondMutation, disabled, reviewRequired]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="shrink-0 border-t border-border px-4 py-3">
      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Tapez votre réponse..."
          disabled={disabled || respondMutation.isPending}
          rows={2}
          className="min-h-[60px] max-h-[120px] resize-none text-sm"
        />
        <Button
          size="icon"
          onClick={handleSend}
          disabled={disabled || respondMutation.isPending || reviewRequired || !message.trim()}
          className="shrink-0 h-10 w-10"
        >
          {respondMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" strokeWidth={1.75} />
          )}
        </Button>
      </div>
      {reviewRequired && (
        <div role="alert" className="mt-2 text-sm text-destructive space-y-2">
          <p>Le résultat de l’envoi est incertain. Vérifiez la conversation et, si nécessaire, WhatsApp avant de renvoyer : le message peut déjà avoir été accepté.</p>
          <Button type="button" variant="outline" size="sm" onClick={() => setReviewRequired(false)}>
            J’ai vérifié
          </Button>
        </div>
      )}
      <p className="text-[10px] text-muted-foreground mt-1.5">
        Ctrl+Entrée pour envoyer
      </p>
    </div>
  );
}
