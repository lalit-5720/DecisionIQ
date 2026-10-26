import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DownloadLink } from "../auth.jsx";
import { Skeleton } from "../components/ui.jsx";
import {
  BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, LineElement, PointElement, Tooltip,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip, Legend);

const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const select = "h-9 rounded-lg border border-line bg-field px-2 text-sm text-ink focus:border-accent focus:outline-none";
const sgn = (v, d = 1) => `${v > 0 ? "+" : ""}${v.toFixed(d)}`;
const FEATURE_CHOICES = ["dow", "rolling_mean_14", "lag_7", "month", "lag_30", "festival_flag"];

export default function Explainability() {
  const [opts, setOpts] = useState(null);
  const [meta, setMeta] = useState(null);
  const [f, setF] = useState({ store: 1, item: 1, date: "" });
  const [local, setLocal] = useState(null);
  const [mode, setMode] = useState("pct");
  const [glob, setGlob] = useState(null);
  const [gov, setGov] = useState(null);
  const [dep, setDep] = useState(null);
  const [feature, setFeature] = useState("dow");
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([fetch("/api/forecast/options").then((r) => r.json()), fetch("/api/explain/options")])
      .then(async ([o, e]) => {
        if (!e.ok) throw new Error((await e.json()).detail);
        const ex = await e.json();
        setOpts(o); setMeta(ex);
        const d = new Date(ex.forecast[0]); d.setDate(d.getDate() + 19);
        setF((x) => ({ ...x, date: d.toISOString().slice(0, 10) }));
      })
      .catch((e) => setError(e.message));
    fetch("/api/explain/global").then((r) => (r.ok ? r.json() : null)).then(setGlob);
    fetch("/api/explain/governance").then((r) => (r.ok ? r.json() : null)).then(setGov);
  }, []);

  useEffect(() => {
    if (!f.date) return;
    setError(null);
    fetch(`/api/explain/local?store=${f.store}&item=${f.item}&date=${f.date}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error((await r.json()).detail))))
      .then(setLocal).catch((e) => { setLocal(null); setError(e.message); });
  }, [f]);

  useEffect(() => {
    if (!meta) return;
    fetch(`/api/explain/dependence?feature=${feature}&store=${f.store}&item=${f.item}`).then((r) => (r.ok ? r.json() : null)).then(setDep);
  }, [feature, f.store, f.item, meta]);

  const wf = useMemo(() => local && {
    labels: local.waterfall.map((s) => s.label),
    datasets: [{
      data: local.waterfall.map((s) => [Math.min(s.start, s.end), Math.max(s.start, s.end)]),
      backgroundColor: local.waterfall.map((s) => ({ base: "#4B5878", final: "#8B7CF6", up: "#00A1DA", down: "#F87171" }[s.kind])),
    }],
  }, [local]);
  const maxAbs = local ? Math.max(...local.contributions.map((c) => Math.abs(mode === "pct" ? c.share_pct : c.shap)), 1) : 1;
  const axis = { ticks: { color: "#B7C0D8" }, grid: { color: "#1E294B" } };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Interpretability & feature-contribution engine</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Model Explainability & Feature Attribution</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">Exact TreeSHAP values for the serving XGBoost model: base value + feature contributions = the forecast.</p>
        </div>
        {glob?.model && (
          <div className="rounded-xl border border-line bg-card px-4 py-2 text-sm">
            <div className="font-semibold text-ok">● XGBoost · {glob.model.version}</div>
            <div className="text-xs text-muted">Global R² {glob.model.r2?.toFixed(2)} · MAPE {glob.model.mape?.toFixed(1)}% · {glob.sample_rows.toLocaleString()} rows explained</div>
          </div>
        )}
      </div>

      {error && <div className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm text-warn">{error}</div>}

      {meta && (
        <div className={`${card} grid gap-3 sm:grid-cols-3`}>
          <label className="text-xs text-muted">Store
            <select className={`${select} mt-1 w-full`} value={f.store} onChange={(e) => setF({ ...f, store: +e.target.value })}>
              {(opts?.stores || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></label>
          <label className="text-xs text-muted">Product
            <select className={`${select} mt-1 w-full`} value={f.item} onChange={(e) => setF({ ...f, item: +e.target.value })}>
              {(opts?.items || []).map((i) => <option key={i.id} value={i.id}>{i.sku} · {i.name}</option>)}
            </select></label>
          <label className="text-xs text-muted">Date (history {meta.history[0]} → forecast {meta.forecast[1]})
            <input type="date" className={`${select} mt-1 w-full`} value={f.date} min={meta.history[0]} max={meta.forecast[1]} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
        </div>
      )}

      {!local && !error && <div className="space-y-4"><Skeleton className="h-40" /><div className="grid gap-4 xl:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div></div>}
      {local && (
        <>
          <div className={`${card} bg-gradient-to-br from-card to-[#1a1f3a]`}>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded-full border border-accent/30 bg-accent/10 px-3 py-1 font-semibold text-accent">Plain-language translation · TreeSHAP derived</span>
              <span className="text-muted">{local.in_history ? `Historical day · actual ${local.actual} units` : "Forecast day"}</span>
            </div>
            <p className="mt-3 text-xl font-semibold leading-snug">{local.summary}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {local.groups.map((g) => (
                <div key={g.group} className="rounded-lg border border-line bg-field p-3">
                  <div className={`${label} ${g.shap >= 0 ? "text-accent" : "text-risk"}`}>{g.group}</div>
                  <div className={`mt-1 text-lg font-bold ${g.shap >= 0 ? "text-ok" : "text-risk"}`}>{sgn(g.shap)} units</div>
                  <div className="text-xs text-muted">{g.features.join(", ")}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className={card}>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Local feature importance (SHAP)</h2>
                <div className="flex gap-1 rounded-lg border border-line p-0.5 text-xs">
                  {[["pct", "Contribution %"], ["raw", "Raw SHAP"]].map(([k, t]) => (
                    <button key={k} onClick={() => setMode(k)} className={`rounded-md px-2.5 py-1 ${mode === k ? "bg-accent text-canvas" : "text-muted"}`}>{t}</button>
                  ))}
                </div>
              </div>
              <p className="mt-1 text-sm text-muted">Baseline expected value <b className="text-ink">{local.base_value} units/day</b> → prediction <b className="text-ink">{local.prediction}</b> ({sgn(local.prediction - local.base_value)} units).</p>
              <div className="mt-4 space-y-2">
                {local.contributions.map((c) => {
                  const v = mode === "pct" ? c.share_pct : c.shap;
                  return (
                    <div key={c.feature} className="grid grid-cols-[130px_1fr_70px] items-center gap-3 text-xs">
                      <span className="truncate font-mono text-muted" title={`value ${c.value}`}>{c.feature} = {Math.round(c.value * 100) / 100}</span>
                      <div className="relative h-5 rounded bg-field">
                        <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                        <div className={`absolute inset-y-0 rounded ${v >= 0 ? "bg-accent" : "bg-risk/80"}`}
                          style={{ width: `${(Math.abs(v) / maxAbs) * 50}%`, [v >= 0 ? "left" : "right"]: "50%" }} />
                      </div>
                      <span className={`text-right font-semibold ${v >= 0 ? "text-accent" : "text-risk"}`}>{mode === "pct" ? `${sgn(v)}%` : sgn(v, 2)}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className={card}>
              <h2 className="text-lg font-semibold">Stepwise prediction bridge</h2>
              <p className="mt-1 text-sm text-muted">Base E[f(x)] → f(x). Balance check: |base + Σφ − f(x)| = {local.balance_check.toExponential(1)} (exact).</p>
              <div className="mt-3 h-[300px]">
                <Bar data={wf} options={{
                  responsive: true, maintainAspectRatio: false,
                  plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => { const s = local.waterfall[c.dataIndex]; return s.kind === "base" || s.kind === "final" ? `${s.value.toFixed(1)} units` : `${sgn(s.value)} units`; } } } },
                  scales: { x: { ...axis, grid: { display: false } }, y: axis },
                }} />
              </div>
              <DownloadLink className="mt-3 inline-block rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:bg-field" url={`/api/explain/export.csv?store=${f.store}&item=${f.item}&date=${f.date}`} name="shap_explanation.csv">Export SHAP values (CSV)</DownloadLink>
              <Link to="/what-if" className="ml-2 inline-block rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-canvas">Simulate in What-If</Link>
            </div>
          </div>
        </>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <div className={card}>
          <h2 className="text-lg font-semibold">Global feature impact</h2>
          <p className="text-xs text-muted">Mean |SHAP| across a sample of store-days — what the model relies on overall.</p>
          <div className="mt-3 space-y-2">
            {(glob?.features || []).slice(0, 8).map((d) => (
              <div key={d.feature}>
                <div className="flex justify-between text-xs"><span className="font-mono">{d.feature}</span><span className="text-accent">{d.share_pct}%</span></div>
                <div className="h-1.5 rounded-full bg-field"><div className="h-full rounded-full bg-accent" style={{ width: `${d.share_pct}%` }} /></div>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            {(glob?.groups || []).map((g) => <span key={g.group} className="rounded-full border border-line bg-field px-3 py-1">{g.group}: <b>{g.share_pct}%</b></span>)}
          </div>
        </div>

        <div className={card}>
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Feature dependence (PDP + ICE)</h2>
            <select className={select} value={feature} onChange={(e) => setFeature(e.target.value)}>
              {FEATURE_CHOICES.map((x) => <option key={x}>{x}</option>)}
            </select>
          </div>
          <p className="text-xs text-muted">Predicted units as one feature varies, for the selected store and product (last 365 days). Price is not a model input, so no price-elasticity curve is shown.</p>
          {dep && (
            <div className="mt-3 h-[240px]">
              <Line data={{
                labels: dep.grid,
                datasets: [
                  ...dep.ice.map((row) => ({ data: row, borderColor: "rgba(183,192,216,0.25)", borderWidth: 1, pointRadius: 0, tension: 0.3 })),
                  { label: "Average (PDP)", data: dep.pdp, borderColor: "#00A1DA", borderWidth: 3, pointRadius: 3, tension: 0.3 },
                ],
              }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: axis, y: axis } }} />
            </div>
          )}
        </div>
      </div>

      {gov && (
        <div className={card}>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Model governance, fairness & audit trail</h2>
            <span className="rounded-full border border-ok/30 bg-ok/10 px-3 py-1 text-xs font-semibold text-ok">Drift: {gov.drift_status}</span>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <div className="space-y-3">
              <div className="rounded-lg border border-line bg-field p-3"><div className={label}>Error parity across stores</div><div className="text-2xl font-bold">{gov.parity_index}%</div><div className="text-xs text-muted">1 − spread of store WAPE (backtest)</div></div>
              <div className="rounded-lg border border-line bg-field p-3"><div className={label}>Last retrained</div><div className="font-semibold">{gov.trained_at.replace("T", " ")}</div><div className="text-xs text-muted">{gov.model_version}</div></div>
              <div className="rounded-lg border border-line bg-field p-3"><div className={label}>Model artifact hash</div><div className="break-all font-mono text-xs">sha256:{gov.artifact_sha256.slice(0, 24)}…</div></div>
            </div>
            <div>
              <div className={label}>Population drift (PSI, last 90 days vs earlier)</div>
              <table className="mt-2 w-full text-left text-sm"><tbody>
                {gov.drift.map((d) => (
                  <tr key={d.feature} className="border-b border-line/60"><td className="py-1.5 font-mono text-xs">{d.feature}</td>
                    <td className={`text-right font-semibold ${d.psi < 0.1 ? "text-ok" : d.psi < 0.25 ? "text-warn" : "text-risk"}`}>{d.psi.toFixed(3)}</td></tr>
                ))}</tbody></table>
              <p className="mt-2 text-xs text-muted">{gov.note} &lt;0.1 stable, 0.1–0.25 moderate, &gt;0.25 significant.</p>
            </div>
            <div>
              <div className={label}>Backtest error by store</div>
              <table className="mt-2 w-full text-left text-sm"><tbody>
                {gov.stores.map((s) => (
                  <tr key={s.store} className="border-b border-line/60"><td className="py-1.5">{s.name}</td><td className="text-right">{s.wape}% WAPE</td><td className={`text-right text-xs ${Math.abs(s.bias) > 3 ? "text-warn" : "text-muted"}`}>{sgn(s.bias)}% bias</td></tr>
                ))}</tbody></table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
