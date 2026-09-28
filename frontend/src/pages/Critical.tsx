import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, FilesystemUsageOut } from "../api/client";
import { mockFullDisks } from "../api/mockData";

function hostMetricsLink(hostname: string, mountPoint: string): string {
  return `/hosts?host=${encodeURIComponent(hostname)}&mount=${encodeURIComponent(mountPoint)}`;
}

// Dedicated view for filesystems that are completely full (%100) -- these
// need immediate attention, distinct from the general ">%90" list on the
// Dashboard which includes filesystems that are simply trending high.
export default function Critical() {
  const [fullDisks, setFullDisks] = useState<FilesystemUsageOut[]>([]);
  const [usingMock, setUsingMock] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .getHighUsage(100)
      .then((rows) => {
        setFullDisks(rows);
        setUsingMock(false);
      })
      .catch(() => {
        setFullDisks(mockFullDisks);
        setUsingMock(true);
      });
  }, []);

  return (
    <div>
      <h2>Kritik: %100 Dolu File System'ler</h2>
      <p className="page-hint">
        Doluluğu tam %100 olan file system'ler. Bir satıra tıklayınca o host'un o file system'inin trendine gidersiniz.
      </p>
      {usingMock && <p style={{ color: "#b45309" }}>Backend'e ulaşılamadı, örnek (mock) veri gösteriliyor.</p>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Host</th>
              <th>File system</th>
              <th>Kullanılan / Kapasite (GB)</th>
              <th>Son ölçüm</th>
            </tr>
          </thead>
          <tbody>
            {fullDisks.map((r) => (
              <tr key={`${r.hostname}-${r.mount_point}`} onClick={() => navigate(hostMetricsLink(r.hostname, r.mount_point))}>
                <td>{r.hostname}</td>
                <td>{r.mount_point}</td>
                <td>
                  <span className="badge badge-REJECT">%100</span> ({r.used_gb.toFixed(1)} / {r.capacity_gb.toFixed(0)} GB)
                </td>
                <td>{new Date(r.collected_at).toLocaleString("tr-TR")}</td>
              </tr>
            ))}
            {fullDisks.length === 0 && (
              <tr>
                <td colSpan={4}>Şu anda %100 dolu file system yok.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
