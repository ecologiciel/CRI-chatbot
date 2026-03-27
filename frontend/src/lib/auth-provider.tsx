"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import type { Admin } from "@/types";
import type { LoginCredentials } from "@/types/auth";
import { ApiClient, initApiClient, ApiError } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Context types
// ---------------------------------------------------------------------------

interface AuthContextValue {
  admin: Admin | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  apiClient: ApiClient;
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_TOKEN_KEY = "cri_refresh_token";
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  // Access token lives in a ref (memory only — never localStorage)
  const accessTokenRef = React.useRef<string | null>(null);

  const [admin, setAdmin] = React.useState<Admin | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);

  // ── Stable callbacks for ApiClient ──────────────────────────────────────

  const getAccessToken = React.useCallback(() => accessTokenRef.current, []);

  const getRefreshToken = React.useCallback(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }, []);

  const setTokens = React.useCallback(
    (access: string, refresh: string) => {
      accessTokenRef.current = access;
      if (typeof window !== "undefined") {
        localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
      }
    },
    [],
  );

  const clearTokens = React.useCallback(() => {
    accessTokenRef.current = null;
    if (typeof window !== "undefined") {
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    }
    setAdmin(null);
  }, []);

  const onAuthFailure = React.useCallback(() => {
    clearTokens();
    router.replace("/login");
  }, [clearTokens, router]);

  // ── Initialize ApiClient singleton ──────────────────────────────────────

  const apiClient = React.useMemo(
    () =>
      initApiClient({
        baseUrl: API_BASE_URL,
        getAccessToken,
        getRefreshToken,
        setTokens,
        onAuthFailure,
      }),
    [getAccessToken, getRefreshToken, setTokens, onAuthFailure],
  );

  // ── Session restoration on mount ────────────────────────────────────────

  React.useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
      if (!storedRefresh) {
        setIsLoading(false);
        return;
      }

      try {
        // Attempt to refresh the access token
        const tokens = await apiClient.refreshToken(storedRefresh);
        if (cancelled) return;

        setTokens(tokens.access_token, tokens.refresh_token);

        // Fetch admin profile
        const profile = await apiClient.getMe();
        if (cancelled) return;

        setAdmin(profile);
      } catch {
        // Refresh failed — session expired
        if (!cancelled) {
          clearTokens();
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    restoreSession();
    return () => {
      cancelled = true;
    };
  }, [apiClient, setTokens, clearTokens]);

  // ── Login ───────────────────────────────────────────────────────────────

  const login = React.useCallback(
    async (credentials: LoginCredentials) => {
      const tokens = await apiClient.login(credentials);
      setTokens(tokens.access_token, tokens.refresh_token);

      const profile = await apiClient.getMe();
      setAdmin(profile);
    },
    [apiClient, setTokens],
  );

  // ── Logout ──────────────────────────────────────────────────────────────

  const logout = React.useCallback(async () => {
    const refreshToken = getRefreshToken();
    try {
      if (refreshToken) {
        await apiClient.logout(refreshToken);
      }
    } catch {
      // Ignore logout API errors — we clear tokens regardless
    }
    clearTokens();
    router.replace("/login");
  }, [apiClient, getRefreshToken, clearTokens, router]);

  // ── Context value ───────────────────────────────────────────────────────

  const value = React.useMemo<AuthContextValue>(
    () => ({
      admin,
      isAuthenticated: admin !== null,
      isLoading,
      apiClient,
      login,
      logout,
    }),
    [admin, isLoading, apiClient, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within <AuthProvider>");
  }
  return context;
}

export function useApiClient(): ApiClient {
  return useAuth().apiClient;
}

export { ApiError };
