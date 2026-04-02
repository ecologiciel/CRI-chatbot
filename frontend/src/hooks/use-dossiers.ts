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

export function useSyncLogs(params?: SyncLogsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["sync-logs", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<SyncLog>>("/dossiers/sync-logs", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status || undefined,
      }),
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
      return api.upload<{ message: string; file_path: string }>(
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
