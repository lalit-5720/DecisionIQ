import { useCallback, useEffect, useMemo, useState } from "react";
import { Chart as ChartJS, LinearScale, LogarithmicScale, PointElement, Tooltip, Legend, BarElement, CategoryScale } from "chart.js";
import { Bar, Scatter } from "react-chartjs-2";
import { useAuth } from "../auth.jsx";
import { ErrorBox } from "../components/ui.jsx";

ChartJS.register(LinearScale, LogarithmicScale, PointElement, Tooltip, Legend, BarElement, CategoryScale);

const inr = (v) => "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(v);
const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const SEV = { High: "text-risk border-risk/30 bg-risk/10", Medium: "text-warn border-warn/30 bg-warn/10", Low: "text-muted border-line bg-field" };
const SEV_COLOR = { High: "#F87171", Medium: "#FBBF24", Low: "#8B7CF6" };
const STATUS_TONE = { Open: "text-ink", "In Review": "text-accent", Resolved: "text-ok", "False Positive": "text-muted" };

const Pill = ({ sev }) => <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${SEV[sev]}`}>{sev.toUpperCase()}</span>;

export default function Risk() {
  const { can } = useAuth();
  const [summary, setSummary] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [filter, setFilter] = useState({ status: "unresolved", severity: "" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(() => { const a = new URLSearchParams(window.location.search).get("alert"); return a ? +a : null; });
  const [detail, setDetail] = useState(null);
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);

  const loadSummary = useCallback(async () => {
    setSummary(await fetch("/api/risk/summary").then((r) => r.json()));
    setTimeline(await fetch("/api/risk/timeline").then((r) => r.json()));
  }, []);
  const loadAlerts = useCallback(async () => {
    const q = new URLSearchParams({ page, page_size: 8, ...(filter.status && { status: filter.status }), ...(filter.severity && { severity: filter.severity }) });
    const j = await fetch(`/api/risk/alerts?${q}`).then((r) => r.json());
    setAlerts(j);
    setSelected((s) => s ?? j.alerts[0]?.id ?? null);
  }, [filter, page]);

  useEffect(() => { loadSummary().catch((e) => setError(e.message)); fetch("/api/risk/scan-status").then((r) => r.json()).then(setScan); }, [loadSummary]);
  useEffect(() => { loadAlerts().catch((e) => setError(e.message)); }, [loadAlerts]);
  useEffect(() => {
    if (selected == null) return setDetail(null);
    fetch(`/api/risk/alerts/${selected}`).then((r) => (r.ok ? r.json() : null)).then(setDetail);
  }, [selected]);
  useEffect(() => {
    if (!scan?.running) return;
    const t = setInterval(async () => {
      const s = await fetch("/api/risk/scan-status").then((r) => r.json());
      setScan(s);
      if (!s.running) { loadSummary(); loadAlerts(); }
    }, 1500);
    return () => clearInterval(t);
  }, [scan?.running, loadSummary, loadAlerts]);

  const startScan = async () => {
    const r = await fetch("/api/risk/scan", { method: "POST" });
    if (!r.ok) return setError((await r.json()).detail);
    setScan((s) => ({ ...s, running: true, status: "running" }));
  };
  const act = async (body) => {
    await fetch(`/api/risk/alerts/${selected}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    await Promise.all([loadAlerts(), loadSummary(), fetch(`/api/risk/alerts/${selected}`).then((r) => r.json()).then(setDetail)]);
  };

  const scatter = useMemo(() => ({
    datasets: ["High", "Medium", "Low"].map((sev) => ({
      label: sev, backgroundColor: SEV_COLOR[sev], pointRadius: sev === "High" ? 4 : 3,
      data: timeline.filter((t) => t.severity === sev && t.amount > 0).map((t) => ({ x: new Date(t.date).getTime(), y: t.amount, id: t.id })),
    })),
  }), [timeline]);

  const m = summary?.metrics;
  const ens = m?.detectors?.Ensemble;
  const pages = alerts ? Math.ceil(alerts.total / alerts.page_size) : 1;
  const ev = detail?.evidence;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Surveillance · telemetry stream</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Risk & Anomalies Intelligence</h1>
          <p className="mt-1 text-sm text-muted">Isolation Forest, autoencoder and Z-score rules vote; an alert needs at least two detectors.</p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {scan?.running && <span className="text-accent">Scanning…</span>}
          {scan?.status === "failed" && <span className="text-risk">Scan failed: {scan.error}</span>}
          <button onClick={startScan} disabled={scan?.running || !can("run_analysis")} title={can("run_analysis") ? undefined : "Your role is not permitted to do this"} className="h-9 rounded-lg bg-accent px-4 font-semibold text-canvas hover:bg-accent-hover disabled:opacity-50">
            {summary?.scanned ? "Re-scan" : "Run scan"}
          </button>
        </div>
      </div>

      {error && <ErrorBox message={error} onRetry={() => { setError(null); loadSummary(); loadAlerts(); }} />}
      {summary && !summary.scanned && <div className="rounded-lg border border-warn/40 bg-warn/10 p-4 text-sm text-warn">No scan yet — click <strong>Run scan</strong> (takes about 15 seconds).</div>}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ["Open risk alerts", summary?.open_alerts ?? "–", `${summary?.total_alerts ?? 0} total in ledger`],
          ["High severity", summary?.high_open ?? "–", summary ? `${inr(summary.high_exposure)} exposure` : ""],
          ["Ensemble precision", ens ? ens.precision.toFixed(2) : "–", ens ? `${ens.fp} false positives` : ""],
          ["Ensemble recall", ens ? ens.recall.toFixed(2) : "–", m ? `${(m.event_recall * 100).toFixed(0)}% of events caught` : ""],
          ["F1-score", ens ? ens.f1.toFixed(2) : "–", "vs injected labels"],
        ].map(([k, v, sub]) => (
          <div key={k} className={card}><div className={label}>{k}</div><div className="mt-2 text-3xl font-bold">{v}</div><div className="mt-1 text-xs text-muted">{sub}</div></div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-4">
          <div className={card}>
            <h2 className="text-lg font-semibold">Anomaly distribution & outlier timeline</h2>
            <p className="text-xs text-muted">Financial exposure per alert over time (log scale). Click a point to open its trace.</p>
            <div className="mt-3 h-[260px]">
              <Scatter data={scatter} options={{
                responsive: true, maintainAspectRatio: false,
                onClick: (_, els) => els[0] && setSelected(scatter.datasets[els[0].datasetIndex].data[els[0].index].id),
                plugins: { legend: { labels: { color: "#B7C0D8" } }, tooltip: { callbacks: { label: (c) => `${new Date(c.raw.x).toLocaleDateString()} · ${inr(c.raw.y)}` } } },
                scales: {
                  x: { type: "linear", ticks: { color: "#B7C0D8", callback: (v) => new Date(v).toLocaleDateString("en-GB", { month: "short", year: "2-digit" }), maxTicksLimit: 8 }, grid: { color: "#1E294B" } },
                  y: { type: "logarithmic", ticks: { color: "#B7C0D8", callback: (v) => inr(v) }, grid: { color: "#1E294B" } },
                },
              }} />
            </div>
          </div>

          <div className={card}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold">Telemetry alert ledger <span className="ml-2 rounded-full bg-field px-2 py-0.5 text-xs text-muted">{alerts?.total ?? 0}</span></h2>
              <div className="flex gap-2 text-xs">
                {[["Unresolved", { status: "unresolved", severity: "" }], ["High severity", { status: "unresolved", severity: "High" }], ["All", { status: "", severity: "" }]].map(([t, f]) => (
                  <button key={t} onClick={() => { setFilter(f); setPage(1); }}
                    className={`rounded-lg border px-3 py-1.5 ${filter.status === f.status && filter.severity === f.severity ? "border-accent text-accent" : "border-line text-muted"}`}>{t}</button>
                ))}
              </div>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className={`${label} border-b border-line`}><tr><th className="py-2">Alert</th><th>Type</th><th>Store</th><th className="text-right">Exposure</th><th>Score</th><th>Severity</th><th>Status</th></tr></thead>
                <tbody>
                  {(alerts?.alerts || []).map((a) => (
                    <tr key={a.id} onClick={() => setSelected(a.id)} className={`cursor-pointer border-b border-line/60 hover:bg-field ${selected === a.id ? "bg-field" : ""}`}>
                      <td className="py-2 font-mono text-xs text-accent">{a.alert_id}<div className="text-[10px] text-muted">{a.date}</div></td>
                      <td>{a.type_label}</td><td className="text-muted">{a.store_name}</td>
                      <td className="text-right">{inr(a.amount)}</td><td>{a.score.toFixed(2)}</td>
                      <td><Pill sev={a.severity} /></td><td className={`text-xs ${STATUS_TONE[a.status]}`}>{a.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>Page {page} of {pages}</span>
              <div className="flex gap-2">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Previous</button>
                <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Next</button>
              </div>
            </div>
          </div>
        </div>

        <div className={`${card} h-fit space-y-4`}>
          {!detail ? <p className="text-sm text-muted">Select an alert to see its forensic trace.</p> : (
            <>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className={label}>Detailed forensic trace</div>
                  <h2 className="text-xl font-semibold">{detail.type_label}</h2>
                  <div className="text-xs text-muted">{detail.alert_id} · {detail.date}{detail.end_date && detail.end_date !== detail.date ? ` → ${detail.end_date}` : ""}</div>
                </div>
                <Pill sev={detail.severity} />
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><div className={label}>Exposure</div><b>{inr(detail.amount)}</b></div>
                <div><div className={label}>Ensemble score</div><b>{detail.score.toFixed(2)} / 1.0</b></div>
                <div className="col-span-2"><div className={label}>Location</div><b>{detail.store_name}{detail.item_name ? ` · ${detail.item_name}` : ""}</b></div>
              </div>
              <div className="rounded-lg border border-line bg-field p-3">
                <div className="text-sm font-semibold">Why this was flagged</div>
                <p className="mt-1 text-sm text-muted">{detail.explanation}</p>
                {ev?.detectors && (
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {Object.entries(ev.detectors).map(([k, v]) => (
                      <span key={k} className={`rounded-full border px-2 py-0.5 ${v ? "border-ok/30 text-ok" : "border-line text-muted"}`}>{v ? "✓" : "–"} {k}</span>
                    ))}
                  </div>
                )}
              </div>
              {detail.distribution && (
                <div>
                  <div className={label}>Billed-units distribution for this series</div>
                  <div className="mt-2 h-[120px]">
                    <Bar data={{
                      labels: detail.distribution.edges.slice(0, -1).map((e) => Math.round(e)),
                      datasets: [{ data: detail.distribution.counts, backgroundColor: detail.distribution.edges.slice(0, -1).map((e, i) => (detail.distribution.value >= e && detail.distribution.value <= detail.distribution.edges[i + 1] ? "#F87171" : "#00A1DA")) }],
                    }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                      scales: { x: { ticks: { color: "#B7C0D8", maxTicksLimit: 7 }, grid: { display: false } }, y: { display: false } } }} />
                  </div>
                  <div className="text-xs text-muted">Median {Math.round(detail.distribution.median)} units · flagged value {Math.round(detail.distribution.value)} (red bar)</div>
                </div>
              )}
              {detail.window?.length > 0 && (
                <table className="w-full text-left text-xs">
                  <thead className={`${label} border-b border-line`}><tr><th className="py-1">Date</th><th>Billed</th><th>Expected</th><th>Price</th></tr></thead>
                  <tbody>{detail.window.map((r) => (
                    <tr key={r.date} className={`border-b border-line/60 ${r.flagged ? "bg-risk/10 text-risk" : ""}`}><td className="py-1">{r.date}</td><td>{r.units_billed}</td><td>{r.expected}</td><td>{inr(r.net_price)}</td></tr>
                  ))}</tbody>
                </table>
              )}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => act({ status: "In Review" })} disabled={!can("approve_actions")} className="h-9 flex-1 disabled:opacity-40 rounded-lg bg-accent px-3 text-sm font-semibold text-canvas hover:bg-accent-hover">Investigate</button>
                <button onClick={() => act({ status: "Resolved" })} disabled={!can("approve_actions")} className="h-9 flex-1 disabled:opacity-40 rounded-lg border border-ok/40 bg-ok/10 px-3 text-sm font-semibold text-ok">Resolve</button>
                <button onClick={() => act({ status: "False Positive" })} disabled={!can("approve_actions")} className="h-9 disabled:opacity-40 rounded-lg border border-line px-3 text-sm text-muted">False positive</button>
              </div>
              <div className="text-xs text-muted">Status: <span className={STATUS_TONE[detail.status]}>{detail.status}</span>{detail.assignee ? ` · assigned to ${detail.assignee}` : ""}</div>
            </>
          )}
        </div>
      </div>

      {m && (
        <div className={card}>
          <h2 className="text-lg font-semibold">Detector comparison (against injected labels)</h2>
          <table className="mt-3 w-full max-w-2xl text-left text-sm">
            <thead className={`${label} border-b border-line`}><tr><th className="py-2">Detector</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
            <tbody>
              {Object.entries(m.detectors).map(([k, d]) => (
                <tr key={k} className="border-b border-line/60"><td className={`py-2 ${k === "Ensemble" ? "font-semibold text-accent" : ""}`}>{k}</td><td>{d.precision.toFixed(2)}</td><td>{d.recall.toFixed(2)}</td><td>{d.f1.toFixed(2)}</td></tr>
              ))}
              <tr><td className="py-2">Logistics cost spikes (weekly Z-score)</td><td>{m.cost_spike.precision.toFixed(2)}</td><td>{m.cost_spike.recall.toFixed(2)}</td><td>{m.cost_spike.f1.toFixed(2)}</td></tr>
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">Labels are synthetic injections; unlabelled but genuinely unusual days in the real data count as false positives, so precision is understated.</p>
        </div>
      )}
    </div>
  );
}
