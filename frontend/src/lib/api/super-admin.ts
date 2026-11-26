import type { ApiClient } from "@/lib/api-client";
import type { PaginatedResponse } from "@/types/api";
import type {
  TenantSummary,
  TenantRecord,
  TenantCreateData,
  MonitoringTenantHealth,
  AuditLogEntry,
  AuditLogFilters,
} from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Super-Admin API — all endpoints require role super_admin
// ---------------------------------------------------------------------------

export const superAdminApi = {
  // ── Tenants ───────────────────────────────────────────────────────────────

  listTenants: async (api: ApiClient) => {
    const tenants: TenantRecord[] = [];
    let page = 1;
    while (true) {
      const result = await api.get<PaginatedResponse<TenantRecord>>("/tenants/", { page, page_size: 100 });
      tenants.push(...result.items);
      if (result.items.length === 0 || tenants.length >= result.total) return tenants;
      page += 1;
    }
  },

  getTenant: (api: ApiClient, slug: string) =>
    api.get<TenantSummary>(`/tenants/${slug}`),

  createTenant: (api: ApiClient, data: TenantCreateData) =>
    api.post<TenantRecord>("/tenants/", data),

  updateTenant: (api: ApiClient, slug: string, data: Record<string, unknown>) =>
    api.patch<TenantSummary>(`/tenants/${slug}`, data),

  toggleTenant: (api: ApiClient, id: string, active: boolean) =>
    api.patch<TenantRecord>(`/tenants/${id}`, {
      status: active ? "active" : "inactive",
    }),

  // ── Monitoring ────────────────────────────────────────────────────────────

  getTenantsHealth: (api: ApiClient, page: number) =>
    api.get<PaginatedResponse<MonitoringTenantHealth>>("/tenants/health", { page, page_size: 20 }),

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
