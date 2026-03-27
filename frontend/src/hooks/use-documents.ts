import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { KBDocument, KBDocumentStatus } from "@/types/kb";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

interface DocumentsParams {
  page?: number;
  page_size?: number;
  status?: KBDocumentStatus;
  category?: string;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useDocuments(params?: DocumentsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["documents", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<KBDocument>>("/kb/documents", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status,
        category: params?.category,
      }),
  });
}

export function useDocument(documentId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["documents", documentId] as const,
    queryFn: () => api.get<KBDocument>(`/kb/documents/${documentId}`),
    enabled: !!documentId,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

interface UploadDocumentParams {
  file: File;
  title: string;
  category?: string;
  language?: string;
}

export function useUploadDocument() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ file, title, category, language }: UploadDocumentParams) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", title);
      if (category) formData.append("category", category);
      if (language) formData.append("language", language);
      return api.upload<KBDocument>("/kb/documents", formData);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useDeleteDocument() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) => api.del(`/kb/documents/${documentId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useReindexDocument() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) =>
      api.post<KBDocument>(`/kb/documents/${documentId}/reindex`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
