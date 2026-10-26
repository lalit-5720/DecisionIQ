import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import { ErrorBox, PageSkeleton } from "../components/ui.jsx";
import { ArcElement, CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineElement, PointElement, Tooltip } from "chart.js";
import { Doughnut, Line } from "react-chartjs-2";

ChartJS.register(ArcElement, CategoryScale, LinearScale, LineElement, PointElement, Filler, Tooltip, Legend);

const fmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr = (v) => (Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toFixed(2)} Cr` : Math.abs(v) >= 1e5 ? `₹${(v / 1e5).toFixed(1)}L` : `₹${fmt.format(v)}`);
const sg = (v, d = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`);
const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const select = "h-8 rounded-lg border border-line bg-field px-2 text-xs text-ink focus:border-accent focus:outline-none";
const SEV = { High: "text-risk border-risk/30 bg-risk/10", Medium: "text-warn border-warn/30 bg-warn/10", Low: "text-muted border-line bg-field" };
const TYPE = { duplicate_billing: "Duplicate billing", demand_drop: "Demand drop", margin_erosion: "Margin erosion", cost_spike: "Logistics cost spike", unclassified: "Unusual pattern" };
const KIND = { reorder: "Inventory reorder", transfer: "Inter-store transfer", markdown: "Dynamic markdown", budget: "Budget reallocation" };
const RANGES = { "7D": [30, 7], "30D": [120, 30], "90D": [365, 90] };

export default function Dashboard() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [d, setD] = useState(null);
  const [opts, setOpts] = useState(null);
  const [scope, setScope] = useState({ store: "", category: "" });
  const [range, setRange] = useState("30D");
  const [series, setSeries] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => fetch("/api/dashboard/summary").then((r) => r.json()).then(setD).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); fetch("/api/forecast/options").then((r) => r.json()).then(setOpts); }, [load]);

  useEffect(() => {
    if (!d?.ready) return;
    const [h, hz] = RANGES[range];
    const q = new URLSearchParams({ history_days: h, horizon: hz, ...(scope.store && { store: scope.store }), ...(scope.category && { category: scope.category }) });
    fetch(`/api/forecast/series?${q}`).then((r) => (r.ok ? r.json() : null)).then(setSeries);
  }, [d?.ready, scope, range]);

  const act = async (id, status) => {
    await fetch(`/api/recommendations/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
    load();
  };

  const chart = useMemo(() => {
    if (!series) return null;
    const nh = series.history.length, pad = (a) => [...Array(nh).fill(null), ...a];
    return {
      labels: [...series.history.map((x) => x.date), ...series.forecast.map((x) => x.date)],
      datasets: [
        { label: "upper", data: pad(series.forecast.map((x) => x.upper)), borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(139,124,246,0.18)", fill: "+1" },
        { label: "lower", data: pad(series.forecast.map((x) => x.lower)), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Historical sales", data: [...series.history.map((x) => x.actual), ...Array(series.forecast.length).fill(null)], borderColor: "#00A1DA", borderWidth: 2, pointRadius: 0, tension: 0.25 },
        { label: "AI projected forecast", data: pad(series.forecast.map((x) => x.yhat)), borderColor: "#8B7CF6", borderDash: [6, 4], borderWidth: 2, pointRadius: 0, tension: 0.25 },
      ],
    };
  }, [series]);

  if (error) return <ErrorBox title="Backend unreachable" message={error} onRetry={() => { setError(null); load(); }} />;
  if (!d) return <PageSkeleton rows={2} />;
  if (!d.ready) return (
    <div className={card}>
      <h1 className="text-2xl font-semibold">Welcome to DecisionIQ</h1>
      <p className="mt-2 text-sm text-muted">No processed data or trained models yet. Run the pipeline on <Link className="text-accent" to="/data-sources">Data Sources</Link>, then train models on <Link className="text-accent" to="/forecasting">Forecasting</Link>.</p>
    </div>
  );

  const k = d.kpis, inv = d.inventory;
  const hour = new Date().getHours();
  const maxReg = Math.max(...d.regions.map((r) => Math.max(r.actual, r.forecast)), 1);
  const axis = { ticks: { color: "#B7C0D8", maxTicksLimit: 8 }, grid: { color: "#1E294B" } };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight">Good {hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"}, Priya</h1>
          <p className="text-sm text-muted">Decision intelligence summary as of {d.as_of} across {d.regions.reduce((a, r) => a + r.stores, 0)} stores.</p>
        </div>
        <div className="flex gap-2">
          <Link to="/settings" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:bg-card">Configure Rules</Link>
          <Link to="/data-sources" className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-canvas hover:bg-accent-hover">+ Upload new data</Link>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className={card}><div className={label}>Units sold · last 30 days</div><div className="mt-2 text-3xl font-bold">{fmt.format(k.units_30d)}</div>
          <div className={`mt-1 text-xs ${k.growth_pct >= 0 ? "text-ok" : "text-warn"}`}>{sg(k.growth_pct)} vs previous 30 days (seasonal)</div></div>
        <div className={card}><div className={label}>Forecast · next 30 days</div><div className="mt-2 text-3xl font-bold">{fmt.format(k.forecast_30d)}</div>
          <div className="mt-1 text-xs text-muted">{sg(k.forecast_growth_pct)} vs last 30 days · {d.model.serving} MAPE {d.model.mape?.toFixed(1)}%</div></div>
        <Link to="/recommendations" className={card}><div className={label}>Series at stock-out risk</div><div className="mt-2 text-3xl font-bold">{d.stockout_risk.series} <span className="text-base font-normal text-muted">SKU-stores</span></div>
          <div className="mt-1 text-xs text-risk">under 5 days of cover · {d.stockout_risk.reorders} reorders pending</div></Link>
        <Link to="/risk" className={card}><div className={label}>Open risk alerts</div><div className="mt-2 text-3xl font-bold">{fmt.format(d.open_alerts)}</div>
          <div className="mt-1 text-xs text-risk">{inr(d.high_exposure)} estimated exposure in High alerts</div></Link>
      </div>

      <div className={card}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Actual vs forecast · daily units</h2>
            <span className="mt-1 inline-block rounded-full border border-accent/30 bg-accent/10 px-3 py-0.5 text-[11px] font-semibold text-accent">Auto-selected: {d.model.serving} · MAPE {d.model.mape?.toFixed(1)}%</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select className={select} value={scope.category} onChange={(e) => setScope({ ...scope, category: e.target.value })}><option value="">All categories</option>{(opts?.categories || []).map((c) => <option key={c}>{c}</option>)}</select>
            <select className={select} value={scope.store} onChange={(e) => setScope({ ...scope, store: e.target.value })}><option value="">All stores</option>{(opts?.stores || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <div className="flex gap-0.5 rounded-lg border border-line p-0.5 text-xs">{Object.keys(RANGES).map((r) => <button key={r} onClick={() => setRange(r)} className={`rounded-md px-2.5 py-1 ${range === r ? "bg-accent text-canvas" : "text-muted"}`}>{r}</button>)}</div>
          </div>
        </div>
        <div className="mt-4 h-[300px]">
          {chart && <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, animation: false,
            plugins: { legend: { labels: { color: "#B7C0D8", filter: (i) => i.text !== "upper" && i.text !== "lower" } } }, scales: { x: axis, y: { ...axis, beginAtZero: true } } }} />}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className={card}>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">⚠ Needs your attention</h2><span className="rounded-full bg-risk px-2 py-0.5 text-[11px] font-bold text-canvas">{d.attention.length} of {fmt.format(d.open_alerts)}</span></div>
          <div className="mt-3 space-y-3">
            {d.attention.map((a) => (
              <div key={a.id} className="rounded-lg border border-line bg-field p-3">
                <div className="flex items-center justify-between"><span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${SEV[a.severity]}`}>{a.severity.toUpperCase()} · {TYPE[a.type] || a.type}</span><b>{inr(a.amount)}</b></div>
                <p className="mt-2 text-sm">{a.explanation}</p>
                <div className="mt-2 flex items-center justify-between text-xs text-muted"><span>{a.store}{a.item ? ` · ${a.item}` : ""} · {a.alert_id}</span>
                  <button onClick={() => nav(`/risk?alert=${a.id}`)} className="rounded-lg border border-line px-3 py-1 text-xs font-semibold text-ink hover:bg-card">Investigate</button></div>
              </div>
            ))}
            {d.attention.length === 0 && <p className="text-sm text-muted">No open alerts.</p>}
          </div>
        </div>

        <div className={card}>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">💡 Top recommendations</h2><Link to="/recommendations" className="text-xs font-semibold text-accent">View all {d.pending_recs} pending ›</Link></div>
          <div className="mt-3 space-y-3">
            {d.recommendations.map((r) => (
              <div key={r.id} className="rounded-lg border border-line bg-field p-3">
                <div className="flex items-center justify-between text-xs"><span className="rounded-full border border-accent/30 bg-accent/10 px-2.5 py-0.5 font-semibold text-accent">{KIND[r.kind]} · {Math.round(r.confidence * 100)}% confidence</span><b className="text-ok">{inr(r.impact_inr)} {r.impact_label}</b></div>
                <p className="mt-2 text-sm font-semibold">{r.title}</p>
                <div className="mt-2 flex justify-end gap-2"><button onClick={() => act(r.id, "Dismissed")} disabled={!can("approve_actions")} className="px-3 py-1 text-xs text-muted disabled:opacity-40">Dismiss</button>
                  <button onClick={() => act(r.id, "Approved")} disabled={!can("approve_actions")} title={can("approve_actions") ? undefined : "Your role is not permitted to do this"} className="rounded-lg bg-accent px-3 py-1 text-xs font-semibold text-canvas hover:bg-accent-hover disabled:opacity-40">Approve</button></div>
              </div>
            ))}
            {d.recommendations.length === 0 && <p className="text-sm text-muted">Nothing pending. Generate recommendations on the Recommendations page.</p>}
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <div className={card}>
          <h2 className="text-lg font-semibold">Demand by region</h2>
          <p className="text-xs text-muted">Last 30 days actual vs next 30 days forecast, units by city</p>
          <div className="mt-4 space-y-3">
            {d.regions.map((r) => (
              <div key={r.city}>
                <div className="flex justify-between text-xs"><span className="font-semibold">{r.city} <span className="font-normal text-muted">({r.stores} stores)</span></span><span className="text-muted">{fmt.format(r.actual)} → {fmt.format(r.forecast)} · {r.share_pct}% of volume</span></div>
                <div className="mt-1 h-2 rounded-full bg-field"><div className="h-full rounded-full bg-accent" style={{ width: `${(r.actual / maxReg) * 100}%` }} /></div>
                <div className="mt-1 h-2 rounded-full bg-field"><div className="h-full rounded-full bg-violet" style={{ width: `${(r.forecast / maxReg) * 100}%` }} /></div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-4 text-xs text-muted"><span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />Actual</span><span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-violet" />Forecast</span></div>
        </div>

        <div className={card}>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Inventory health</h2>{inv && <span className="rounded-full bg-field px-2 py-0.5 text-[11px] text-muted">Total {fmt.format(inv.total_skus)} SKU-stores</span>}</div>
          {inv ? (
            <div className="mt-3 flex flex-wrap items-center gap-4">
              <div className="relative h-[150px] w-[150px]">
                <Doughnut data={{ labels: Object.keys(inv.buckets), datasets: [{ data: Object.values(inv.buckets), backgroundColor: ["#F87171", "#34D399", "#C7BFFF"], borderWidth: 0 }] }}
                  options={{ cutout: "72%", plugins: { legend: { display: false } } }} />
                <div className="absolute inset-0 grid place-items-center text-center"><div><div className="text-lg font-bold">{inr(inv.stock_value)}</div><div className="text-[10px] text-muted">STOCK VALUE</div></div></div>
              </div>
              <div className="space-y-2 text-sm">
                {Object.entries(inv.buckets).map(([k2, v], i) => (
                  <div key={k2} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: ["#F87171", "#34D399", "#C7BFFF"][i] }} />{k2}<b className="ml-auto pl-3">{v}</b></div>
                ))}
              </div>
            </div>
          ) : <p className="mt-3 text-sm text-muted">Needs trained forecasts.</p>}
          <Link to="/recommendations" className="mt-3 inline-block text-xs font-semibold text-accent">Manage replenishment ›</Link>
        </div>
      </div>
    </div>
  );
}
