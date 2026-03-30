import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "@/hooks/use-auth";
import type { Admin, AdminRole } from "@/types";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Params & payloads
// ---------------------------------------------------------------------------

interface AdminsParams {
  page?: number;
  page_size?: number;
  search?: string;
  is_active?: boolean;
}

export interface AdminCreatePayload {
  email: string;
  password: string;
  full_name: string;
  role: AdminRole;
}

export interface AdminUpdatePayload {
  full_name?: string;
  role?: AdminRole;
  is_active?: boolean;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useAdmins(params?: AdminsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["admins", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<Admin>>("/auth/admins", {
        page: params?.page,
        page_size: params?.page_size,
        search: params?.search || undefined,
        is_active:
          params?.is_active !== undefined
            ? String(params.is_active)
            : undefined,
      }),
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateAdmin() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AdminCreatePayload) =>
      api.post<Admin>("/auth/admins", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admins"] });
    },
  });
}

export function useUpdateAdmin() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: AdminUpdatePayload }) =>
      api.patch<Admin>(`/auth/admins/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admins"] });
    },
  });
}

export function useDeactivateAdmin() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (adminId: string) => api.del(`/auth/admins/${adminId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admins"] });
    },
  });
}
