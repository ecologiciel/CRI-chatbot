import type { ApiClient } from "@/lib/api-client";
import type { PaginatedResponse } from "@/types/api";
import type {
  TenantSummary,
  MonitoringTenantHealth,
  AuditLogEntry,
  AuditLogFilters,
} from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Super-Admin API — all endpoints require role super_admin
// ---------------------------------------------------------------------------

export const superAdminApi = {
  // ── Tenants ───────────────────────────────────────────────────────────────

  listTenants: (api: ApiClient) =>
    api.get<TenantSummary[]>("/tenants"),

  getTenant: (api: ApiClient, slug: string) =>
    api.get<TenantSummary>(`/tenants/${slug}`),

  createTenant: (api: ApiClient, formData: FormData) =>
    api.upload<TenantSummary>("/tenants/provision", formData),

  updateTenant: (api: ApiClient, slug: string, data: Record<string, unknown>) =>
    api.patch<TenantSummary>(`/tenants/${slug}`, data),

  toggleTenant: (api: ApiClient, slug: string, active: boolean) =>
    api.patch<TenantSummary>(`/tenants/${slug}`, {
      status: active ? "active" : "inactive",
    }),

  // ── Monitoring ────────────────────────────────────────────────────────────

  getTenantsHealth: (api: ApiClient) =>
    api.get<MonitoringTenantHealth[]>("/tenants/health"),

  // ── Audit Logs ────────────────────────────────────────────────────────────

  getAuditLogs: (api: ApiClient, filters: AuditLogFilters) =>
    api.get<PaginatedResponse<AuditLogEntry>>("/audit/logs", {
      tenant_slug: filters.tenant_slug,
      user_id: filters.user_id,
      action: filters.action,
      date_from: filters.date_from,
      date_to: filters.date_to,
      page: filters.page,
      page_size: filters.page_size,
    }),
};
