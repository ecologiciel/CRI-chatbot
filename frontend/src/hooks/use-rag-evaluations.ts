import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { RAGEvaluationRun } from "@/types/kb";

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
