import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineElement, PointElement, Tooltip } from "chart.js";
import { Line } from "react-chartjs-2";
import { Skeleton } from "../components/ui.jsx";

ChartJS.register(CategoryScale, LinearScale, LineElement, PointElement, Filler, Tooltip, Legend);

const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const select = "h-9 w-full rounded-lg border border-line bg-field px-2 text-sm text-ink focus:border-accent focus:outline-none";
const fmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr = (v) => (Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toFixed(2)} Cr` : Math.abs(v) >= 1e5 ? `₹${(v / 1e5).toFixed(1)}L` : `₹${fmt.format(v)}`);
const pct = (a, b) => (b ? ((a / b - 1) * 100) : 0);
const sg = (v, d = 1, suf = "") => `${v > 0 ? "+" : ""}${v.toFixed(d)}${suf}`;
const DEFAULT = { price_pct: 0, voucher_pct: 0, marketing: "Low", safety_stock_units: null, lead_time_days: 3, festival_shock: false, competitor_match: false };
const RATING_TONE = { "Highly favorable": "text-ok border-ok/30 bg-ok/10", Favorable: "text-ok border-ok/30 bg-ok/10", Neutral: "text-muted border-line bg-field", Unfavorable: "text-risk border-risk/30 bg-risk/10" };

function Slider({ title, value, min, max, step = 1, onChange, fmtV, hint }) {
  return (
    <div className="rounded-lg border border-line bg-field p-3">
      <div className="flex items-center justify-between text-sm"><span className="font-semibold">{title}</span><span className="rounded bg-card px-2 py-0.5 font-mono text-xs text-accent">{fmtV(value)}</span></div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} className="mt-2 w-full accent-[#00A1DA]" />
      <div className="flex justify-between text-[10px] text-muted"><span>{hint[0]}</span><span>{hint[1]}</span><span>{hint[2]}</span></div>
    </div>
  );
}

export default function WhatIf() {
  const [opts, setOpts] = useState(null);
  const [scope, setScope] = useState({ store: "", category: "", item: 1 });
  const [lv, setLv] = useState(DEFAULT);
  const [info, setInfo] = useState(null);
  const [res, setRes] = useState(null);
  const [view, setView] = useState("daily");
  const [busy, setBusy] = useState(false);
  const [mc, setMc] = useState(false);
  const [saved, setSaved] = useState([]);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState(null);
  const seq = useRef(0);

  const body = useCallback((runs) => ({
    scope: { store: scope.store || null, category: scope.category || null, item: scope.item || null },
    horizon: 30, levers: lv, runs,
  }), [scope, lv]);

  const loadSaved = () => fetch("/api/simulate/scenarios").then((r) => r.json()).then((j) => setSaved(j.scenarios));
  useEffect(() => { fetch("/api/forecast/options").then((r) => r.json()).then(setOpts); loadSaved(); }, []);

  useEffect(() => {
    const q = new URLSearchParams(Object.entries(scope).filter(([, v]) => v));
    fetch(`/api/simulate/baseline?${q}`).then(async (r) => (r.ok ? r.json() : Promise.reject(new Error((await r.json()).detail)))).then(setInfo).catch((e) => setMsg({ error: e.message }));
  }, [scope]);

  const run = useCallback(async (runs) => {
    const my = ++seq.current;
    setBusy(true);
    const r = await fetch("/api/simulate/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body(runs)) });
    const j = await r.json();
    if (my !== seq.current) return;
    setBusy(false);
    if (!r.ok) return setMsg({ error: typeof j.detail === "string" ? j.detail : "Invalid levers" });
    setMsg(null); setRes(j);
  }, [body]);

  useEffect(() => { setMc(false); const t = setTimeout(() => run(250), 350); return () => clearTimeout(t); }, [run]);

  const set = (k) => (v) => setLv((x) => ({ ...x, [k]: v }));
  const ssValue = lv.safety_stock_units ?? info?.baseline_safety_stock ?? 0;
  const items = (opts?.items || []).filter((i) => !scope.category || i.category === scope.category);

  const chart = useMemo(() => {
    if (!res) return null;
    const t = res.trajectory, L = t.dates;
    const base = { borderColor: "#00A1DA", borderWidth: 2, pointRadius: 0, tension: 0.3, label: "Baseline" };
    const scn = { borderColor: "#C7BFFF", borderWidth: 2, pointRadius: 0, tension: 0.3, label: "Simulated scenario" };
    if (view === "cumulative") return { labels: L, datasets: [{ ...base, data: t.baseline_cum_revenue }, { ...scn, data: t.scenario_cum_revenue }] };
    if (view === "stockout") return { labels: L, datasets: [{ ...base, data: t.baseline_stockout }, { ...scn, data: t.scenario_stockout }] };
    return {
      labels: L,
      datasets: [
        { label: "p90", data: t.band_hi, borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(139,124,246,0.15)", fill: "+1" },
        { label: "p10", data: t.band_lo, borderWidth: 0, pointRadius: 0, fill: false },
        { ...base, data: t.baseline_units }, { ...scn, data: t.scenario_units },
      ],
    };
  }, [res, view]);

  const save = async () => {
    const r = await fetch("/api/simulate/scenarios", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body(500), name }) });
    const j = await r.json();
    if (!r.ok) return setMsg({ error: typeof j.detail === "string" ? j.detail : "Enter a scenario name" });
    setName(""); setMsg({ ok: `Saved “${j.name}”` }); loadSaved();
  };
  const load = (s) => { setScope({ store: s.scope_ids.store || "", category: s.scope_ids.category || "", item: s.scope_ids.item || "" }); setLv({ ...DEFAULT, ...s.levers }); };
  const del = async (id) => { await fetch(`/api/simulate/scenarios/${id}`, { method: "DELETE" }); loadSaved(); };
  const reset = () => setLv(DEFAULT);

  const b = res?.baseline, s = res?.scenario;
  const axis = { ticks: { color: "#B7C0D8", maxTicksLimit: 8 }, grid: { color: "#1E294B" } };
  const cmp = [["Revenue", "revenue", inr], ["Units", "units", fmt.format], ["Gross margin", "gross_margin_pct", (v) => v.toFixed(1) + "%"], ["Net profit", "net_profit", inr], ["Stock-out risk", "stockout_risk_pct", (v) => v.toFixed(1) + "%"]];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight">Scenario & Sensitivity Simulator <span className="ml-2 rounded-full bg-violet/20 px-2 py-0.5 align-middle text-[11px] font-semibold text-violet">STOCHASTIC ENGINE</span></h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">Move the levers: the 30-day forecast is re-simulated with price response, marketing, shocks and an inventory policy. Baseline and scenario share the same random draws.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={reset} className="h-9 rounded-lg border border-line px-4 text-sm font-semibold hover:bg-card">Reset to baseline</button>
        </div>
      </div>

      {msg?.error && <div className="rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{msg.error}</div>}
      {msg?.ok && <div className="rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{msg.ok}</div>}

      <div className={`${card} grid gap-3 md:grid-cols-4`}>
        <label className="text-xs text-muted">Category<select className={`${select} mt-1`} value={scope.category} onChange={(e) => setScope({ ...scope, category: e.target.value, item: "" })}>
          <option value="">All categories</option>{(opts?.categories || []).map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="text-xs text-muted">Target product<select className={`${select} mt-1`} value={scope.item} onChange={(e) => setScope({ ...scope, item: e.target.value ? +e.target.value : "" })}>
          <option value="">All products</option>{items.map((i) => <option key={i.id} value={i.id}>{i.sku} · {i.name}</option>)}</select></label>
        <label className="text-xs text-muted">Network scope<select className={`${select} mt-1`} value={scope.store} onChange={(e) => setScope({ ...scope, store: e.target.value ? +e.target.value : "" })}>
          <option value="">All 10 stores</option>{(opts?.stores || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <div className="text-xs text-muted">Reference baseline<div className="mt-1 rounded-lg border border-line bg-field px-3 py-2 text-sm text-ink">{info?.reference || "…"}</div></div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_1fr_340px]">
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Simulation levers</h2>
          <Slider title="Retail price" value={lv.price_pct} min={-20} max={20} onChange={set("price_pct")} fmtV={(v) => sg(v, 0, "%")} hint={["−20% markdown", "0% current", "+20% premium"]} />
          <Slider title="Festive markdown voucher" value={lv.voucher_pct} min={0} max={30} onChange={set("voucher_pct")} fmtV={(v) => `${v}% off`} hint={["0 none", "15 moderate", "30 clearance"]} />
          <div className="rounded-lg border border-line bg-field p-3">
            <div className="text-sm font-semibold">Marketing push intensity</div>
            <div className="mt-2 grid grid-cols-3 gap-1">
              {[["Low", "+0%"], ["Medium", "+15%"], ["High", "+35%"]].map(([k, t]) => (
                <button key={k} onClick={() => set("marketing")(k)} className={`rounded-md py-1.5 text-xs ${lv.marketing === k ? "bg-accent font-semibold text-canvas" : "bg-card text-muted"}`}>{k}<div className="text-[10px] opacity-80">{t} budget</div></button>
              ))}
            </div>
          </div>
          <Slider title="Safety stock target" value={Math.round(ssValue)} min={0} max={info?.safety_stock_max || 100} step={Math.max(1, Math.round((info?.safety_stock_max || 100) / 100))}
            onChange={(v) => set("safety_stock_units")(v)} fmtV={(v) => `${fmt.format(v)} units`} hint={["0", `${fmt.format(info?.baseline_safety_stock || 0)} baseline`, `${fmt.format(info?.safety_stock_max || 0)} max`]} />
          <Slider title="Supplier replenish SLA" value={lv.lead_time_days} min={1} max={21} onChange={set("lead_time_days")} fmtV={(v) => `${v} days`} hint={["1d air", "3d baseline", "21d port"]} />
          <div>
            <div className={label}>Exogenous shocks</div>
            {[["festival_shock", "Festival demand spike", "+45% for 7 days from day 10"], ["competitor_match", "Competitor price match", "−5% demand reaction"]].map(([k, t, h]) => (
              <label key={k} className="mt-2 flex cursor-pointer items-center justify-between rounded-lg border border-line bg-field p-3">
                <span><span className="text-sm font-semibold">{t}</span><span className="block text-xs text-muted">{h}</span></span>
                <input type="checkbox" checked={lv[k]} onChange={(e) => set(k)(e.target.checked)} className="h-4 w-4 accent-[#00A1DA]" />
              </label>
            ))}
          </div>
          <button onClick={() => { setMc(true); run(1000); }} className="h-10 w-full rounded-lg border border-line bg-field text-sm font-semibold hover:border-accent">
            {busy ? "Simulating…" : "Run Monte Carlo simulation"}<span className="block text-[10px] font-normal text-muted">{mc ? "1,000 runs" : "live preview uses 250 runs"}</span>
          </button>
        </div>

        <div className="space-y-4">
          <div className={card}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><h2 className="text-lg font-semibold">Forecast trajectory: baseline vs simulated</h2><p className="text-xs text-muted">{res?.scope} · {res?.n_series} series · {res?.runs} runs {busy && "· updating…"}</p></div>
              <div className="flex gap-1 rounded-lg border border-line p-0.5 text-xs">
                {[["daily", "Daily units"], ["cumulative", "Cumulative ₹"], ["stockout", "Stock-out %"]].map(([k, t]) => (
                  <button key={k} onClick={() => setView(k)} className={`rounded-md px-2.5 py-1 ${view === k ? "bg-accent text-canvas" : "text-muted"}`}>{t}</button>
                ))}
              </div>
            </div>
            <div className="mt-3 h-[320px]">
              {!chart && <Skeleton className="h-full" />}
              {chart && <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, animation: false,
                plugins: { legend: { labels: { color: "#B7C0D8", filter: (i) => i.text !== "p90" && i.text !== "p10" } } }, scales: { x: axis, y: { ...axis, beginAtZero: true } } }} />}
            </div>
            {view === "daily" && <p className="mt-1 text-xs text-muted">Shaded band = 10th–90th percentile of simulated demand.</p>}
          </div>
          {res && (
            <div className={card}>
              <h2 className="text-lg font-semibold">Store-level simulation footprint</h2>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                {res.stores.map((st) => (
                  <div key={st.store} className="rounded-lg border border-line bg-field p-3">
                    <div className="flex items-center justify-between"><span className="text-sm font-semibold">{st.name}</span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${st.status === "Safe" ? "bg-ok/15 text-ok" : st.status === "Watch" ? "bg-warn/15 text-warn" : "bg-risk/15 text-risk"}`}>{st.status}</span></div>
                    <div className="mt-1 text-xs text-muted">Simulated {fmt.format(st.units)} units · buffer {fmt.format(st.buffer_units)}</div>
                    <div className="mt-2 h-1.5 rounded-full bg-card"><div className={`h-full rounded-full ${st.status === "Safe" ? "bg-ok" : st.status === "Watch" ? "bg-warn" : "bg-risk"}`} style={{ width: `${Math.min(100, 100 - st.stockout_risk_pct * 5)}%` }} /></div>
                    <div className="mt-1 text-[10px] text-muted">daily stock-out probability {st.stockout_risk_pct}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          {s && (
            <>
              {[
                ["Projected revenue", inr(s.revenue), `${sg(pct(s.revenue, b.revenue), 1, "%")} vs baseline ${inr(b.revenue)}`, s.revenue >= b.revenue],
                ["Volume projected", `${fmt.format(s.units)} units`, `${sg(pct(s.units, b.units), 1, "%")} · p10–p90 ${fmt.format(s.units_p10)}–${fmt.format(s.units_p90)}`, s.units >= b.units],
                ["Gross margin rate", `${s.gross_margin_pct.toFixed(1)}%`, `${sg(s.gross_margin_pct - b.gross_margin_pct, 1, " pts")} · net profit ${inr(s.net_profit)} (${sg(res.delta.net_profit / 1e5, 1, "L")})`, s.net_profit >= b.net_profit],
                ["Stock-out risk (daily)", `${s.stockout_risk_pct.toFixed(1)}%`, `${sg(s.stockout_risk_pct - b.stockout_risk_pct, 1, " pts")} vs baseline ${b.stockout_risk_pct.toFixed(1)}%`, s.stockout_risk_pct <= b.stockout_risk_pct + 0.5],
              ].map(([k, v, sub, good]) => (
                <div key={k} className={card}><div className={label}>{k}</div><div className="mt-1 text-2xl font-bold">{v}</div><div className={`mt-1 text-xs ${good ? "text-ok" : "text-risk"}`}>{sub}</div></div>
              ))}
              <div className="grid grid-cols-3 gap-2">
                {[["Elasticity index", s.elasticity_index.toFixed(2)], ["Safety buffer", `${s.safety_buffer_days.toFixed(1)} d`], ["Monte Carlo P90 peak", `${fmt.format(s.peak_p90)} u`]].map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-line bg-card p-3"><div className="text-[10px] uppercase tracking-wider text-muted">{k}</div><div className="mt-1 font-semibold">{v}</div></div>
                ))}
              </div>
              <div className={card}>
                <div className="flex items-center justify-between"><span className="font-semibold">DecisionIQ verdict</span>
                  <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${RATING_TONE[res.verdict.rating] || RATING_TONE.Neutral}`}>{res.verdict.rating}</span></div>
                <p className="mt-2 text-sm text-muted">{res.verdict.text}</p>
              </div>
            </>
          )}
        </div>
      </div>

      <div className={card}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-semibold">Saved scenarios <span className="ml-1 rounded-full bg-field px-2 py-0.5 text-xs text-muted">{saved.length}</span></h2>
          <div className="flex gap-2">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Scenario name" className="h-9 w-56 rounded-lg border border-line bg-field px-3 text-sm focus:border-accent focus:outline-none" />
            <button onClick={save} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover">Save scenario</button>
          </div>
        </div>
        {saved.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className={`${label} border-b border-line`}>
                <tr><th className="py-2">Metric</th><th>Baseline</th>{saved.slice(0, 4).map((x) => <th key={x.id}>
                  <div className="font-semibold normal-case tracking-normal text-ink">{x.name}</div>
                  <div className="text-[10px] font-normal normal-case tracking-normal text-muted">{x.scope}</div>
                  <button onClick={() => load(x)} className="mr-2 text-[11px] normal-case tracking-normal text-accent">Load</button>
                  <button onClick={() => del(x.id)} className="text-[11px] normal-case tracking-normal text-risk">Delete</button></th>)}</tr>
              </thead>
              <tbody>
                {cmp.map(([t, k, f]) => (
                  <tr key={k} className="border-b border-line/60"><td className="py-2 text-muted">{t}</td>
                    <td>{saved[0] ? f(saved[0].baseline[k]) : "–"} <span className="text-[10px] text-muted">(first scenario's scope)</span></td>
                    {saved.slice(0, 4).map((x) => <td key={x.id} className="font-semibold">{f(x.scenario[k])}</td>)}</tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted">Baselines differ if scenarios use different scopes; compare scenarios saved for the same product and stores.</p>
          </div>
        )}
      </div>
    </div>
  );
}
