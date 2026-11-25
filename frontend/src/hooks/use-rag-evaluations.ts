import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { RAGEvaluationCase, RAGEvaluationRun } from "@/types/kb";

export function useRAGEvaluationCases() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["rag-evaluation-cases"],
    queryFn: () => api.get<RAGEvaluationCase[]>("/kb/evaluations/cases"),
  });
}

export function useCreateRAGEvaluationCase() {
  const api = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Pick<RAGEvaluationCase, "query" | "language" | "expected_document_ids" | "expects_abstention">) =>
      api.post<RAGEvaluationCase>("/kb/evaluations/cases", data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rag-evaluation-cases"] }),
  });
}

export function useRAGEvaluationRuns() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["rag-evaluation-runs"],
    queryFn: () => api.get<RAGEvaluationRun[]>("/kb/evaluations/runs"),
  });
}

export function useRunRAGEvaluation() {
  const api = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<RAGEvaluationRun>("/kb/evaluations/runs"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rag-evaluation-runs"] }),
  });
}
