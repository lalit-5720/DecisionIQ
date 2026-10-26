import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineElement, PointElement, Tooltip } from "chart.js";
import { Line } from "react-chartjs-2";
import { useAuth } from "../auth.jsx";
import { EmptyState, ErrorBox, Skeleton } from "../components/ui.jsx";

ChartJS.register(CategoryScale, LinearScale, LineElement, PointElement, Filler, Tooltip, Legend);

const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const TABS = [["all", "All 4 states"], ["empty", "Empty"], ["training", "Training"], ["failure", "Failure"], ["low", "Low confidence"]];

const EX_LOG = `[2018-01-14 09:42:18 IST] [CRITICAL] Schema mismatch detected in batch file: pos_feed_jan14.csv
[SCHEMA_CHECK] Missing required structural attributes:
  - store: (Type: INT NOT NULL)
  - sales: (Type: INT NOT NULL)
  - date: (Type: ISO8601 TIMESTAMP)
[POLICY] Automatic fall-through rejected. Model training halted to prevent poisoned downstream forecasts.`;
const EX_STEPS = [
  { label: "Data ingestion & sanitisation", status: "done", detail: "1,248,390 rows normalised" },
  { label: "Feature lag transformation", status: "done", detail: "lag_7, lag_30, rolling_mean_14" },
  { label: "Hyperparameter tuning & CV", status: "active", detail: "XGBoost fold 4 of 5 (eta=0.035, max_depth=6)" },
  { label: "SHAP attribution", status: "pending", detail: "global + local explanations" },
];

function Shell({ tag, tone, title, example, onExample, children }) {
  const tones = { ok: "border-ok/30 bg-ok/10 text-ok", info: "border-accent/30 bg-accent/10 text-accent", risk: "border-risk/40 bg-risk/10 text-risk", warn: "border-warn/40 bg-warn/10 text-warn", violet: "border-violet/40 bg-violet/10 text-violet" };
  return (
    <section className={card} aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-wide ${tones[tone]}`}>{tag}</span>
        <div className="flex items-center gap-2">
          {example && <span className="rounded bg-field px-2 py-0.5 text-[10px] font-semibold text-muted">EXAMPLE</span>}
          <button onClick={onExample} className="text-[11px] text-muted underline decoration-dotted hover:text-ink">{example ? "Show live state" : "Preview example"}</button>
        </div>
      </div>
      {children}
    </section>
  );
}

function StepList({ steps }) {
  return (
    <ul className="mt-3 space-y-2">
      {steps.map((s, i) => (
        <li key={i} className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${s.status === "active" ? "border-accent/40 bg-accent/5" : "border-line bg-field"}`}>
          <span className={`mt-0.5 ${s.status === "done" ? "text-ok" : s.status === "active" ? "animate-pulse text-accent" : s.status === "failed" ? "text-risk" : "text-muted"}`}>
            {s.status === "done" ? "✓" : s.status === "active" ? "◐" : s.status === "failed" ? "✕" : "…"}</span>
          <div className="min-w-0"><div className="font-semibold">{i + 1}. {s.label}</div>{s.detail && <div className="truncate text-xs text-muted">{s.detail}</div>}</div>
        </li>
      ))}
    </ul>
  );
}

export default function ForecastStates() {
  const { can } = useAuth();
  const [tab, setTab] = useState("all");
  const [ex, setEx] = useState({ empty: false, training: false, failure: false, low: false });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [pick, setPick] = useState(null);
  const [usePrior, setUsePrior] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async (series) => {
    try {
      const q = series ? `?store=${series.store}&item=${series.item}` : "";
      const [pipe, diag, train, models, low] = await Promise.all([
        fetch("/api/pipeline/status").then((r) => r.json()), fetch("/api/pipeline/diagnostics").then((r) => r.json()),
        fetch("/api/forecast/train-status").then((r) => r.json()), fetch("/api/forecast/models").then((r) => r.json()),
        fetch(`/api/forecast/low-confidence${q}`).then((r) => (r.ok ? r.json() : null)),
      ]);
      setData({ pipe, diag, train, models, low });
      setError(null);
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { load(pick); }, [load, pick]);
  useEffect(() => {
    if (!data?.train?.running && !data?.pipe?.running) return;
    const t = setInterval(() => load(pick), 2500);
    return () => clearInterval(t);
  }, [data?.train?.running, data?.pipe?.running, load, pick]);

  const flip = (k) => setEx((e) => ({ ...e, [k]: !e[k] }));
  const act = async (url, ok) => {
    setMsg(null);
    const r = await fetch(url, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    setMsg(r.ok ? { ok } : { error: typeof j.detail === "string" ? j.detail : "Request failed" });
    setTimeout(() => load(pick), 800);
  };
  const downloadLog = (text) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.download = "pipeline_diagnostic.log";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const low = data?.low;
  const chart = useMemo(() => {
    const e = ex.low ? null : low?.example;
    if (!e) return null;
    return {
      labels: e.dates,
      datasets: [
        { label: "upper", data: e.upper, borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(139,124,246,0.2)", fill: "+1" },
        { label: "lower", data: e.lower, borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Model forecast", data: e.yhat, borderColor: "#8B7CF6", borderWidth: 2, pointRadius: 0, tension: 0.25 },
        ...(usePrior ? [{ label: "Category-average prior", data: e.prior, borderColor: "#FBBF24", borderDash: [6, 4], borderWidth: 2, pointRadius: 0 }] : []),
      ],
    };
  }, [low, ex.low, usePrior]);

  if (error) return <ErrorBox message={error} onRetry={() => load(pick)} title="Could not load engine states" />;
  if (!data) return <div className="space-y-4"><Skeleton className="h-12 w-96" /><div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div></div>;

  const { pipe, diag, train, models } = data;
  const nSeries = models.n_series;
  const isEmpty = !models.available && pipe.status !== "complete";
  const failed = diag.failed || train.status === "failed";
  const show = (k) => tab === "all" || tab === k;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>System telemetry matrix · <Link to="/forecasting" className="text-accent">← back to forecasting</Link></div>
          <h1 className="text-[28px] font-semibold tracking-tight">Forecasting Engine States & Fault Vectors</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">What the engine looks like while empty, training, failing or unsure. Each card shows the live condition; “Preview example” shows the variant when it is not currently active.</p>
        </div>
        <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-card p-1" role="tablist">
          {TABS.map(([k, t]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`rounded-lg px-3 py-1.5 text-xs ${tab === k ? "bg-field font-semibold text-ink" : "text-muted hover:text-ink"}`}>{t}</button>)}
        </div>
      </div>
      {msg?.error && <ErrorBox message={msg.error} />}
      {msg?.ok && <div className="rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{msg.ok}</div>}

      <div className={`grid gap-4 ${tab === "all" ? "lg:grid-cols-2" : ""}`}>
        {show("empty") && (
          <Shell tag={ex.empty || isEmpty ? "State 01 // Idle — no data" : "State 01 // Ready"} tone={ex.empty || isEmpty ? "info" : "ok"} title="Empty state" example={ex.empty} onExample={() => flip("empty")}>
            {ex.empty || isEmpty ? (
              <div className="mt-4"><EmptyState icon="☁" title="No data yet — upload to begin" hint="No historical sales transactions were found. Upload at least 90 days of daily sales for the stores you want to forecast.">
                <div className="grid w-full max-w-sm grid-cols-3 gap-2 text-center text-xs"><div className="rounded-lg bg-field p-2"><div className={label}>Min history</div><b>90 days</b></div><div className="rounded-lg bg-field p-2"><div className={label}>Granularity</div><b>Daily</b></div><div className="rounded-lg bg-field p-2"><div className={label}>Formats</div><b>CSV·XLSX</b></div></div>
                <Link to="/data-sources" className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-canvas">+ Upload historical data</Link>
              </EmptyState></div>
            ) : (
              <div className="mt-4 space-y-3">
                <h3 className="text-lg font-semibold">Data and models are in place</h3>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg bg-field p-3"><div className={label}>Series</div><b className="text-lg">{nSeries ?? "–"}</b></div>
                  <div className="rounded-lg bg-field p-3"><div className={label}>Rows</div><b className="text-lg">{pipe.features?.rows?.toLocaleString() ?? "–"}</b></div>
                  <div className="rounded-lg bg-field p-3"><div className={label}>Range</div><b className="text-[11px]">{pipe.features?.date_min} → {pipe.features?.date_max}</b></div>
                </div>
                <Link to="/data-sources" className="inline-block rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:bg-field">Upload more data</Link>
              </div>
            )}
          </Shell>
        )}

        {show("training") && (
          <Shell tag={ex.training ? "State 02 // Executing — 72%" : train.running ? `State 02 // Executing — ${train.progress}%` : "State 02 // Last training run"} tone={ex.training || train.running ? "violet" : "ok"} title="Training state" example={ex.training} onExample={() => flip("training")}>
            {(() => {
              const live = !ex.training;
              const steps = live ? train.steps.map((s) => ({ ...s })) : EX_STEPS;
              const pct = live ? train.progress || 0 : 72;
              return (
                <div className="mt-4">
                  <h3 className="text-lg font-semibold">{live ? (train.running ? "Training and benchmarking models" : train.status === "complete" ? "Training complete" : train.status === "failed" ? "Training failed" : "No training run yet") : "Active hyperparameter optimisation"}</h3>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-field" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div className="h-full bg-gradient-to-r from-accent to-violet transition-all" style={{ width: `${pct}%` }} /></div>
                  <StepList steps={steps} />
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                    <span>{live && train.duration_s ? `Last run ${train.duration_s}s · ${train.updated_at?.replace("T", " ")}` : live ? "" : "Estimated remaining: 1m 24s"}</span>
                    {live && !train.running && <button onClick={() => act("/api/forecast/retrain", "Retraining started")} disabled={!can("run_analysis")} title={can("run_analysis") ? undefined : "Your role is not permitted to do this"} className="rounded-lg border border-line px-3 py-1.5 font-semibold text-ink hover:bg-field disabled:opacity-40">Retrain models</button>}
                  </div>
                </div>
              );
            })()}
          </Shell>
        )}

        {show("failure") && (
          <Shell tag={ex.failure || failed ? "State 03 // Pipeline exception" : "State 03 // No faults"} tone={ex.failure || failed ? "risk" : "ok"} title="Failure state" example={ex.failure} onExample={() => flip("failure")}>
            {ex.failure || failed ? (() => {
              const log = ex.failure ? EX_LOG : diag.log;
              return (
                <div className="mt-4">
                  <div className="flex items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-risk text-lg text-canvas">!</span>
                    <div><h3 className="text-lg font-semibold text-risk">{ex.failure ? "Pipeline failed at cleaning — required columns missing" : diag.error || train.error || "Pipeline failed"}</h3>
                      <p className="text-sm text-muted">Execution aborted to protect historical models. Nothing was written to the forecast store.</p></div></div>
                  <pre className="mt-3 max-h-48 overflow-auto rounded-lg border border-line bg-[#080d1d] p-3 font-mono text-[11px] leading-5 text-muted">{log}</pre>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button disabled={ex.failure || !can("upload_data")} onClick={() => act("/api/pipeline/run", "Pipeline re-run started")} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-40">↻ Retry pipeline run</button>
                    <Link to="/data-sources" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:bg-field">Inspect source column mappings</Link>
                    <button onClick={() => downloadLog(log)} className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:bg-field">Download diagnostic log</button>
                  </div>
                </div>
              );
            })() : (
              <div className="mt-4 space-y-3">
                <h3 className="text-lg font-semibold">No active faults</h3>
                <p className="text-sm text-muted">Last pipeline run: <b className="text-ink">{pipe.status}</b>{pipe.latency_s ? ` in ${pipe.latency_s}s` : ""}{pipe.updated_at ? ` · ${pipe.updated_at.replace("T", " ")}` : ""}. A run that fails stops here with the full log, and nothing downstream is overwritten.</p>
                <pre className="max-h-36 overflow-auto rounded-lg border border-line bg-[#080d1d] p-3 font-mono text-[11px] leading-5 text-muted">{diag.log}</pre>
                <button onClick={() => downloadLog(diag.log)} className="rounded-lg border border-line px-4 py-2 text-sm font-semibold hover:bg-field">Download log</button>
              </div>
            )}
          </Shell>
        )}

        {show("low") && (
          <Shell tag={ex.low || low?.low_count > 0 ? `State 04 // Inference degradation${ex.low ? "" : ` — ${low.low_count} series`}` : "State 04 // Forecast confidence healthy"} tone={ex.low || low?.low_count > 0 ? "warn" : "ok"} title="Low confidence" example={ex.low} onExample={() => flip("low")}>
            {!low && !ex.low ? <div className="mt-4"><EmptyState icon="📉" title="No forecasts yet" hint="Train the models to see forecast confidence." /></div> : (
              <div className="mt-4 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><h3 className="text-lg font-semibold">{ex.low ? "Forecast uncertainty is high for this product" : low.low_count > 0 ? "Some forecasts are uncertain" : "All forecasts are within the confidence threshold"}</h3>
                    <p className="text-sm text-muted">{ex.low ? "Only 45 days of history exist for SKU-APP-0230 in the Hubballi cluster, so the interval is widened to ±28%." : `${low.low_count} of ${low.total_series} series are below ${low.threshold}% confidence (median ${low.median_confidence}%). Confidence = 100% − relative forecast band.`}</p></div>
                  <span className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-1 text-sm font-bold text-warn">{ex.low ? "61.2%" : `${low.example.confidence}%`}</span>
                </div>
                {ex.low ? (
                  <div className="rounded-lg border border-line bg-field p-4 text-sm text-muted">Mean forecast with 90% bound (±28.4%) over the Diwali run. Prescriptive reorder quantities adjust to a conservative safety stock until more history accumulates.</div>
                ) : (
                  <>
                    <div className="text-xs text-muted">Weakest series: <b className="text-ink">{low.example.label}</b></div>
                    <div className="h-[190px]">{chart && <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { color: "#B7C0D8", filter: (i) => i.text !== "upper" && i.text !== "lower" } } },
                      scales: { x: { ticks: { color: "#B7C0D8", maxTicksLimit: 6 }, grid: { color: "#1E294B" } }, y: { ticks: { color: "#B7C0D8" }, grid: { color: "#1E294B" }, beginAtZero: true } } }} />}</div>
                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => setUsePrior(!usePrior)} className={`rounded-lg border px-3 py-1.5 text-sm font-semibold ${usePrior ? "border-warn text-warn" : "border-line hover:bg-field"}`}>⇄ {usePrior ? "Hide" : "Compare with"} category-average prior</button>
                      <Link to="/settings" className="rounded-lg border border-line px-3 py-1.5 text-sm font-semibold hover:bg-field">Review recommendation rules</Link>
                    </div>
                    <div className="overflow-x-auto"><table className="w-full min-w-[360px] text-left text-xs">
                      <thead className={`${label} border-b border-line`}><tr><th className="py-1.5">Least confident series</th><th>Avg/day</th><th>Band ±</th><th>Confidence</th></tr></thead>
                      <tbody>{low.series.slice(0, 5).map((s) => (
                        <tr key={`${s.store}-${s.item}`} onClick={() => setPick({ store: s.store, item: s.item })} className="cursor-pointer border-b border-line/60 hover:bg-field">
                          <td className="py-1.5">{s.item_name}<div className="text-[10px] text-muted">{s.store_name}</div></td><td>{s.avg_daily}</td><td>{s.band_pct}%</td><td className="font-semibold text-warn">{s.confidence}%</td></tr>
                      ))}</tbody></table></div>
                  </>
                )}
              </div>
            )}
          </Shell>
        )}
      </div>

      <div className={`${card} text-sm text-muted`}>
        <b className="text-ink">Recovery policy in this build:</b> a failed pipeline or training run stops, keeps the previous forecasts and models untouched, and logs the cause (see the audit trail). Retries are manual — there is no automatic retry/back-off daemon yet.
      </div>
    </div>
  );
}
