import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, Decision, RequestOut } from "../api/client";
import { mockRequests } from "../api/mockData";

const OVERRIDE_OPTIONS: Decision[] = ["APPROVE", "APPROVE_REDUCED", "MANUAL_REVIEW", "REJECT"];

export default function RequestDetail() {
  const { id } = useParams<{ id: string }>();
  const [request, setRequest] = useState<RequestOut | null>(null);
  const [overrideDecision, setOverrideDecision] = useState<Decision>("APPROVE");
  const [reason, setReason] = useState("");
  const [user, setUser] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api
      .getRequest(Number(id))
      .then(setRequest)
      .catch(() => setRequest(mockRequests.find((r) => r.id === Number(id)) ?? mockRequests[0]));
  }, [id]);

  if (!request) return <p>Yükleniyor...</p>;

  const decision = request.latest_decision;

  async function submitOverride() {
    if (!request || !reason || !user) {
      setMessage("Lütfen gerekçe ve kullanıcı alanlarını doldurun.");
      return;
    }
    try {
      await api.overrideDecision(request.id, { new_decision: overrideDecision, reason, user });
      setMessage("Override kaydedildi.");
    } catch {
      setMessage("Override kaydedilemedi (backend'e ulaşılamıyor olabilir).");
    }
  }

  return (
    <div>
      <h2>Talep #{request.id} — {request.ticket_id}</h2>
      <div className="card">
        <p><strong>Host:</strong> {request.hostname}</p>
        <p><strong>Mount point:</strong> {request.mount_point}</p>
        <p><strong>İstenen boyut:</strong> {request.requested_gb} GB</p>
        <p><strong>Talep eden:</strong> {request.requester ?? "-"}</p>
        <p><strong>Oluşturulma:</strong> {new Date(request.created_at).toLocaleString("tr-TR")}</p>
      </div>

      <div className="card">
        <h3>Karar</h3>
        {decision ? (
          <>
            <p>
              <span className={`badge badge-${decision.decision}`}>{decision.decision}</span>{" "}
              {decision.score != null && <span>Skor: {decision.score}</span>}
            </p>
            {decision.recommended_gb != null && <p>Önerilen boyut: {decision.recommended_gb} GB</p>}
            <h4>Gerekçe</h4>
            <pre style={{ whiteSpace: "pre-wrap", background: "#f8fafc", padding: 12, borderRadius: 6 }}>
              {JSON.stringify(decision.reasoning, null, 2)}
            </pre>
          </>
        ) : (
          <p>Bu talep için henüz karar üretilmedi.</p>
        )}
      </div>

      <div className="card">
        <h3>Manuel override</h3>
        <div className="filters">
          <select value={overrideDecision} onChange={(e) => setOverrideDecision(e.target.value as Decision)}>
            {OVERRIDE_OPTIONS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <input placeholder="Kullanıcı" value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <textarea
          placeholder="Gerekçe"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          style={{ width: "100%", marginBottom: 12, padding: 8, borderRadius: 6, border: "1px solid #cbd5e1" }}
        />
        <button className="btn btn-primary" onClick={submitOverride}>Override kaydet</button>
        {message && <p>{message}</p>}
      </div>
    </div>
  );
}
