// Thin REST client for the DiskAdvisor backend. Talks to
// `${VITE_API_BASE_URL}/api/v1/...` (defaults to http://localhost:8000).
// If the backend is unreachable (e.g. running the UI standalone for a demo),
// callers fall back to the mock data in ./mockData.ts -- see pages/*.tsx.

export type Decision = "APPROVE" | "APPROVE_REDUCED" | "MANUAL_REVIEW" | "REJECT";

export interface DecisionOut {
  request_id: number;
  decision: Decision;
  score: number | null;
  recommended_gb: number | null;
  reasoning: Record<string, unknown>;
}

export interface RequestOut {
  id: number;
  ticket_id: string;
  hostname: string;
  mount_point: string;
  requested_gb: number;
  requester: string | null;
  created_at: string;
  latest_decision: DecisionOut | null;
}

export interface HostOut {
  id: number;
  hostname: string;
  dt_entity_id: string | null;
  environment: string | null;
  created_at: string;
}

export interface DiskMetricOut {
  mount_point: string;
  capacity_bytes: number;
  used_bytes: number;
  used_pct: number;
  collected_at: string;
}

export interface FilesystemGrowthOut {
  hostname: string;
  mount_point: string;
  growth_pct_points: number;
  growth_gb: number;
  current_used_pct: number;
  current_used_gb: number;
  current_capacity_gb: number;
}

export interface FilesystemUsageOut {
  hostname: string;
  mount_point: string;
  used_pct: number;
  used_gb: number;
  capacity_gb: number;
  collected_at: string;
}

export interface CorrelationPointOut {
  timestamp_ms: number;
  value: number | null;
}

export interface CorrelationSeriesOut {
  metric_id: string;
  label: string;
  unit: string;
  points: CorrelationPointOut[];
}

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${API_PREFIX}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API hatası (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listRequests: () => apiFetch<RequestOut[]>("/requests"),
  getRequest: (id: number) => apiFetch<RequestOut>(`/requests/${id}`),
  overrideDecision: (requestId: number, body: { new_decision: Decision; reason: string; user: string }) =>
    apiFetch(`/requests/${requestId}/override`, { method: "POST", body: JSON.stringify(body) }),
  listHosts: () => apiFetch<HostOut[]>("/hosts"),
  getHostMetrics: (hostname: string, mountPoint?: string) =>
    apiFetch<DiskMetricOut[]>(`/hosts/${hostname}/metrics${mountPoint ? `?mount_point=${mountPoint}` : ""}`),
  getTopGrowth: (days = 7, limit = 10) =>
    apiFetch<FilesystemGrowthOut[]>(`/hosts/top-growth?days=${days}&limit=${limit}`),
  getHighUsage: (thresholdPct = 90) =>
    apiFetch<FilesystemUsageOut[]>(`/hosts/high-usage?threshold_pct=${thresholdPct}`),
  getHostCorrelation: (hostname: string, days = 7) =>
    apiFetch<CorrelationSeriesOut[]>(`/hosts/${hostname}/correlation?days=${days}`),
  evaluate: (body: { ticket_id: string; hostname: string; mount_point: string; requested_gb: number; requester?: string }) =>
    apiFetch<DecisionOut>("/advisor/evaluate", { method: "POST", body: JSON.stringify(body) }),
};
