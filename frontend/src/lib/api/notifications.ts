import type { ApiClient } from "@/lib/api-client";
import type {
  NotificationHistoryList,
  NotificationHistoryParams,
  NotificationStats,
  ManualNotificationRequest,
  ManualNotificationResponse,
  NotificationTemplateRead,
  NotificationTemplateUpdate,
} from "@/types/notification";

export const notificationsApi = {
  getHistory: (api: ApiClient, params?: NotificationHistoryParams) =>
    api.get<NotificationHistoryList>("/notifications", {
      page: params?.page,
      page_size: params?.page_size,
      status: params?.status,
      event_type: params?.event_type,
      date_from: params?.date_from,
      date_to: params?.date_to,
    }),

  getStats: (api: ApiClient, days: number = 30) =>
    api.get<NotificationStats>("/notifications/stats", { days }),

  send: (api: ApiClient, data: ManualNotificationRequest) =>
    api.post<ManualNotificationResponse>("/notifications/send", data),

  getTemplates: (api: ApiClient) =>
    api.get<NotificationTemplateRead[]>("/notifications/templates"),

  updateTemplate: (
    api: ApiClient,
    eventType: string,
    data: NotificationTemplateUpdate,
  ) =>
    api.put<NotificationTemplateRead>(
      `/notifications/templates/${eventType}`,
      data,
    ),
};
