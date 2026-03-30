import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type {
  Campaign,
  CampaignStatus,
  CampaignStatsData,
  CampaignRecipient,
  CampaignCreatePayload,
  CampaignUpdatePayload,
  AudiencePreview,
  QuotaStatus,
  RecipientStatus,
} from "@/types/campaign";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

interface CampaignsParams {
  page?: number;
  page_size?: number;
  status?: CampaignStatus;
}

interface RecipientsParams {
  page?: number;
  page_size?: number;
  status?: RecipientStatus;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useCampaigns(params?: CampaignsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["campaigns", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<Campaign>>("/campaigns", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status || undefined,
      }),
  });
}

export function useCampaign(campaignId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["campaigns", "detail", campaignId] as const,
    queryFn: () => api.get<Campaign>(`/campaigns/${campaignId}`),
    enabled: !!campaignId,
  });
}

export function useCampaignStats(campaignId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["campaigns", campaignId, "stats"] as const,
    queryFn: () =>
      api.get<CampaignStatsData>(`/campaigns/${campaignId}/stats`),
    enabled: !!campaignId,
    refetchInterval: 10_000,
  });
}

export function useCampaignRecipients(
  campaignId: string | null,
  params?: RecipientsParams
) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["campaigns", campaignId, "recipients", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<CampaignRecipient>>(
        `/campaigns/${campaignId}/recipients`,
        {
          page: params?.page,
          page_size: params?.page_size,
          status: params?.status || undefined,
        }
      ),
    enabled: !!campaignId,
  });
}

export function useCampaignQuota(count?: number) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["campaigns", "quota", count] as const,
    queryFn: () =>
      api.get<QuotaStatus>("/campaigns/quota", {
        count: count ?? 0,
      }),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateCampaign() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CampaignCreatePayload) =>
      api.post<Campaign>("/campaigns", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useUpdateCampaign() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CampaignUpdatePayload }) =>
      api.patch<Campaign>(`/campaigns/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useLaunchCampaign() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.post<Campaign>(`/campaigns/${id}/launch`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function usePauseCampaign() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.post<Campaign>(`/campaigns/${id}/pause`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useResumeCampaign() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.post<Campaign>(`/campaigns/${id}/resume`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useScheduleCampaign() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      scheduled_at,
    }: {
      id: string;
      scheduled_at: string;
    }) => api.post<Campaign>(`/campaigns/${id}/schedule`, { scheduled_at }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useAudiencePreview() {
  const api = useApiClient();

  return useMutation({
    mutationFn: (campaignId: string) =>
      api.post<AudiencePreview>(`/campaigns/${campaignId}/preview`, {}),
  });
}
