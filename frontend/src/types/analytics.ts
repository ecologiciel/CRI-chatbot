export type AnalyticsPeriod = "7d" | "30d" | "90d" | "custom";

export interface AnalyticsOverview {
  conversations_total: number;
  conversations_trend: number;
  messages_total: number;
  messages_trend: number;
  resolution_rate: number;
  resolution_trend: number;
  csat_average: number;
  csat_trend: number;
}

export interface TimeSeriesPoint {
  date: string;
  conversations: number;
  messages: number;
  escalations: number;
}

export interface LanguageDistribution {
  language: string;
  label: string;
  count: number;
  percentage: number;
}

export interface QuestionTypeDistribution {
  type: string;
  label: string;
  count: number;
  percentage: number;
}

export interface TopQuestion {
  question: string;
  count: number;
  avg_confidence: number;
  status: "covered" | "uncovered";
}
