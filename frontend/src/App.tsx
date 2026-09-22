import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Requests from "./pages/Requests";
import RequestDetail from "./pages/RequestDetail";
import HostMetrics from "./pages/HostMetrics";
import Analysis from "./pages/Analysis";

export default function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>DiskAdvisor</h1>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/requests">Talepler</NavLink>
          <NavLink to="/hosts">Host Metrikleri</NavLink>
          <NavLink to="/analysis">Analiz</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/requests/:id" element={<RequestDetail />} />
          <Route path="/hosts" element={<HostMetrics />} />
          <Route path="/analysis" element={<Analysis />} />
        </Routes>
      </main>
    </div>
  );
}
