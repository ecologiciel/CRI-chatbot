import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import { superAdminApi } from "@/lib/api/super-admin";
import type { AuditLogFilters } from "@/types/super-admin";

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useTenants() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sa-tenants"] as const,
    queryFn: () => superAdminApi.listTenants(api),
  });
}

export function useTenantsHealth() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sa-tenants-health"] as const,
    queryFn: () => superAdminApi.getTenantsHealth(api),
    refetchInterval: 30_000, // auto-refresh every 30s
  });
}

export function useAuditLogs(filters: AuditLogFilters) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sa-audit-logs", filters] as const,
    queryFn: () => superAdminApi.getAuditLogs(api, filters),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateTenant() {
  const api = useApiClient();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) =>
      superAdminApi.createTenant(api, formData),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sa-tenants"] });
      qc.invalidateQueries({ queryKey: ["sa-tenants-health"] });
    },
  });
}

export function useToggleTenant() {
  const api = useApiClient();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, active }: { slug: string; active: boolean }) =>
      superAdminApi.toggleTenant(api, slug, active),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sa-tenants"] });
      qc.invalidateQueries({ queryKey: ["sa-tenants-health"] });
    },
  });
}
