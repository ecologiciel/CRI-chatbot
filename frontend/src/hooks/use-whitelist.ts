import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type {
  WhitelistEntry,
  WhitelistCreatePayload,
  WhitelistUpdatePayload,
} from "@/types/whitelist";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Params
// ---------------------------------------------------------------------------

interface WhitelistParams {
  page?: number;
  page_size?: number;
  search?: string;
  is_active?: boolean;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useWhitelistEntries(params?: WhitelistParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["whitelist", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<WhitelistEntry>>("/whitelist", {
        page: params?.page,
        page_size: params?.page_size,
        search: params?.search || undefined,
        is_active:
          params?.is_active !== undefined
            ? String(params.is_active)
            : undefined,
      }),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateWhitelistEntry() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: WhitelistCreatePayload) =>
      api.post<WhitelistEntry>("/whitelist", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whitelist"] });
    },
  });
}

export function useUpdateWhitelistEntry() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: WhitelistUpdatePayload }) =>
      api.patch<WhitelistEntry>(`/whitelist/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whitelist"] });
    },
  });
}

export function useDeleteWhitelistEntry() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (entryId: string) => api.del(`/whitelist/${entryId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whitelist"] });
    },
  });
}
