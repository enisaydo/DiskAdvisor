import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, FilesystemGrowthOut, FilesystemUsageOut, RequestOut } from "../api/client";
import { mockHighUsage, mockRequests, mockTopGrowth } from "../api/mockData";

const DECISIONS = ["APPROVE", "APPROVE_REDUCED", "MANUAL_REVIEW", "REJECT"] as const;

function hostMetricsLink(hostname: string, mountPoint: string): string {
  return `/hosts?host=${encodeURIComponent(hostname)}&mount=${encodeURIComponent(mountPoint)}`;
}

export default function Dashboard() {
  const [requests, setRequests] = useState<RequestOut[]>([]);
  const [topGrowth, setTopGrowth] = useState<FilesystemGrowthOut[]>([]);
  const [highUsage, setHighUsage] = useState<FilesystemUsageOut[]>([]);
  const [usingMock, setUsingMock] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .listRequests()
      .then(setRequests)
      .catch(() => {
        setRequests(mockRequests);
        setUsingMock(true);
      });
    api
      .getTopGrowth(7, 10)
      .then(setTopGrowth)
      .catch(() => setTopGrowth(mockTopGrowth));
    api
      .getHighUsage(90)
      .then(setHighUsage)
      .catch(() => setHighUsage(mockHighUsage));
  }, []);

  const counts = Object.fromEntries(
    DECISIONS.map((d) => [d, requests.filter((r) => r.latest_decision?.decision === d).length])
  );
  const avgScore =
    requests.filter((r) => r.latest_decision?.score != null).reduce((s, r) => s + (r.latest_decision!.score ?? 0), 0) /
    (requests.filter((r) => r.latest_decision?.score != null).length || 1);

  return (
    <div>
      <h2>Özet</h2>
      {usingMock && <p style={{ color: "#b45309" }}>Backend'e ulaşılamadı, örnek (mock) veri gösteriliyor.</p>}
      <div className="kpi-row">
        <div className="kpi">
          <div className="value">{requests.length}</div>
          <div className="label">Toplam talep</div>
        </div>
        <div className="kpi">
          <div className="value">{counts.APPROVE ?? 0}</div>
          <div className="label">Onaylanan</div>
        </div>
        <div className="kpi">
          <div className="value">{counts.MANUAL_REVIEW ?? 0}</div>
          <div className="label">Manuel inceleme</div>
        </div>
        <div className="kpi">
          <div className="value">{counts.REJECT ?? 0}</div>
          <div className="label">Reddedilen</div>
        </div>
        <div className="kpi">
          <div className="value">{avgScore ? avgScore.toFixed(1) : "-"}</div>
          <div className="label">Ortalama skor</div>
        </div>
      </div>

      <div className="card">
        <h3>Son talepler</h3>
        <table>
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Host</th>
              <th>Karar</th>
            </tr>
          </thead>
          <tbody>
            {requests.slice(0, 5).map((r) => (
              <tr key={r.id}>
                <td>{r.ticket_id}</td>
                <td>{r.hostname}</td>
                <td>
                  {r.latest_decision && (
                    <span className={`badge badge-${r.latest_decision.decision}`}>{r.latest_decision.decision}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>En çok büyüyen 10 file system (son 7 gün)</h3>
        <p className="page-hint">Bir satıra tıklayınca o host'un o file system'inin trendine gidersiniz.</p>
        <table>
          <thead>
            <tr>
              <th>Host</th>
              <th>File system</th>
              <th>Büyüme (% puan)</th>
              <th>Büyüme (GB)</th>
              <th>Güncel doluluk</th>
            </tr>
          </thead>
          <tbody>
            {topGrowth.map((r) => (
              <tr key={`${r.hostname}-${r.mount_point}`} onClick={() => navigate(hostMetricsLink(r.hostname, r.mount_point))}>
                <td>{r.hostname}</td>
                <td>{r.mount_point}</td>
                <td>+{r.growth_pct_points.toFixed(1)}%</td>
                <td>+{r.growth_gb.toFixed(1)} GB</td>
                <td>
                  {r.current_used_pct.toFixed(1)}% ({r.current_used_gb.toFixed(1)} / {r.current_capacity_gb.toFixed(0)} GB)
                </td>
              </tr>
            ))}
            {topGrowth.length === 0 && (
              <tr>
                <td colSpan={5}>Veri yok.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Doluluk %90 üzerinde olan file system'ler</h3>
        <p className="page-hint">Bir satıra tıklayınca o host'un o file system'inin trendine gidersiniz.</p>
        <table>
          <thead>
            <tr>
              <th>Host</th>
              <th>File system</th>
              <th>Doluluk</th>
            </tr>
          </thead>
          <tbody>
            {highUsage.map((r) => (
              <tr key={`${r.hostname}-${r.mount_point}`} onClick={() => navigate(hostMetricsLink(r.hostname, r.mount_point))}>
                <td>{r.hostname}</td>
                <td>{r.mount_point}</td>
                <td>
                  <span className={r.used_pct >= 95 ? "badge badge-REJECT" : "badge badge-MANUAL_REVIEW"}>
                    {r.used_pct.toFixed(1)}%
                  </span>{" "}
                  ({r.used_gb.toFixed(1)} / {r.capacity_gb.toFixed(0)} GB)
                </td>
              </tr>
            ))}
            {highUsage.length === 0 && (
              <tr>
                <td colSpan={3}>Veri yok.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
