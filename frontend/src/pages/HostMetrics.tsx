import { useEffect, useMemo, useState } from "react";
import { api, DiskMetricOut, HostOut } from "../api/client";
import { mockHosts, mockMetricsFor } from "../api/mockData";
import LineChart from "../components/LineChart";

export default function HostMetrics() {
  const [hosts, setHosts] = useState<HostOut[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [metrics, setMetrics] = useState<DiskMetricOut[]>([]);
  const [selectedMount, setSelectedMount] = useState<string>("");

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
    api
      .getHostMetrics(selected)
      .then(setMetrics)
      .catch(() => setMetrics(mockMetricsFor(selected)));
  }, [selected]);

  // A host can have several distinct filesystems (/, /u01, /opt/agents, ...).
  // Mixing their used_pct into one chart/series produces a meaningless
  // interleaved line, so the chart and table are always scoped to one
  // mount point at a time.
  const mountPoints = useMemo(
    () => Array.from(new Set(metrics.map((m) => m.mount_point))).sort(),
    [metrics]
  );

  useEffect(() => {
    if (mountPoints.length && !mountPoints.includes(selectedMount)) {
      setSelectedMount(mountPoints[0]);
    }
  }, [mountPoints, selectedMount]);

  const metricsForMount = useMemo(
    () => metrics.filter((m) => m.mount_point === selectedMount),
    [metrics, selectedMount]
  );

  return (
    <div>
      <h2>Host Metrikleri</h2>
      <div className="filters">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
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
        <h3>Disk kullanım trendi ({selected || "-"} — {selectedMount || "-"})</h3>
        <LineChart values={metricsForMount.map((m) => m.used_pct)} height={200} min={0} max={100} />
      </div>

      <div className="card">
        <h3>Bu host'taki tüm file system'ler</h3>
        <table>
          <thead>
            <tr>
              <th>Mount</th>
              <th>Kullanım %</th>
              <th>Kullanılan / Kapasite (GB)</th>
              <th>Zaman</th>
            </tr>
          </thead>
          <tbody>
            {metricsForMount.map((m, i) => (
              <tr key={i}>
                <td>{m.mount_point}</td>
                <td>{m.used_pct.toFixed(1)}%</td>
                <td>
                  {(m.used_bytes / 1024 ** 3).toFixed(1)} / {(m.capacity_bytes / 1024 ** 3).toFixed(1)}
                </td>
                <td>{new Date(m.collected_at).toLocaleString("tr-TR")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
