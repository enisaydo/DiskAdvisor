// Local mock data used to render pages without a running backend (demo/dev).
import type { CorrelationSeriesOut, DiskMetricOut, FilesystemGrowthOut, FilesystemUsageOut, HostOut, RequestOut } from "./client";

export const mockRequests: RequestOut[] = [
  {
    id: 1,
    ticket_id: "TCK-10021",
    hostname: "app01.prod.example.com",
    mount_point: "/var/log",
    requested_gb: 50,
    requester: "ahmet.yilmaz",
    created_at: "2026-09-20T09:12:00Z",
    latest_decision: {
      request_id: 1,
      decision: "REJECT",
      score: 18.4,
      recommended_gb: null,
      reasoning: { action: "/var/log dizinine logrotate ekleyin, ~38 GB kazanılır." },
    },
  },
  {
    id: 2,
    ticket_id: "TCK-10022",
    hostname: "db03.prod.example.com",
    mount_point: "/data",
    requested_gb: 200,
    requester: "elif.demir",
    created_at: "2026-09-21T14:03:00Z",
    latest_decision: {
      request_id: 2,
      decision: "APPROVE",
      score: 88.2,
      recommended_gb: 200,
      reasoning: { action: "Talep gerekçelendirilmiş bulundu, olduğu gibi onaylandı." },
    },
  },
  {
    id: 3,
    ticket_id: "TCK-10023",
    hostname: "web12.prod.example.com",
    mount_point: "/",
    requested_gb: 30,
    requester: "mehmet.kaya",
    created_at: "2026-09-21T16:45:00Z",
    latest_decision: {
      request_id: 3,
      decision: "APPROVE_REDUCED",
      score: 62.1,
      recommended_gb: 18,
      reasoning: { action: "Yaklaşık 12 GB log temizliği ile geri kazanılabilir, 18 GB önerildi." },
    },
  },
  {
    id: 4,
    ticket_id: "TCK-10024",
    hostname: "batch07.prod.example.com",
    mount_point: "/opt",
    requested_gb: 100,
    requester: "zeynep.arslan",
    created_at: "2026-09-22T08:30:00Z",
    latest_decision: {
      request_id: 4,
      decision: "MANUAL_REVIEW",
      score: null,
      recommended_gb: null,
      reasoning: { audit: "SSH/Ansible audit sunucuya erişemedi; karar güvenlik gereği MANUAL_REVIEW." },
    },
  },
];

export const mockHosts: HostOut[] = [
  { id: 1, hostname: "app01.prod.example.com", dt_entity_id: "HOST-A1B2C3", environment: "prod", created_at: "2026-01-10T00:00:00Z" },
  { id: 2, hostname: "db03.prod.example.com", dt_entity_id: "HOST-D4E5F6", environment: "prod", created_at: "2026-01-10T00:00:00Z" },
  { id: 3, hostname: "web12.prod.example.com", dt_entity_id: "HOST-G7H8I9", environment: "prod", created_at: "2026-01-10T00:00:00Z" },
];

export const mockTopGrowth: FilesystemGrowthOut[] = [
  { hostname: "batch07.prod.example.com", mount_point: "/opt", growth_pct_points: 34.2, growth_gb: 68.4, current_used_pct: 91.5, current_used_gb: 183, current_capacity_gb: 200 },
  { hostname: "app01.prod.example.com", mount_point: "/var/log", growth_pct_points: 28.7, growth_gb: 14.4, current_used_pct: 88.1, current_used_gb: 44, current_capacity_gb: 50 },
  { hostname: "db03.prod.example.com", mount_point: "/data", growth_pct_points: 19.3, growth_gb: 386, current_used_pct: 76.2, current_used_gb: 1524, current_capacity_gb: 2000 },
  { hostname: "web12.prod.example.com", mount_point: "/", growth_pct_points: 15.6, growth_gb: 4.7, current_used_pct: 62.4, current_used_gb: 18.7, current_capacity_gb: 30 },
  { hostname: "web13.prod.example.com", mount_point: "/", growth_pct_points: 12.1, growth_gb: 3.6, current_used_pct: 58.9, current_used_gb: 17.7, current_capacity_gb: 30 },
];

export const mockHighUsage: FilesystemUsageOut[] = [
  { hostname: "batch07.prod.example.com", mount_point: "/opt", used_pct: 91.5, used_gb: 183, capacity_gb: 200, collected_at: "2026-09-22T08:00:00Z" },
  { hostname: "app01.prod.example.com", mount_point: "/var/log", used_pct: 88.1, used_gb: 44, capacity_gb: 50, collected_at: "2026-09-22T08:00:00Z" },
  { hostname: "app02.prod.example.com", mount_point: "/tmp", used_pct: 93.8, used_gb: 9.4, capacity_gb: 10, collected_at: "2026-09-22T08:00:00Z" },
];

export function mockCorrelationFor(_hostname: string): CorrelationSeriesOut[] {
  const start = Date.UTC(2026, 8, 15, 0, 0, 0);
  const hour = 60 * 60 * 1000;
  const series = (label: string, unit: string, gen: (i: number) => number): CorrelationSeriesOut => ({
    metric_id: label,
    label,
    unit,
    points: Array.from({ length: 48 }).map((_, i) => ({ timestamp_ms: start + i * hour, value: gen(i) })),
  });
  return [
    series("CPU kullanımı", "%", (i) => 20 + (i > 30 ? 45 : 0) + Math.sin(i / 3) * 5),
    series("Bellek kullanımı", "%", (i) => 55 + Math.sin(i / 5) * 4),
    series("Disk yazma", "bytes/s", (i) => (i > 30 ? 80_000_000 : 2_000_000)),
    series("Network gönderilen", "bytes/s", (i) => (i > 30 ? 30_000_000 : 1_000_000)),
  ];
}

export function mockMetricsFor(hostname: string): DiskMetricOut[] {
  const base = 40;
  return Array.from({ length: 14 }).map((_, i) => {
    const usedPct = Math.min(95, base + i * 2.5);
    const capacity = 100 * 1024 ** 3;
    return {
      mount_point: "/var/log",
      capacity_bytes: capacity,
      used_bytes: Math.round((usedPct / 100) * capacity),
      used_pct: Math.round(usedPct * 10) / 10,
      collected_at: new Date(Date.UTC(2026, 8, 8 + i)).toISOString(),
    };
  });
}
