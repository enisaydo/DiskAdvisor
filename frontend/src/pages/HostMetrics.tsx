import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, DiskMetricOut, HostOut } from "../api/client";
import { mockHosts, mockMetricsFor } from "../api/mockData";
import LineChart from "../components/LineChart";

export default function HostMetrics() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [hosts, setHosts] = useState<HostOut[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [metrics, setMetrics] = useState<DiskMetricOut[]>([]);
  const [selectedMount, setSelectedMount] = useState<string>("");

  useEffect(() => {
    api
      .listHosts()
      .then((hs) => {
        setHosts(hs);
        const fromUrl = searchParams.get("host");
        if (fromUrl && hs.some((h) => h.hostname === fromUrl)) setSelected(fromUrl);
        else if (hs.length) setSelected(hs[0].hostname);
      })
      .catch(() => {
        setHosts(mockHosts);
        const fromUrl = searchParams.get("host");
        setSelected(fromUrl && mockHosts.some((h) => h.hostname === fromUrl) ? fromUrl : mockHosts[0].hostname);
      });
    // Deep-linked from Dashboard's top-growth/high-usage rows (?host=&mount=);
    // only applied on first load, not on every searchParams change, so
    // switching hosts/mounts via the selects doesn't fight the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    api
      .getHostMetrics(selected)
      .then(setMetrics)
      .catch(() => setMetrics(mockMetricsFor(selected)));
  }, [selected]);

  // A host can have several distinct filesystems (/, /u01, /opt/agents, ...).
  // Mixing their used_pct into one chart/series produces a meaningless
  // interleaved line, so the trend chart is always scoped to one mount
  // point at a time.
  const mountPoints = useMemo(
    () => Array.from(new Set(metrics.map((m) => m.mount_point))).sort(),
    [metrics]
  );

  useEffect(() => {
    if (!mountPoints.length) return;
    const fromUrl = searchParams.get("mount");
    if (fromUrl && mountPoints.includes(fromUrl)) {
      setSelectedMount(fromUrl);
    } else if (!mountPoints.includes(selectedMount)) {
      setSelectedMount(mountPoints[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mountPoints]);

  // Latest sample per mount point -- the disk-by-disk overview of this host,
  // independent of which one is currently selected for the trend chart.
  const latestByMount = useMemo(() => {
    const map = new Map<string, DiskMetricOut>();
    for (const m of metrics) {
      const existing = map.get(m.mount_point);
      if (!existing || m.collected_at > existing.collected_at) map.set(m.mount_point, m);
    }
    return Array.from(map.values()).sort((a, b) => b.used_pct - a.used_pct);
  }, [metrics]);

  const metricsForMount = useMemo(
    () => metrics.filter((m) => m.mount_point === selectedMount),
    [metrics, selectedMount]
  );

  function selectHost(hostname: string) {
    setSelected(hostname);
    setSelectedMount("");
    setSearchParams({});
  }

  return (
    <div>
      <h2>Host Metrikleri</h2>
      <div className="filters">
        <select value={selected} onChange={(e) => selectHost(e.target.value)}>
          {hosts.map((h) => (
            <option key={h.id} value={h.hostname}>{h.hostname}</option>
          ))}
        </select>
        <select value={selectedMount} onChange={(e) => setSelectedMount(e.target.value)} disabled={!mountPoints.length}>
          {mountPoints.map((mp) => (
            <option key={mp} value={mp}>{mp}</option>
          ))}
        </select>
      </div>

      <div className="card">
        <h3>Bu host'taki tüm file system'ler ({latestByMount.length})</h3>
        <p className="page-hint">Bir satıra tıklayınca o file system'in trendi aşağıda açılır.</p>
        <table>
          <thead>
            <tr>
              <th>Mount</th>
              <th>Kullanım %</th>
              <th>Kullanılan / Kapasite (GB)</th>
              <th>Son ölçüm</th>
            </tr>
          </thead>
          <tbody>
            {latestByMount.map((m) => (
              <tr
                key={m.mount_point}
                className={m.mount_point === selectedMount ? "row-selected" : undefined}
                onClick={() => setSelectedMount(m.mount_point)}
              >
                <td>{m.mount_point}</td>
                <td>
                  <span className={m.used_pct >= 90 ? "badge badge-REJECT" : m.used_pct >= 75 ? "badge badge-MANUAL_REVIEW" : "badge badge-APPROVE"}>
                    {m.used_pct.toFixed(1)}%
                  </span>
                </td>
                <td>
                  {(m.used_bytes / 1024 ** 3).toFixed(1)} / {(m.capacity_bytes / 1024 ** 3).toFixed(1)}
                </td>
                <td>{new Date(m.collected_at).toLocaleString("tr-TR")}</td>
              </tr>
            ))}
            {latestByMount.length === 0 && (
              <tr>
                <td colSpan={4}>Bu host için henüz metrik verisi yok.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Disk kullanım trendi ({selected || "-"} — {selectedMount || "-"})</h3>
        <LineChart
          values={metricsForMount.map((m) => m.used_pct)}
          timestamps={metricsForMount.map((m) => new Date(m.collected_at).getTime())}
          height={200}
          min={0}
          max={100}
        />
        {selected && (
          <Link className="inline-link" to={`/analysis?host=${encodeURIComponent(selected)}`}>
            Bu host için CPU/bellek/network korelasyon analizine git →
          </Link>
        )}
      </div>
    </div>
  );
}
