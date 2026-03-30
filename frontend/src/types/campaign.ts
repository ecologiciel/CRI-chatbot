// ---------------------------------------------------------------------------
// Campaign / Publipostage types — mirrors backend schemas (campaign.py + enums.py)
// ---------------------------------------------------------------------------

export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "sending"
  | "paused"
  | "completed"
  | "failed";

export type RecipientStatus =
  | "pending"
  | "sent"
  | "delivered"
  | "read"
  | "failed";

/** Inline stats stored in Campaign.stats JSONB column. */
export interface CampaignStatsInline {
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  total: number;
}

/** Full campaign — mirrors CampaignRead from the backend. */
export interface Campaign {
  id: string;
  name: string;
  description: string | null;
  template_id: string;
  template_name: string;
  template_language: string;
  audience_filter: Record<string, unknown>;
  audience_count: number;
  variable_mapping: Record<string, string>;
  status: CampaignStatus;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  stats: CampaignStatsInline;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** Aggregated stats from GET /campaigns/{id}/stats. */
export interface CampaignStatsData {
  total: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  pending: number;
  delivery_rate: number | null;
  read_rate: number | null;
}

/** Single recipient from GET /campaigns/{id}/recipients. */
export interface CampaignRecipient {
  id: string;
  campaign_id: string;
  contact_id: string;
  status: RecipientStatus;
  whatsapp_message_id: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  error_message: string | null;
  created_at: string;
}

/** Audience preview from POST /campaigns/{id}/preview. */
export interface AudiencePreview {
  count: number;
  sample: Array<Record<string, unknown>>;
}

/** Quota status from GET /campaigns/quota. */
export interface QuotaStatus {
  allowed: boolean;
  used: number;
  limit: number;
  remaining: number;
  percentage: number;
}

// ---------------------------------------------------------------------------
// Payloads
// ---------------------------------------------------------------------------

export interface CampaignCreatePayload {
  name: string;
  description?: string;
  template_id: string;
  template_name: string;
  template_language: string;
  audience_filter: Record<string, unknown>;
  variable_mapping?: Record<string, string>;
}

export interface CampaignUpdatePayload {
  name?: string;
  description?: string;
  audience_filter?: Record<string, unknown>;
  variable_mapping?: Record<string, string>;
}

export interface CampaignSchedulePayload {
  scheduled_at: string;
}

// ---------------------------------------------------------------------------
// Wizard form data (4-step wizard state)
// ---------------------------------------------------------------------------

export interface CampaignWizardData {
  // Step 1 — Template
  template_id: string;
  template_name: string;
  template_language: string;
  // Step 2 — Audience
  audience_tags: string[];
  audience_language: string;
  // Step 3 — Variables
  variable_mapping: Record<string, string>;
  // Step 4 — Schedule
  name: string;
  description: string;
  send_mode: "immediate" | "scheduled";
  scheduled_at: string;
}

/** WhatsApp template definition for the wizard. */
export interface WhatsAppTemplate {
  id: string;
  name: string;
  language: string;
  body: string;
  header?: string;
  footer?: string;
  buttons?: string[];
  variables: string[];
}
