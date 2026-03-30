// ---------------------------------------------------------------------------
// Escalation types — mirrors backend EscalationRead / EscalationStats schemas
// ---------------------------------------------------------------------------

export type EscalationTrigger =
  | "explicit_request"
  | "rag_failure"
  | "sensitive_topic"
  | "negative_feedback"
  | "otp_timeout"
  | "manual";

export type EscalationPriority = "high" | "medium" | "low";

export type EscalationStatus =
  | "pending"
  | "assigned"
  | "in_progress"
  | "resolved"
  | "closed";

export interface Escalation {
  id: string;
  conversation_id: string;
  trigger_type: EscalationTrigger;
  priority: EscalationPriority;
  assigned_to: string | null;
  context_summary: string | null;
  user_message: string | null;
  status: EscalationStatus;
  resolution_notes: string | null;
  created_at: string;
  assigned_at: string | null;
  resolved_at: string | null;
  contact_name?: string;
  contact_phone?: string;
  wait_time_seconds?: number;
}

export interface EscalationMessage {
  id: string;
  direction: "inbound" | "outbound";
  type: "text" | "image" | "audio" | "system";
  content: string | null;
  timestamp: string;
  sender_type?: "user" | "bot" | "agent";
}

export interface EscalationWebSocketEvent {
  event: "new" | "assigned" | "resolved" | "updated";
  data: Partial<Escalation>;
  timestamp: string;
}

export interface EscalationStatsData {
  total_pending: number;
  total_in_progress: number;
  avg_wait_seconds: number | null;
  avg_resolution_seconds: number | null;
  by_trigger: Record<string, number>;
  by_priority: Record<string, number>;
}

export interface EscalationRespondPayload {
  message: string;
}

export interface EscalationResolvePayload {
  resolution_notes: string;
}

// ---------------------------------------------------------------------------
// UI config — labels and styling
// ---------------------------------------------------------------------------

export const TRIGGER_LABELS: Record<EscalationTrigger, string> = {
  explicit_request: "Demande explicite",
  rag_failure: "Échec RAG répété",
  sensitive_topic: "Sujet sensible",
  negative_feedback: "Feedback négatif",
  otp_timeout: "Timeout OTP",
  manual: "Manuel",
};

export const PRIORITY_CONFIG: Record<
  EscalationPriority,
  { label: string; className: string; dotClassName: string }
> = {
  high: {
    label: "Haute",
    className: "bg-[#B5544B]/10 text-[#B5544B] border-[#B5544B]/20",
    dotClassName: "bg-[#B5544B]",
  },
  medium: {
    label: "Moyenne",
    className: "bg-[#C4944B]/10 text-[#C4944B] border-[#C4944B]/20",
    dotClassName: "bg-[#C4944B]",
  },
  low: {
    label: "Basse",
    className: "bg-[#5B7A8B]/10 text-[#5B7A8B] border-[#5B7A8B]/20",
    dotClassName: "bg-[#5B7A8B]",
  },
};

export const STATUS_CONFIG: Record<
  EscalationStatus,
  { label: string; className: string }
> = {
  pending: {
    label: "En attente",
    className: "bg-[#C4944B]/10 text-[#C4944B] border-0",
  },
  assigned: {
    label: "Assignée",
    className: "bg-[#5B7A8B]/10 text-[#5B7A8B] border-0",
  },
  in_progress: {
    label: "En cours",
    className: "bg-[#7A8B5F]/10 text-[#7A8B5F] border-0",
  },
  resolved: {
    label: "Résolue",
    className: "bg-[#5F8B5F]/10 text-[#5F8B5F] border-0",
  },
  closed: {
    label: "Clôturée",
    className: "bg-muted text-muted-foreground border-0",
  },
};
