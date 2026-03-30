"use client";

import { useState, useCallback } from "react";
import {
  Phone,
  UserPlus,
  XCircle,
  Info,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PriorityBadge } from "./priority-badge";
import { TriggerBadge } from "./trigger-badge";
import { AiSummaryBanner } from "./ai-summary-banner";
import { ConversationBubbles } from "./conversation-bubbles";
import { AiSuggestions } from "./ai-suggestions";
import { ResponseInput } from "./response-input";
import { CloseDialog } from "./close-dialog";
import {
  useEscalation,
  useEscalationConversation,
  useAssignEscalation,
} from "@/hooks/use-escalations";
import { STATUS_CONFIG } from "@/types/escalation";

function maskPhone(phone: string): string {
  if (phone.length > 8) {
    return phone.slice(0, 8) + "•••• " + phone.slice(-3);
  }
  return phone;
}

interface EscalationDetailProps {
  escalationId: string;
}

export function EscalationDetail({ escalationId }: EscalationDetailProps) {
  const { data: escalation, isLoading, isError } = useEscalation(escalationId);
  const { data: messages } = useEscalationConversation(escalationId);
  const assignMutation = useAssignEscalation();
  const [closeOpen, setCloseOpen] = useState(false);
  const [suggestionText, setSuggestionText] = useState("");

  const handleAssign = useCallback(() => {
    assignMutation.mutate(escalationId, {
      onSuccess: () => toast.success("Escalade prise en charge"),
      onError: () => toast.error("Échec de l'assignation"),
    });
  }, [escalationId, assignMutation]);

  const handleSuggestionSelect = useCallback((text: string) => {
    setSuggestionText(text);
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (isError || !escalation) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
        <AlertTriangle className="h-8 w-8 opacity-30" strokeWidth={1.5} />
        <p className="text-sm">Escalade introuvable</p>
      </div>
    );
  }

  const status = STATUS_CONFIG[escalation.status];
  const isPending = escalation.status === "pending";
  const isActive =
    escalation.status === "assigned" ||
    escalation.status === "in_progress";
  const isClosed =
    escalation.status === "resolved" || escalation.status === "closed";
  const displayName =
    escalation.contact_name ?? escalation.contact_phone ?? "Inconnu";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h2 className="text-sm font-semibold font-heading truncate">
                {displayName}
              </h2>
              <Badge className={cn("text-xs", status.className)}>
                {status.label}
              </Badge>
              <PriorityBadge priority={escalation.priority} size="sm" />
              <TriggerBadge trigger={escalation.trigger_type} />
            </div>
            {escalation.contact_phone && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Phone className="h-3 w-3" strokeWidth={1.75} />
                <span className="font-mono">
                  {maskPhone(escalation.contact_phone)}
                </span>
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 shrink-0">
            {isPending && (
              <Button
                size="sm"
                onClick={handleAssign}
                disabled={assignMutation.isPending}
                className="gap-1.5"
              >
                {assignMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <UserPlus className="h-3.5 w-3.5" strokeWidth={1.75} />
                )}
                Prendre en charge
              </Button>
            )}
            {isActive && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setCloseOpen(true)}
                className="gap-1.5"
              >
                <XCircle className="h-3.5 w-3.5" strokeWidth={1.75} />
                Clôturer
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* AI Summary */}
      <AiSummaryBanner summary={escalation.context_summary} />

      {/* Conversation bubbles */}
      <ConversationBubbles
        messages={messages ?? []}
        escalation={escalation}
      />

      {/* AI Suggestions — only when assigned */}
      {isActive && (
        <AiSuggestions
          escalationId={escalationId}
          onSelect={handleSuggestionSelect}
        />
      )}

      {/* Response input — only when assigned */}
      {isActive && (
        <ResponseInput
          escalationId={escalationId}
          suggestion={suggestionText}
        />
      )}

      {/* Read-only banner for closed escalations */}
      {isClosed && (
        <div className="shrink-0 border-t border-border px-4 py-3">
          <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2">
            <Info
              className="h-4 w-4 text-muted-foreground shrink-0"
              strokeWidth={1.75}
            />
            <p className="text-xs text-muted-foreground">
              Escalade clôturée — lecture seule
            </p>
          </div>
        </div>
      )}

      {/* Close dialog */}
      <CloseDialog
        escalationId={escalationId}
        open={closeOpen}
        onOpenChange={setCloseOpen}
      />
    </div>
  );
}
