import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { DashboardStats } from "@/types/dashboard";

export function useDashboardStats() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["dashboard-stats"] as const,
    queryFn: () => api.get<DashboardStats>("/dashboard/stats"),
    refetchInterval: 30_000,
  });
}
