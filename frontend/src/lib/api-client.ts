import type { Admin } from "@/types";
import type { LoginCredentials, AuthTokenResponse } from "@/types/auth";
import type { ApiErrorResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Decode the payload segment of a JWT (no crypto — validation is server-side). */
function decodeJwtPayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  if (parts.length !== 3) return {};
  // base64url → base64 → decode
  const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
  try {
    return JSON.parse(atob(base64));
  } catch {
    return {};
  }
}

/** Extract tenant_id from a JWT access token. */
export function extractTenantIdFromJWT(token: string): string | null {
  const payload = decodeJwtPayload(token);
  return typeof payload.tenant_id === "string" ? payload.tenant_id : null;
}

// ---------------------------------------------------------------------------
// API Error
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ---------------------------------------------------------------------------
// API Client
// ---------------------------------------------------------------------------

interface ApiClientConfig {
  baseUrl: string;
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  setTokens: (access: string, refresh: string) => void;
  onAuthFailure: () => void;
}

const API_PREFIX = "/api/v1";

export class ApiClient {
  private config: ApiClientConfig;
  private refreshPromise: Promise<boolean> | null = null;

  constructor(config: ApiClientConfig) {
    this.config = config;
  }

  // ── Core request ────────────────────────────────────────────────────────

  private async request<T>(
    path: string,
    options: RequestInit = {},
    skipAuth = false,
  ): Promise<T> {
    const url = `${this.config.baseUrl}${API_PREFIX}${path}`;

    const headers = new Headers(options.headers);

    if (!skipAuth) {
      const token = this.config.getAccessToken();
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
        const tenantId = extractTenantIdFromJWT(token);
        if (tenantId) {
          headers.set("X-Tenant-ID", tenantId);
        }
      }
    }

    if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    const response = await fetch(url, { ...options, headers });

    // ── 401 → attempt token refresh then retry once ──
    if (response.status === 401 && !skipAuth) {
      const refreshed = await this.tryRefresh();
      if (refreshed) {
        // Retry with new token
        const retryHeaders = new Headers(options.headers);
        const newToken = this.config.getAccessToken();
        if (newToken) {
          retryHeaders.set("Authorization", `Bearer ${newToken}`);
          const tenantId = extractTenantIdFromJWT(newToken);
          if (tenantId) {
            retryHeaders.set("X-Tenant-ID", tenantId);
          }
        }
        if (
          !retryHeaders.has("Content-Type") &&
          !(options.body instanceof FormData)
        ) {
          retryHeaders.set("Content-Type", "application/json");
        }
        const retryResponse = await fetch(url, {
          ...options,
          headers: retryHeaders,
        });
        if (!retryResponse.ok) {
          await this.handleErrorResponse(retryResponse);
        }
        if (retryResponse.status === 204) return undefined as T;
        return retryResponse.json() as Promise<T>;
      }
      // Refresh failed — force logout
      this.config.onAuthFailure();
      throw new ApiError(401, "AuthenticationError", "Session expired");
    }

    if (!response.ok) {
      await this.handleErrorResponse(response);
    }

    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  private async handleErrorResponse(response: Response): Promise<never> {
    let body: ApiErrorResponse | null = null;
    try {
      body = await response.json();
    } catch {
      // response body is not JSON
    }
    throw new ApiError(
      response.status,
      body?.error ?? "UnknownError",
      body?.message ?? `Request failed with status ${response.status}`,
      body?.details,
    );
  }

  // ── Token refresh (mutex) ───────────────────────────────────────────────

  private async tryRefresh(): Promise<boolean> {
    // If a refresh is already in-flight, wait for it
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = this.doRefresh();
    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }

  private async doRefresh(): Promise<boolean> {
    const refreshToken = this.config.getRefreshToken();
    if (!refreshToken) return false;

    try {
      const url = `${this.config.baseUrl}${API_PREFIX}/auth/refresh`;
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) return false;

      const data = (await response.json()) as AuthTokenResponse;
      this.config.setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    }
  }

  // ── Convenience methods ─────────────────────────────────────────────────

  async get<T>(
    path: string,
    params?: Record<string, string | number | undefined>,
  ): Promise<T> {
    let queryString = "";
    if (params) {
      const filtered = Object.entries(params).filter(
        ([, v]) => v !== undefined,
      );
      if (filtered.length > 0) {
        queryString =
          "?" + new URLSearchParams(
            filtered.map(([k, v]) => [k, String(v)]),
          ).toString();
      }
    }
    return this.request<T>(`${path}${queryString}`);
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  async del(path: string): Promise<void> {
    return this.request<void>(path, { method: "DELETE" });
  }

  async upload<T>(path: string, formData: FormData): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      body: formData,
      // No Content-Type header — browser sets multipart boundary
    });
  }

  // ── Auth endpoints (skipAuth — no Bearer needed for login/refresh) ──────

  async login(credentials: LoginCredentials): Promise<AuthTokenResponse> {
    return this.request<AuthTokenResponse>(
      "/auth/login",
      {
        method: "POST",
        body: JSON.stringify(credentials),
      },
      true,
    );
  }

  async refreshToken(refreshToken: string): Promise<AuthTokenResponse> {
    return this.request<AuthTokenResponse>(
      "/auth/refresh",
      {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      },
      true,
    );
  }

  async getMe(): Promise<Admin> {
    return this.request<Admin>("/auth/me");
  }

  async logout(refreshToken: string): Promise<void> {
    return this.request<void>("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  }
}

// ---------------------------------------------------------------------------
// Singleton — configured by AuthProvider
// ---------------------------------------------------------------------------

let _apiClient: ApiClient | null = null;

export function getApiClient(): ApiClient {
  if (!_apiClient) {
    throw new Error(
      "ApiClient not initialized. Wrap your app with <AuthProvider>.",
    );
  }
  return _apiClient;
}

export function initApiClient(config: ApiClientConfig): ApiClient {
  _apiClient = new ApiClient(config);
  return _apiClient;
}
