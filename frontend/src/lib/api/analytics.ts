import type { ApiClient } from "@/lib/api-client";
import type {
  AnalyticsOverview,
  TimeSeriesPoint,
  LanguageDistribution,
  QuestionTypeDistribution,
  TopQuestion,
} from "@/types/analytics";

export const analyticsApi = {
  getOverview: (
    api: ApiClient,
    params: { period: string; start?: string; end?: string },
  ) =>
    api.get<AnalyticsOverview>("/dashboard/analytics", params),

  getTimeSeries: (
    api: ApiClient,
    params: { period: string; start?: string; end?: string },
  ) =>
    api.get<TimeSeriesPoint[]>("/dashboard/analytics/timeseries", params),

  getLanguages: (
    api: ApiClient,
    params: { period: string; start?: string; end?: string },
  ) =>
    api.get<LanguageDistribution[]>("/dashboard/analytics/languages", params),

  getQuestionTypes: (
    api: ApiClient,
    params: { period: string; start?: string; end?: string },
  ) =>
    api.get<QuestionTypeDistribution[]>(
      "/dashboard/analytics/question-types",
      params,
    ),

  getTopQuestions: (
    api: ApiClient,
    params: { period: string; start?: string; end?: string; limit?: number },
  ) =>
    api.get<TopQuestion[]>("/dashboard/analytics/top-questions", params),
};
