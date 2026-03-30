import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import { analyticsApi } from "@/lib/api/analytics";

export function useAnalyticsOverview(
  period: string,
  start?: string,
  end?: string,
) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["analytics", "overview", period, start, end] as const,
    queryFn: () => analyticsApi.getOverview(api, { period, start, end }),
  });
}

export function useAnalyticsTimeSeries(
  period: string,
  start?: string,
  end?: string,
) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["analytics", "timeseries", period, start, end] as const,
    queryFn: () => analyticsApi.getTimeSeries(api, { period, start, end }),
  });
}

export function useAnalyticsLanguages(
  period: string,
  start?: string,
  end?: string,
) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["analytics", "languages", period, start, end] as const,
    queryFn: () => analyticsApi.getLanguages(api, { period, start, end }),
  });
}

export function useAnalyticsQuestionTypes(
  period: string,
  start?: string,
  end?: string,
) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["analytics", "question-types", period, start, end] as const,
    queryFn: () => analyticsApi.getQuestionTypes(api, { period, start, end }),
  });
}

export function useAnalyticsTopQuestions(
  period: string,
  start?: string,
  end?: string,
  limit: number = 10,
) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["analytics", "top-questions", period, start, end, limit] as const,
    queryFn: () =>
      analyticsApi.getTopQuestions(api, { period, start, end, limit }),
  });
}
