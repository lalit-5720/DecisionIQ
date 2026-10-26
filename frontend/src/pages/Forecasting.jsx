import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CategoryScale, Chart as ChartJS, Filler, Legend, LineElement, LinearScale, PointElement, Tooltip,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { DownloadLink, useAuth } from "../auth.jsx";
import { EmptyState, ErrorBox, Skeleton } from "../components/ui.jsx";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend);

const fmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const select = "h-9 rounded-lg border border-line bg-field px-2 text-sm text-ink focus:border-accent focus:outline-none";

const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v != null)).toString();

export default function Forecasting() {
  const { can } = useAuth();
  const [opts, setOpts] = useState(null);
  const [f, setF] = useState(() => {
    const q = new URLSearchParams(window.location.search);
    return { store: q.get("store") || "", category: "", item: q.get("item") || "", horizon: 30 };
  });
  const [data, setData] = useState(null);
  const [loadingSeries, setLoadingSeries] = useState(false);
  const [sched, setSched] = useState(null);
  const [page, setPage] = useState(1);
  const [models, setModels] = useState(null);
  const [train, setTrain] = useState(null);
  const [error, setError] = useState(null);
  const [fatal, setFatal] = useState(null);

  const filters = { store: f.store, category: f.category, item: f.item };
  const loadModels = useCallback(async () => setModels(await fetch("/api/forecast/models").then((r) => r.json())), []);

  const boot = useCallback(() => {
    setFatal(null);
    fetch("/api/forecast/options").then((r) => r.json()).then(setOpts).catch((e) => setFatal(e.message));
    loadModels().catch((e) => setFatal(e.message));
    fetch("/api/forecast/train-status").then((r) => r.json()).then(setTrain).catch(() => {});
  }, [loadModels]);
  useEffect(() => { boot(); }, [boot]);

  useEffect(() => {
    if (!models?.available) return;
    setError(null);
    setLoadingSeries(true);
    fetch(`/api/forecast/series?${qs({ ...filters, horizon: f.horizon })}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error((await r.json()).detail))))
      .then(setData)
      .catch((e) => { setData(null); setError(e.message); })
      .finally(() => setLoadingSeries(false));
    setPage(1);
  }, [f, models?.available]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!models?.available) return;
    fetch(`/api/forecast/schedule?${qs({ ...filters, horizon: f.horizon, page })}`)
      .then((r) => (r.ok ? r.json() : null)).then(setSched);
  }, [f, page, models?.available]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!train?.running) return;
    const t = setInterval(async () => {
      const s = await fetch("/api/forecast/train-status").then((r) => r.json());
      setTrain(s);
      if (!s.running) loadModels();
    }, 3000);
    return () => clearInterval(t);
  }, [train?.running, loadModels]);

  const retrain = async () => {
    const r = await fetch("/api/forecast/retrain", { method: "POST" });
    if (!r.ok) return setError((await r.json()).detail);
    setTrain((t) => ({ ...t, running: true, status: "running" }));
  };

  const chart = useMemo(() => {
    if (!data) return null;
    const labels = [...data.history.map((d) => d.date), ...data.forecast.map((d) => d.date)];
    const nh = data.history.length;
    const pad = (arr, offset) => [...Array(offset).fill(null), ...arr];
    const bt = Object.fromEntries(data.backtest.map((b) => [b.date, b.pred]));
    return {
      labels,
      datasets: [
        { label: "95% upper", data: pad(data.forecast.map((d) => d.upper), nh), borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(139,124,246,0.18)", fill: "+1" },
        { label: "95% lower", data: pad(data.forecast.map((d) => d.lower), nh), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Historical sales", data: [...data.history.map((d) => d.actual), ...Array(data.forecast.length).fill(null)], borderColor: "#00A1DA", borderWidth: 2, pointRadius: 0, tension: 0.2 },
        { label: "Backtest (holdout)", data: labels.map((l, i) => (i < nh ? bt[l] ?? null : null)), borderColor: "#B7C0D8", borderDash: [3, 3], borderWidth: 1, pointRadius: 0, tension: 0.2 },
        { label: "Forecast", data: pad(data.forecast.map((d) => d.yhat), nh), borderColor: "#8B7CF6", borderDash: [6, 4], borderWidth: 2, pointRadius: 0, tension: 0.2 },
      ],
    };
  }, [data]);

  const best = models?.models?.find((m) => m.name === models.selected);
  const s = data?.summary;
  const pages = sched ? Math.ceil(sched.total / sched.page_size) : 1;
  const items = (opts?.items || []).filter((i) => !f.category || i.category === f.category);

  if (fatal) return <ErrorBox title="Could not load the forecasting page" message={fatal} onRetry={boot} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Engine telemetry</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Predictive Demand Forecasting</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Global XGBoost, Prophet, SARIMA and LSTM models benchmarked on a 90-day holdout; the best scalable model serves the forecast.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Link to="/forecasting/states" className="text-xs font-semibold text-accent hover:underline">Engine states →</Link>
          {train?.running && <span className="text-accent">Training… {train.progress}%</span>}
          {train?.status === "failed" && <span className="text-risk">Last run failed</span>}
          <button onClick={retrain} disabled={train?.running || !can("run_analysis")} title={can("run_analysis") ? undefined : "Your role is not permitted to do this"}
            className="h-9 rounded-lg border border-line px-4 font-semibold hover:bg-card disabled:opacity-50">
            Retrain Models
          </button>
        </div>
      </div>

      {train?.running && (
        <div className={card}>
          <div className="h-2 overflow-hidden rounded-full bg-field"><div className="h-full bg-accent transition-all" style={{ width: `${train.progress}%` }} /></div>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
            {train.steps.map((st) => (
              <div key={st.key} className={st.status === "done" ? "text-ok" : st.status === "active" ? "text-accent" : "text-muted"}>
                {st.label}{st.detail ? ` · ${st.detail}` : ""}
              </div>
            ))}
          </div>
        </div>
      )}

      {models && !models.available && !train?.running && (
        <EmptyState icon="📈" title="No trained models yet" hint="Run the data pipeline, then train the models. Training benchmarks four models and takes a couple of minutes.">
          <Link to="/data-sources" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:bg-field">Go to Data Sources</Link>
          <button onClick={retrain} disabled={!can("run_analysis")} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-40">Train models</button>
        </EmptyState>
      )}

      <div className={`${card} grid gap-3 sm:grid-cols-2 xl:grid-cols-4`}>
        <label className="text-xs text-muted">Store
          <select className={`${select} mt-1 w-full`} value={f.store} onChange={(e) => setF({ ...f, store: e.target.value })}>
            <option value="">All stores</option>
            {(opts?.stores || []).map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">Category
          <select className={`${select} mt-1 w-full`} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value, item: "" })}>
            <option value="">All categories</option>
            {(opts?.categories || []).map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">Product
          <select className={`${select} mt-1 w-full`} value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })}>
            <option value="">All products</option>
            {items.map((i) => <option key={i.id} value={i.id}>{i.sku} · {i.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">Forecast horizon
          <select className={`${select} mt-1 w-full`} value={f.horizon} onChange={(e) => setF({ ...f, horizon: +e.target.value })}>
            {(opts?.horizons || [30]).map((h) => <option key={h} value={h}>Next {h} days</option>)}
          </select>
        </label>
      </div>

      {error && <ErrorBox message={error} title="No forecast for this selection" />}
      {loadingSeries && !data && <Skeleton className="h-[420px]" />}

      {data && (
        <div className={`${card} ${loadingSeries ? "opacity-70" : ""}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">{f.horizon}-Day Predictive Trajectory</h2>
              <span className="mt-1 inline-block rounded-full border border-ok/30 bg-ok/10 px-3 py-0.5 text-[11px] font-semibold text-ok">
                Active model: {s.model} {best ? `· MAPE ${best.mape.toFixed(1)}% on holdout` : ""}
              </span>
            </div>
            <div className="flex flex-wrap gap-3 text-sm">
              <div className="rounded-lg border border-line bg-field px-3 py-2"><div className={label}>Forecast peak</div><b>{fmt.format(s.peak_units)} units/day</b></div>
              <div className="rounded-lg border border-line bg-field px-3 py-2"><div className={label}>Run-rate WoW</div><b className={s.run_rate_wow_pct >= 0 ? "text-ok" : "text-risk"}>{s.run_rate_wow_pct > 0 ? "+" : ""}{s.run_rate_wow_pct}%</b></div>
              <div className="rounded-lg border border-line bg-field px-3 py-2"><div className={label}>Total units</div><b>{fmt.format(s.total_units)}</b></div>
            </div>
          </div>
          <div className="mt-4 h-[340px]">
            <Line data={chart} options={{
              responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
              plugins: { legend: { labels: { color: "#B7C0D8", filter: (i) => !i.text.startsWith("95% l") && !i.text.startsWith("95% u") } } },
              scales: {
                x: { ticks: { color: "#B7C0D8", maxTicksLimit: 8 }, grid: { color: "#1E294B" } },
                y: { ticks: { color: "#B7C0D8" }, grid: { color: "#1E294B" }, beginAtZero: true },
              },
            }} />
          </div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <div className={card}>
          <h2 className="text-lg font-semibold">Model Benchmark & Backtest</h2>
          {models?.available && (
            <p className="text-xs text-muted">
              Holdout {models.backtest_window[0]} → {models.backtest_window[1]} · {models.eval_series.length}-series sample (Prophet/SARIMA are per-series)
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="mt-3 w-full min-w-[420px] text-left text-sm">
              <thead className={`${label} border-b border-line`}>
                <tr><th className="py-2">Model</th><th>MAE</th><th>RMSE</th><th>MAPE</th><th>R²</th><th>Train</th><th>Status</th></tr>
              </thead>
              <tbody>
                {(models?.models || []).map((m) => (
                  <tr key={m.name} className="border-b border-line/60">
                    <td className="py-2 font-semibold">{m.name}</td>
                    <td>{m.mae.toFixed(1)}</td><td>{m.rmse.toFixed(1)}</td>
                    <td className={m.status === "Selected" ? "font-semibold text-ok" : ""}>{m.mape.toFixed(1)}%</td>
                    <td>{m.r2.toFixed(2)}</td><td className="text-muted">{m.train_s}s</td>
                    <td className="text-xs">{m.status === "Selected" ? <span className="text-ok">Selected</span> : <span className="text-muted">{m.status}</span>}</td>
                  </tr>
                ))}
                {!models && <tr><td colSpan={7} className="py-4"><Skeleton className="h-20" /></td></tr>}
              </tbody>
            </table>
          </div>
          {models?.available && (() => {
            const full = models.models.find((m) => m.name === models.serving)?.full_set;
            return full && (
              <p className="mt-3 text-xs text-muted">
                {models.serving} on all {models.n_series} series: MAPE {full.mape.toFixed(1)}% (daily, per series) · {full.mape_agg.toFixed(1)}% (daily chain total) · WAPE {full.wape.toFixed(1)}%.
              </p>
            );
          })()}
          <h3 className="mt-5 text-sm font-semibold">Key predictive drivers (XGBoost gain)</h3>
          <div className="mt-2 space-y-2">
            {(models?.importance || []).slice(0, 5).map((d) => (
              <div key={d.feature}>
                <div className="flex justify-between text-xs"><span className="font-mono">{d.feature}</span><span className="text-accent">{d.weight}%</span></div>
                <div className="h-1.5 rounded-full bg-field"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(d.weight, 100)}%` }} /></div>
              </div>
            ))}
          </div>
        </div>

        <div className={card}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Next {f.horizon}-Day Forecast Schedule</h2>
            {models?.available && (
              <DownloadLink className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:bg-field"
                url={`/api/forecast/export.csv?${qs({ ...filters, horizon: f.horizon })}`} name="forecast.csv">Export CSV</DownloadLink>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="mt-3 w-full min-w-[420px] text-left text-sm">
              <thead className={`${label} border-b border-line`}>
                <tr><th className="py-2">Date</th><th>Day</th><th>Forecast</th><th>Lower</th><th>Upper</th><th>Driver</th></tr>
              </thead>
              <tbody>
                {(sched?.rows || []).map((r) => (
                  <tr key={r.date} className="border-b border-line/60">
                    <td className="py-2">{r.date}</td><td className="text-muted">{r.day}</td>
                    <td className="font-semibold text-accent">{fmt.format(r.forecast)}</td>
                    <td className="text-muted">{fmt.format(r.lower)}</td><td className="text-muted">{fmt.format(r.upper)}</td>
                    <td className="text-xs">{r.driver}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sched && (
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>Page {page} of {pages} · {sched.total} days</span>
              <div className="flex gap-2">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Previous</button>
                <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Next</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
