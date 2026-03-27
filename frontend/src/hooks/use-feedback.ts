import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { UnansweredQuestion, UnansweredQuestionStatus } from "@/types/kb";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Feedback stats
// ---------------------------------------------------------------------------

interface FeedbackStats {
  total: number;
  positive: number;
  negative: number;
  question: number;
  satisfaction_rate: number;
}

export function useFeedbackStats() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["feedback-stats"] as const,
    queryFn: () => api.get<FeedbackStats>("/feedback/stats"),
  });
}

// ---------------------------------------------------------------------------
// Unanswered questions
// ---------------------------------------------------------------------------

interface UnansweredParams {
  page?: number;
  page_size?: number;
  status?: UnansweredQuestionStatus;
}

export function useUnansweredQuestions(params?: UnansweredParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["unanswered", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<UnansweredQuestion>>("/feedback/unanswered", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status,
      }),
  });
}

// ---------------------------------------------------------------------------
// Review mutation
// ---------------------------------------------------------------------------

interface ReviewQuestionData {
  proposed_answer?: string;
  status: UnansweredQuestionStatus;
  review_note?: string;
}

export function useReviewQuestion() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      questionId,
      data,
    }: {
      questionId: string;
      data: ReviewQuestionData;
    }) => api.patch<UnansweredQuestion>(`/feedback/unanswered/${questionId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["unanswered"] });
      queryClient.invalidateQueries({ queryKey: ["feedback-stats"] });
    },
  });
}
