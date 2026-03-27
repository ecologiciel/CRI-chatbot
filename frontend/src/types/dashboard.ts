export interface DashboardStats {
  active_conversations: number;
  messages_today: number;
  resolution_rate: number;
  csat_score: number;
  total_contacts: number;
  kb_documents_indexed: number;
  unanswered_questions: number;
  quota_usage: Record<string, unknown> | null;
}
