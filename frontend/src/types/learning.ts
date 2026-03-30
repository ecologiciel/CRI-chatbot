export interface LearningStats {
  total: number;
  by_status: Record<string, number>;
  approval_rate: number;
  avg_review_time_hours: number | null;
  top_questions: Array<{ id: string; question: string; frequency: number }>;
}
