import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type {
  Dossier,
  DossierDetail,
  DossierStats,
  DossierStatut,
  SyncLog,
  SyncConfig,
  SyncConfigCreatePayload,
  SyncStatus,
} from "@/types/dossier";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

interface DossiersParams {
  page?: number;
  page_size?: number;
  statut?: DossierStatut;
  type_projet?: string;
  date_depot_from?: string;
  date_depot_to?: string;
  search?: string;
}

interface SyncLogsParams {
  page?: number;
  page_size?: number;
  status?: SyncStatus;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useDossiers(params?: DossiersParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["dossiers", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<Dossier>>("/dossiers", {
        page: params?.page,
        page_size: params?.page_size,
        statut: params?.statut,
        type_projet: params?.type_projet || undefined,
        date_depot_from: params?.date_depot_from || undefined,
        date_depot_to: params?.date_depot_to || undefined,
        search: params?.search || undefined,
      }),
  });
}

export function useDossier(dossierId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["dossiers", "detail", dossierId] as const,
    queryFn: () => api.get<DossierDetail>(`/dossiers/${dossierId}`),
    enabled: !!dossierId,
  });
}

export function useDossierStats() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["dossier-stats"] as const,
    queryFn: () => api.get<DossierStats>("/dossiers/stats"),
    refetchInterval: 30_000,
  });
}

export function useSyncLogs(params?: SyncLogsParams, poll = false) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sync-logs", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<SyncLog>>("/dossiers/sync-logs", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status || undefined,
      }),
    refetchInterval: poll ? 3000 : false,
  });
}

export function useSyncLog(syncLogId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sync-logs", "detail", syncLogId] as const,
    queryFn: () => api.get<SyncLog>(`/dossiers/sync-logs/${syncLogId}`),
    enabled: !!syncLogId,
  });
}

export function useSyncConfigs() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sync-configs"] as const,
    queryFn: () => api.get<SyncConfig[]>("/dossiers/sync-configs"),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useImportDossiers() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      file,
      syncConfigId,
    }: {
      file: File;
      syncConfigId?: string;
    }) => {
      const formData = new FormData();
      formData.append("file", file);
      const qs = syncConfigId ? `?sync_config_id=${syncConfigId}` : "";
      return api.upload<{ message: string; file_path?: string; request_id?: string; deduplicated?: boolean }>(
        `/dossiers/import${qs}`,
        formData,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dossiers"] });
      queryClient.invalidateQueries({ queryKey: ["dossier-stats"] });
      queryClient.invalidateQueries({ queryKey: ["sync-logs"] });
    },
  });
}

export interface DurableImportRequest {
  request_id: string;
  state: "pending" | "processing" | "completed" | "failed" | "uncertain";
  outcome_code: string | null;
  review_state: "open" | "follow_up" | "closed";
  review_outcome: "applied" | "not_applied" | null;
  sync_log_id: string | null;
  created_at: string;
  updated_at: string;
}

export function useDurableImportRequests(state: string, offset: number, enabled: boolean) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["dossier-import-requests", state, offset],
    queryFn: () => api.get<{available: boolean; active: boolean; items: DurableImportRequest[]; has_more: boolean}>(
      "/dossiers/imports", {state: state || undefined, limit: 25, offset},
    ),
    enabled,
    refetchInterval: 15_000,
  });
}

export function useDurableImportRequest(requestId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["dossier-import-request", requestId],
    queryFn: () => api.get<DurableImportRequest>(`/dossiers/imports/${requestId}`),
    enabled: !!requestId,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "completed" || state === "failed" || state === "uncertain" ? false : 3000;
    },
  });
}

export function useCreateSyncConfig() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: SyncConfigCreatePayload) =>
      api.post<SyncConfig>("/dossiers/sync-configs", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-configs"] });
    },
  });
}

export function useUpdateSyncConfig() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<SyncConfigCreatePayload>;
    }) => api.put<SyncConfig>(`/dossiers/sync-configs/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-configs"] });
    },
  });
}
