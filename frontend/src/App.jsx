import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Placeholder from "./pages/Placeholder.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import DataSources from "./pages/DataSources.jsx";
import Forecasting from "./pages/Forecasting.jsx";
import Risk from "./pages/Risk.jsx";
import Recommendations from "./pages/Recommendations.jsx";
import Explainability from "./pages/Explainability.jsx";
import WhatIf from "./pages/WhatIf.jsx";
import Reports from "./pages/Reports.jsx";
import Settings from "./pages/Settings.jsx";
import Login from "./pages/Login.jsx";
import ForecastStates from "./pages/ForecastStates.jsx";
import { useAuth } from "./auth.jsx";
import { NAV_ITEMS } from "./nav.js";

function Protected() {
  const { user, ready } = useAuth();
  const loc = useLocation();
  if (!ready) return <div className="grid min-h-screen place-items-center text-sm text-muted">Loading…</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname + loc.search }} replace />;
  return <Layout />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route index element={<Dashboard />} />
        <Route path="/data-sources" element={<DataSources />} />
        <Route path="/forecasting" element={<Forecasting />} />
        <Route path="/forecasting/states" element={<ForecastStates />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/recommendations" element={<Recommendations />} />
        <Route path="/explainability" element={<Explainability />} />
        <Route path="/what-if" element={<WhatIf />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<Settings />} />
        {NAV_ITEMS.filter((n) => !["/", "/data-sources", "/forecasting", "/risk", "/recommendations", "/explainability", "/what-if", "/reports", "/settings"].includes(n.path)).map((n) => (
          <Route key={n.path} path={n.path} element={<Placeholder title={n.label} />} />
        ))}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
