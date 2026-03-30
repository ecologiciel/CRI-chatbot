"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useRespondEscalation } from "@/hooks/use-escalations";

interface ResponseInputProps {
  escalationId: string;
  disabled?: boolean;
  /** When set, the textarea is filled with this text (from AI suggestions) */
  suggestion?: string;
}

export function ResponseInput({
  escalationId,
  disabled,
  suggestion,
}: ResponseInputProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const respondMutation = useRespondEscalation();

  // Insert suggestion text when prop changes
  useEffect(() => {
    if (suggestion) {
      setMessage(suggestion);
      textareaRef.current?.focus();
    }
  }, [suggestion]);

  const handleSend = useCallback(() => {
    const trimmed = message.trim();
    if (!trimmed) return;

    respondMutation.mutate(
      { id: escalationId, data: { message: trimmed } },
      {
        onSuccess: () => {
          setMessage("");
          toast.success("Message envoyé via WhatsApp");
          textareaRef.current?.focus();
        },
        onError: () => {
          toast.error("Échec de l'envoi du message");
        },
      },
    );
  }, [message, escalationId, respondMutation]);

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
          disabled={disabled || respondMutation.isPending || !message.trim()}
          className="shrink-0 h-10 w-10"
        >
          {respondMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" strokeWidth={1.75} />
          )}
        </Button>
      </div>
      <p className="text-[10px] text-muted-foreground mt-1.5">
        Ctrl+Entrée pour envoyer
      </p>
    </div>
  );
}
