import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { PaginatedResponse } from "@/types/api";
import type { ConversationMessageRecord, ConversationRecord } from "@/types/conversation";

export function useConversations(page: number, search: string) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["conversations", page, search],
    queryFn: () => api.get<PaginatedResponse<ConversationRecord>>("/conversations", {
      page, page_size: 20, search: search || undefined,
    }),
    refetchInterval: 30_000,
  });
}

export function useConversation(id: string) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api.get<ConversationRecord>(`/conversations/${id}`),
    enabled: !!id,
    refetchInterval: 30_000,
  });
}

export function useConversationMessages(id: string, page: number) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["conversation", id, "messages", page],
    queryFn: () => api.get<PaginatedResponse<ConversationMessageRecord>>(
      `/conversations/${id}/messages`, { page, page_size: 100 },
    ),
    enabled: !!id,
    refetchInterval: 30_000,
  });
}
