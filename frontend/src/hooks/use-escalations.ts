import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef, useState, useCallback } from "react";
import { useApiClient, useAuth } from "@/hooks/use-auth";
import type {
  Escalation,
  EscalationStatus,
  EscalationPriority,
  EscalationStatsData,
  EscalationMessage,
  EscalationRespondPayload,
  EscalationResolvePayload,
  EscalationWebSocketEvent,
} from "@/types/escalation";
import type { PaginatedResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

interface EscalationsParams {
  page?: number;
  page_size?: number;
  status?: EscalationStatus;
  priority?: EscalationPriority;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useEscalations(params?: EscalationsParams) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["escalations", params] as const,
    queryFn: () =>
      api.get<PaginatedResponse<Escalation>>("/escalations", {
        page: params?.page,
        page_size: params?.page_size,
        status: params?.status || undefined,
        priority: params?.priority || undefined,
      }),
  });
}

export function useEscalation(escalationId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["escalations", "detail", escalationId] as const,
    queryFn: () => api.get<Escalation>(`/escalations/${escalationId}`),
    enabled: !!escalationId,
  });
}

export function useEscalationStats() {
  const api = useApiClient();
  return useQuery({
    queryKey: ["escalation-stats"] as const,
    queryFn: () => api.get<EscalationStatsData>("/escalations/stats"),
    refetchInterval: 30_000,
  });
}

export function useEscalationConversation(escalationId: string | null) {
  const api = useApiClient();
  return useQuery({
    queryKey: ["escalations", escalationId, "conversation"] as const,
    queryFn: () =>
      api.get<EscalationMessage[]>(`/escalations/${escalationId}/conversation`),
    enabled: !!escalationId,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useAssignEscalation() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api.post<Escalation>(`/escalations/${id}/assign`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["escalations"] });
      queryClient.invalidateQueries({ queryKey: ["escalation-stats"] });
    },
  });
}

export function useRespondEscalation() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: EscalationRespondPayload;
    }) => api.post<Escalation>(`/escalations/${id}/respond`, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["escalations", variables.id, "conversation"],
      });
      queryClient.invalidateQueries({ queryKey: ["escalations"] });
    },
  });
}

export function useCloseEscalation() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: EscalationResolvePayload;
    }) => api.post<Escalation>(`/escalations/${id}/close`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["escalations"] });
      queryClient.invalidateQueries({ queryKey: ["escalation-stats"] });
    },
  });
}

// ---------------------------------------------------------------------------
// WebSocket hook
// ---------------------------------------------------------------------------

const MAX_RECONNECT_DELAY = 30_000;
const PING_INTERVAL = 30_000;
const WS_BASE =
  process.env.NEXT_PUBLIC_WS_URL ??
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
    /^http/,
    "ws",
  );

export function useEscalationWebSocket() {
  const { admin } = useAuth();
  const api = useApiClient();
  const queryClient = useQueryClient();

  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] =
    useState<EscalationWebSocketEvent | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const reconnectAttempts = useRef(0);
  const mountedRef = useRef(true);

  const tenantId = admin?.tenant_id;

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["escalations"] });
    queryClient.invalidateQueries({ queryKey: ["escalation-stats"] });
  }, [queryClient]);

  const connect = useCallback(() => {
    if (!tenantId || !mountedRef.current) return;

    const token = (api as unknown as { getAccessToken?: () => string | null })
      .getAccessToken
      ? (api as unknown as { getAccessToken: () => string | null }).getAccessToken()
      : null;

    if (!token) return;

    const wsUrl = `${WS_BASE}/ws/escalations/${tenantId}?token=${token}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setIsConnected(true);
        reconnectAttempts.current = 0;

        // Start periodic ping
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send("ping");
          }
        }, PING_INTERVAL);
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        if (event.data === "pong") return;

        try {
          const parsed: EscalationWebSocketEvent = JSON.parse(event.data);
          setLastEvent(parsed);
          invalidateAll();
        } catch {
          // Ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        clearInterval(pingIntervalRef.current);

        // Reconnect with exponential backoff
        const delay = Math.min(
          1000 * Math.pow(2, reconnectAttempts.current),
          MAX_RECONNECT_DELAY,
        );
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectAttempts.current++;
          connect();
        }, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      // WebSocket constructor can throw if URL is invalid
    }
  }, [tenantId, api, invalidateAll]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
      clearTimeout(reconnectTimeoutRef.current);
      clearInterval(pingIntervalRef.current);
    };
  }, [connect]);

  return { isConnected, lastEvent };
}
