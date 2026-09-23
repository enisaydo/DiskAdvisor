import { useEffect, useMemo, useState } from "react";
import { api, CorrelationSeriesOut, DiskMetricOut, HostOut } from "../api/client";
import { mockCorrelationFor, mockHosts, mockMetricsFor } from "../api/mockData";
import LineChart from "../components/LineChart";

// Correlation ("Analiz") page: pick a host (typically one flagged by the
// Dashboard's top-growth / high-usage lists) and look at its disk usage
// trend next to CPU/memory/network/disk-I/O over the same window, to see
// whether a resource spike lines up with the growth -- on-demand, live from
// Dynatrace, not a continuous fleet-wide collection (see backend README).
export default function Analysis() {
  const [hosts, setHosts] = useState<HostOut[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [days, setDays] = useState(7);
  const [diskMetrics, setDiskMetrics] = useState<DiskMetricOut[]>([]);
  const [selectedMount, setSelectedMount] = useState<string>("");
  const [correlation, setCorrelation] = useState<CorrelationSeriesOut[]>([]);
  const [usingMock, setUsingMock] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api
      .listHosts()
      .then((hs) => {
        setHosts(hs);
        if (hs.length) setSelected(hs[0].hostname);
      })
      .catch(() => {
        setHosts(mockHosts);
        setSelected(mockHosts[0].hostname);
      });
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    Promise.all([api.getHostMetrics(selected), api.getHostCorrelation(selected, days)])
      .then(([dm, corr]) => {
        setDiskMetrics(dm);
        setCorrelation(corr);
        setUsingMock(false);
      })
      .catch(() => {
        setDiskMetrics(mockMetricsFor(selected));
        setCorrelation(mockCorrelationFor(selected));
        setUsingMock(true);
      })
      .finally(() => setLoading(false));
  }, [selected, days]);

  // Same reasoning as Host Metrikleri: a host can have several distinct
  // filesystems, so the trend chart is always scoped to one mount point.
  const mountPoints = useMemo(
    () => Array.from(new Set(diskMetrics.map((m) => m.mount_point))).sort(),
    [diskMetrics]
  );

  useEffect(() => {
    if (mountPoints.length && !mountPoints.includes(selectedMount)) {
      setSelectedMount(mountPoints[0]);
    }
  }, [mountPoints, selectedMount]);

  const diskMetricsForMount = useMemo(
    () => diskMetrics.filter((m) => m.mount_point === selectedMount),
    [diskMetrics, selectedMount]
  );

  return (
    <div>
      <h2>Analiz</h2>
      <p className="page-hint">
        Bir host için disk büyümesini CPU/bellek/network/disk I/O ile yan yana inceleyin. Talep anındaki karar
        modülünden bağımsızdır — büyümenin sebebini araştırmak için kullanılır.
      </p>
      {usingMock && <p style={{ color: "#b45309" }}>Backend'e ulaşılamadı, örnek (mock) veri gösteriliyor.</p>}

      <div className="filters">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {hosts.map((h) => (
            <option key={h.id} value={h.hostname}>{h.hostname}</option>
          ))}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Son 7 gün</option>
          <option value={14}>Son 14 gün</option>
          <option value={30}>Son 30 gün</option>
        </select>
        <select value={selectedMount} onChange={(e) => setSelectedMount(e.target.value)} disabled={!mountPoints.length}>
          {mountPoints.map((mp) => (
            <option key={mp} value={mp}>{mp}</option>
          ))}
        </select>
      </div>

      {loading && <p>Yükleniyor...</p>}

      <div className="card">
        <h3>Disk kullanım trendi ({selected || "-"} — {selectedMount || "-"})</h3>
        <LineChart values={diskMetricsForMount.map((m) => m.used_pct)} height={160} min={0} max={100} color="#14213d" />
      </div>

      <div className="analysis-grid">
        {correlation.map((series) => {
          const values = series.points.map((p) => p.value ?? 0);
          const latest = series.points[series.points.length - 1]?.value;
          return (
            <div className="card" key={series.metric_id}>
              <h3>
                {series.label} {latest != null && <span className="metric-latest">({latest.toFixed(1)} {series.unit})</span>}
              </h3>
              <LineChart values={values} height={100} color="#2563eb" />
            </div>
          );
        })}
        {!loading && correlation.length === 0 && <p>Bu host için korelasyon verisi yok.</p>}
      </div>
    </div>
  );
}
