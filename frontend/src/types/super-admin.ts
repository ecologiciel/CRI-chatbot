import type { TenantStatus } from "@/types";

// ---------------------------------------------------------------------------
// Tenant management
// ---------------------------------------------------------------------------

export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  region: string;
  status: TenantStatus;
  logo_url: string | null;
  accent_color: string | null;
  messages_used: number;
  messages_limit: number;
  contacts_count: number;
  last_activity: string | null;
  created_at: string;
}

export interface TenantCreateData {
  // Step 1 — Informations
  name: string;
  slug: string;
  region: string;
  // Step 2 — WhatsApp
  whatsapp_phone_number_id: string;
  whatsapp_access_token: string;
  whatsapp_app_secret: string;
  // Step 3 — Personnalisation
  logo_file?: File;
  accent_color: string;
}

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------

export interface MonitoringTenantHealth {
  tenant: TenantSummary;
  is_healthy: boolean;
  messages_today: number;
  conversations_active: number;
  last_webhook_at: string | null;
  whatsapp_connected: boolean;
  qdrant_collection_size: number;
}

// ---------------------------------------------------------------------------
// Audit logs
// ---------------------------------------------------------------------------

export interface AuditLogEntry {
  id: string;
  tenant_slug: string;
  user_id: string | null;
  user_type: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  ip_address: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogFilters {
  tenant_slug?: string;
  user_id?: string;
  action?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const REGIONS_MAROC = [
  "Rabat-Salé-Kénitra",
  "Casablanca-Settat",
  "Tanger-Tétouan-Al Hoceima",
  "Marrakech-Safi",
  "Fès-Meknès",
  "Souss-Massa",
  "Oriental",
  "Béni Mellal-Khénifra",
  "Drâa-Tafilalet",
  "Laâyoune-Sakia El Hamra",
  "Guelmim-Oued Noun",
  "Dakhla-Oued Ed Dahab",
] as const;

export const TENANT_STATUS_STYLES: Record<TenantStatus, string> = {
  active: "bg-[#5F8B5F]/10 text-[#5F8B5F] border-[#5F8B5F]/20",
  inactive: "bg-[#6B5B4F]/10 text-[#6B5B4F] border-[#6B5B4F]/20",
  suspended: "bg-[#B5544B]/10 text-[#B5544B] border-[#B5544B]/20",
  provisioning: "bg-[#C4944B]/10 text-[#C4944B] border-[#C4944B]/20",
};

export const AUDIT_ACTIONS = [
  "create",
  "update",
  "delete",
  "login",
  "logout",
  "export",
  "import",
  "provision",
  "activate",
  "deactivate",
] as const;
