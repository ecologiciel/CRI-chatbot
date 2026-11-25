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
    refetchInterval: (query) => query.state.data?.items.some(
      (document) => document.status === "pending" || document.status === "indexing",
    ) ? 15_000 : false,
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
  source_url?: string;
  source_authority?: string;
  source_reference?: string;
  source_version?: string;
  published_at?: string;
  expires_at?: string;
}

export function useUploadDocument() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ file, title, category, language, source_url, source_authority, source_reference, source_version, published_at, expires_at }: UploadDocumentParams) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", title);
      if (category) formData.append("category", category);
      if (language) formData.append("language", language);
      if (source_url) formData.append("source_url", source_url);
      if (source_authority) formData.append("source_authority", source_authority);
      if (source_reference) formData.append("source_reference", source_reference);
      if (source_version) formData.append("source_version", source_version);
      if (published_at) formData.append("published_at", published_at);
      if (expires_at) formData.append("expires_at", expires_at);
      return api.upload<KBDocument>("/kb/documents", formData);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useValidateDocument() {
  const api = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (document: KBDocument) =>
      api.post<KBDocument>(`/kb/documents/${document.id}/validate`, {
        source_authority: document.source_authority,
        source_reference: document.source_reference,
        source_version: document.source_version,
        source_url: document.source_url,
        published_at: document.published_at,
        expires_at: document.expires_at,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
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
