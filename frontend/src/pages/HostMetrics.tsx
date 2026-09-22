import { useEffect, useState } from "react";
import { api, DiskMetricOut, HostOut } from "../api/client";
import { mockHosts, mockMetricsFor } from "../api/mockData";
import LineChart from "../components/LineChart";

export default function HostMetrics() {
  const [hosts, setHosts] = useState<HostOut[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [metrics, setMetrics] = useState<DiskMetricOut[]>([]);

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

  return (
    <div>
      <h2>Host Metrikleri</h2>
      <div className="filters">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {hosts.map((h) => (
            <option key={h.id} value={h.hostname}>{h.hostname}</option>
          ))}
        </select>
      </div>

      <div className="card">
        <h3>Disk kullanım trendi ({selected || "-"})</h3>
        <LineChart values={metrics.map((m) => m.used_pct)} height={200} min={0} max={100} />
      </div>

      <div className="card">
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
            {metrics.map((m, i) => (
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
