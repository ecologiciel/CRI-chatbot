import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { UnansweredQuestion } from "@/types/kb";
import type { LearningStats } from "@/types/learning";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// List questions
// ---------------------------------------------------------------------------

interface LearningQuestionsParams {
  status?: string;
  page?: number;
  page_size?: number;
  date_from?: string;
  date_to?: string;
}

export function useLearningQuestions(params?: LearningQuestionsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["learning-questions", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<UnansweredQuestion>>("/learning/questions", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status,
        date_from: params?.date_from,
        date_to: params?.date_to,
      }),
  });
}

// ---------------------------------------------------------------------------
// Single question detail
// ---------------------------------------------------------------------------

export function useLearningQuestion(questionId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["learning-question", questionId] as const,
    queryFn: () =>
      api.get<UnansweredQuestion>(`/learning/questions/${questionId}`),
    enabled: !!questionId,
  });
}

// ---------------------------------------------------------------------------
// Learning stats
// ---------------------------------------------------------------------------

export function useLearningStats() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["learning-stats"] as const,
    queryFn: () => api.get<LearningStats>("/learning/stats"),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

function useInvalidateLearning() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ["learning-questions"] });
    queryClient.invalidateQueries({ queryKey: ["learning-question"] });
    queryClient.invalidateQueries({ queryKey: ["learning-stats"] });
  };
}

export function useGenerateProposal() {
  const api = useApiClient();
  const invalidate = useInvalidateLearning();

  return useMutation({
    mutationFn: (questionId: string) =>
      api.post<UnansweredQuestion>(
        `/learning/questions/${questionId}/generate`,
      ),
    onSuccess: invalidate,
  });
}

export function useApproveQuestion() {
  const api = useApiClient();
  const invalidate = useInvalidateLearning();

  return useMutation({
    mutationFn: ({
      questionId,
      data,
    }: {
      questionId: string;
      data: { proposed_answer?: string; review_note?: string };
    }) =>
      api.post<UnansweredQuestion>(
        `/learning/questions/${questionId}/approve`,
        data,
      ),
    onSuccess: invalidate,
  });
}

export function useRejectQuestion() {
  const api = useApiClient();
  const invalidate = useInvalidateLearning();

  return useMutation({
    mutationFn: ({
      questionId,
      data,
    }: {
      questionId: string;
      data: { review_note?: string };
    }) =>
      api.post<UnansweredQuestion>(
        `/learning/questions/${questionId}/reject`,
        data,
      ),
    onSuccess: invalidate,
  });
}

export function useEditProposal() {
  const api = useApiClient();
  const invalidate = useInvalidateLearning();

  return useMutation({
    mutationFn: ({
      questionId,
      data,
    }: {
      questionId: string;
      data: { proposed_answer: string; review_note?: string };
    }) =>
      api.post<UnansweredQuestion>(
        `/learning/questions/${questionId}/edit`,
        data,
      ),
    onSuccess: invalidate,
  });
}
