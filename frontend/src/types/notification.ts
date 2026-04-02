// ---------------------------------------------------------------------------
// Notification types — matches backend schemas (notification.py)
// ---------------------------------------------------------------------------

export type NotificationStatus = "sent" | "skipped" | "failed";

export type NotificationEventType =
  | "decision_finale"
  | "complement_request"
  | "status_update"
  | "dossier_incomplet";

export type NotificationPriority = "high" | "medium" | "low";

// ---------------------------------------------------------------------------
// History (GET /notifications)
// ---------------------------------------------------------------------------

export interface NotificationHistoryItem {
  id: string;
  event_type: string | null;
  status: NotificationStatus;
  contact_id: string | null;
  dossier_id: string | null;
  dossier_numero: string | null;
  template_name: string | null;
  wamid: string | null;
  reason: string | null;
  created_at: string;
}

export interface NotificationHistoryList {
  items: NotificationHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface NotificationHistoryParams {
  page?: number;
  page_size?: number;
  status?: NotificationStatus;
  event_type?: NotificationEventType;
  date_from?: string;
  date_to?: string;
}

// ---------------------------------------------------------------------------
// Stats (GET /notifications/stats)
// ---------------------------------------------------------------------------

export interface NotificationStats {
  total_sent: number;
  total_skipped: number;
  total_failed: number;
  by_event_type: Record<string, number>;
  period_days: number;
}

// ---------------------------------------------------------------------------
// Manual send (POST /notifications/send)
// ---------------------------------------------------------------------------

export interface ManualNotificationRequest {
  contact_id: string;
  dossier_id: string;
  event_type: NotificationEventType;
}

export interface ManualNotificationResponse {
  status: NotificationStatus;
  wamid: string | null;
  reason: string | null;
}

// ---------------------------------------------------------------------------
// Templates (GET/PUT /notifications/templates)
// ---------------------------------------------------------------------------

export interface NotificationTemplateRead {
  event_type: string;
  template_name: string;
  description: string;
  priority: string;
}

export interface NotificationTemplateUpdate {
  template_name: string;
}
