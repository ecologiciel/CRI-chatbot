import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import { notificationsApi } from "@/lib/api/notifications";
import type {
  NotificationHistoryParams,
  ManualNotificationRequest,
  NotificationTemplateUpdate,
} from "@/types/notification";

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useNotificationHistory(params?: NotificationHistoryParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["notifications", params] as const,
    queryFn: () => notificationsApi.getHistory(api, params),
  });
}

export function useNotificationStats(days: number = 30) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["notifications", "stats", days] as const,
    queryFn: () => notificationsApi.getStats(api, days),
  });
}

export function useNotificationTemplates() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["notifications", "templates"] as const,
    queryFn: () => notificationsApi.getTemplates(api),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useSendNotification() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ManualNotificationRequest) =>
      notificationsApi.send(api, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useUpdateTemplate() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      eventType,
      data,
    }: {
      eventType: string;
      data: NotificationTemplateUpdate;
    }) => notificationsApi.updateTemplate(api, eventType, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["notifications", "templates"],
      });
    },
  });
}
