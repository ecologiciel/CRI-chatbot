import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApiClient, useAuth } from "@/hooks/use-auth";
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
  const { admin } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AdminCreatePayload) => {
      const tenantId = admin?.role === "super_admin"
        ? sessionStorage.getItem("cri_selected_tenant_id")
        : admin?.tenant_id;
      if (!tenantId) throw new Error("Sélectionnez une institution avant de créer un compte.");
      return api.post<Admin>("/auth/admins", { ...data, tenant_id: tenantId });
    },
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
