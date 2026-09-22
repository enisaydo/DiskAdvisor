import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, RequestOut, Decision } from "../api/client";
import { mockRequests } from "../api/mockData";

const DECISIONS: (Decision | "ALL")[] = ["ALL", "APPROVE", "APPROVE_REDUCED", "MANUAL_REVIEW", "REJECT"];

export default function Requests() {
  const [requests, setRequests] = useState<RequestOut[]>([]);
  const [filter, setFilter] = useState<(typeof DECISIONS)[number]>("ALL");
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api.listRequests().then(setRequests).catch(() => setRequests(mockRequests));
  }, []);

  const filtered = useMemo(() => {
    return requests.filter((r) => {
      const matchesFilter = filter === "ALL" || r.latest_decision?.decision === filter;
      const matchesSearch =
        !search ||
        r.hostname.toLowerCase().includes(search.toLowerCase()) ||
        r.ticket_id.toLowerCase().includes(search.toLowerCase());
      return matchesFilter && matchesSearch;
    });
  }, [requests, filter, search]);

  return (
    <div>
      <h2>Talepler</h2>
      <div className="filters">
        <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
          {DECISIONS.map((d) => (
            <option key={d} value={d}>
              {d === "ALL" ? "Tüm kararlar" : d}
            </option>
          ))}
        </select>
        <input
          placeholder="Host veya ticket ara..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Host</th>
              <th>Mount</th>
              <th>İstenen (GB)</th>
              <th>Karar</th>
              <th>Skor</th>
              <th>Öneri (GB)</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id} onClick={() => navigate(`/requests/${r.id}`)}>
                <td>{r.ticket_id}</td>
                <td>{r.hostname}</td>
                <td>{r.mount_point}</td>
                <td>{r.requested_gb}</td>
                <td>
                  {r.latest_decision ? (
                    <span className={`badge badge-${r.latest_decision.decision}`}>{r.latest_decision.decision}</span>
                  ) : (
                    "-"
                  )}
                </td>
                <td>{r.latest_decision?.score ?? "-"}</td>
                <td>{r.latest_decision?.recommended_gb ?? "-"}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7}>Kayıt bulunamadı.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
