import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type {
  Contact,
  ContactDetail,
  ContactCreatePayload,
  ContactUpdatePayload,
  ImportResult,
  OptInStatus,
  ContactLanguage,
} from "@/types/contact";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

interface ContactsParams {
  page?: number;
  page_size?: number;
  search?: string;
  opt_in_status?: OptInStatus;
  language?: ContactLanguage;
  tags?: string;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useContacts(params?: ContactsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["contacts", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<Contact>>("/contacts", {
        page: params?.page,
        page_size: params?.page_size,
        search: params?.search || undefined,
        opt_in_status: params?.opt_in_status,
        language: params?.language,
        tags: params?.tags || undefined,
      }),
  });
}

export function useContact(contactId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["contacts", "detail", contactId] as const,
    queryFn: () => api.get<ContactDetail>(`/contacts/${contactId}`),
    enabled: !!contactId,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateContact() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ContactCreatePayload) =>
      api.post<Contact>("/contacts", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useUpdateContact() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ContactUpdatePayload }) =>
      api.patch<Contact>(`/contacts/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useDeleteContact() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (contactId: string) => api.del(`/contacts/${contactId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useImportContacts() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return api.upload<ImportResult>("/contacts/import", formData);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}
