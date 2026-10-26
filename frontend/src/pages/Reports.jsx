import { useCallback, useEffect, useState } from "react";
import { DownloadLink, useAuth } from "../auth.jsx";

const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const select = "h-9 rounded-lg border border-line bg-field px-2 text-sm text-ink focus:border-accent focus:outline-none";
const TAG = { "Forecasting & Revenue": "text-violet bg-violet/10 border-violet/30", "Audit & Compliance": "text-risk bg-risk/10 border-risk/30", "Supply Chain & Ops": "text-ok bg-ok/10 border-ok/30" };
const size = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const when = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "never");

function Toggle({ on, onChange, children }) {
  return (
    <label className="flex cursor-pointer items-center justify-between rounded-lg border border-line bg-field px-3 py-2 text-sm">
      {children}<input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[#00A1DA]" />
    </label>
  );
}

export default function Reports() {
  const { can } = useAuth();
  const [tpl, setTpl] = useState([]);
  const [led, setLed] = useState(null);
  const [filter, setFilter] = useState({ q: "", template: "", days: 30 });
  const [page, setPage] = useState(1);
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const [custom, setCustom] = useState(false);
  const [pick, setPick] = useState({ template: "forecast_summary", format: "pdf" });

  const loadTpl = useCallback(() => fetch("/api/reports/templates").then((r) => r.json()).then((j) => setTpl(j.templates)), []);
  const loadLed = useCallback(() => {
    const q = new URLSearchParams({ page, days: filter.days, ...(filter.q && { q: filter.q }), ...(filter.template && { template: filter.template }) });
    return fetch(`/api/reports?${q}`).then((r) => r.json()).then(setLed);
  }, [filter, page]);

  useEffect(() => { loadTpl(); fetch("/api/settings").then((r) => r.json()).then((j) => setCfg(j.config.reports)); }, [loadTpl]);
  useEffect(() => { loadLed(); }, [loadLed]);

  const generate = async (template, format) => {
    setBusy(`${template}:${format}`); setMsg(null);
    const r = await fetch("/api/reports/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template, format }) });
    const j = await r.json();
    setBusy(null);
    if (!r.ok) return setMsg({ error: typeof j.detail === "string" ? j.detail : "Could not generate report" });
    setMsg({ ok: `Generated ${j.title} (${format.toUpperCase()}, ${size(j.size_bytes)})`, id: j.id });
    loadTpl(); setPage(1); loadLed();
  };
  const saveCfg = async (patch) => {
    const next = { ...cfg, ...patch };
    setCfg(next);
    await fetch("/api/settings/reports", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  };
  const pages = led ? Math.max(1, Math.ceil(led.total / led.page_size)) : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Automated dispatches</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Automated Reports & Executive Dispatches</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">Generate production-ready PDF, Excel or JSON dossiers from live forecasts, alerts and recommendations.</p>
        </div>
        <button onClick={() => setCustom(!custom)} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover">+ Create custom report</button>
      </div>

      {msg?.error && <div className="rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{msg.error}</div>}
      {msg?.ok && (
        <div className="flex items-center justify-between rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">
          {msg.ok}<DownloadLink className="font-semibold underline" url={`/api/reports/${msg.id}/download`} name="report">Download</DownloadLink>
        </div>
      )}

      {custom && (
        <div className={`${card} flex flex-wrap items-end gap-3`}>
          <label className="text-xs text-muted">Template<select className={`${select} mt-1 block`} value={pick.template} onChange={(e) => setPick({ ...pick, template: e.target.value })}>
            {tpl.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}</select></label>
          <label className="text-xs text-muted">Format<select className={`${select} mt-1 block`} value={pick.format} onChange={(e) => setPick({ ...pick, format: e.target.value })}>
            {["pdf", "xlsx", "json"].map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}</select></label>
          <button onClick={() => generate(pick.template, pick.format)} className="h-9 rounded-lg border border-accent px-4 text-sm font-semibold text-accent">Generate</button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {tpl.map((t) => (
          <div key={t.key} className={card}>
            <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${TAG[t.group] || ""}`}>{t.group}</span>
            <h3 className="mt-3 text-lg font-semibold">{t.title}</h3>
            <p className="mt-1 min-h-[40px] text-sm text-muted">{t.description}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 rounded-lg bg-field p-3 text-center">
              <div><div className="text-lg font-bold">{t.runs}</div><div className="text-[10px] uppercase text-muted">Generated</div></div>
              <div><div className="text-sm font-bold">{when(t.last_run)}</div><div className="text-[10px] uppercase text-muted">Last run</div></div>
            </div>
            <div className="mt-4 flex gap-2">
              <button onClick={() => generate(t.key, "pdf")} disabled={!!busy} className="h-9 flex-1 rounded-lg bg-accent text-sm font-semibold text-canvas hover:bg-accent-hover disabled:opacity-50">
                {busy === `${t.key}:pdf` ? "Generating…" : "Generate now (PDF)"}</button>
              {["xlsx", "json"].map((f) => (
                <button key={f} onClick={() => generate(t.key, f)} disabled={!!busy} title={`Generate ${f.toUpperCase()}`}
                  className="h-9 rounded-lg border border-line px-3 text-xs font-semibold uppercase hover:bg-field disabled:opacity-50">{busy === `${t.key}:${f}` ? "…" : f}</button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {cfg && (
        <div className={card}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Pipeline & channel delivery</h2>
            <span className="rounded-full border border-warn/30 bg-warn/10 px-3 py-1 text-[11px] font-semibold text-warn">Saved as configuration — automatic scheduling and delivery are not active in this build</span>
          </div>
          <fieldset disabled={!can("approve_actions")} className="m-0 mt-4 grid min-w-0 gap-4 border-0 p-0 lg:grid-cols-3">
            <div>
              <div className={label}>Dispatch cadence</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {["Daily", "Weekly", "Monthly", "Trigger-based"].map((c) => (
                  <button key={c} onClick={() => saveCfg({ cadence: c })} className={`h-9 rounded-lg border text-sm ${cfg.cadence === c ? "border-accent bg-accent/10 font-semibold text-accent" : "border-line text-muted"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <div className={label}>Distribution channels</div>
              <Toggle on={cfg.email} onChange={(v) => saveCfg({ email: v })}>Email · Store GMs & managers</Toggle>
              <Toggle on={cfg.slack} onChange={(v) => saveCfg({ slack: v })}>Slack · #decision-iq-alerts</Toggle>
              <Toggle on={cfg.erp_sftp} onChange={(v) => saveCfg({ erp_sftp: v })}>ERP SAP / Tally SFTP</Toggle>
            </div>
            <div className="space-y-2">
              <div className={label}>Payload formats</div>
              <Toggle on={cfg.pdf} onChange={(v) => saveCfg({ pdf: v })}>Executive PDF</Toggle>
              <Toggle on={cfg.xlsx} onChange={(v) => saveCfg({ xlsx: v })}>Raw XLSX data (multi-tab)</Toggle>
              <Toggle on={cfg.json_stream} onChange={(v) => saveCfg({ json_stream: v })}>JSON payload</Toggle>
            </div>
          </fieldset>
        </div>
      )}

      <div className={card}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div><h2 className="text-lg font-semibold">Generation ledger & artifact downloads</h2><p className="text-xs text-muted">Every file carries a SHA-256 checksum for verification.</p></div>
          <div className="flex flex-wrap gap-2">
            <input value={filter.q} onChange={(e) => { setFilter({ ...filter, q: e.target.value }); setPage(1); }} placeholder="Filter reports…" className={`${select} w-44`} />
            <select className={select} value={filter.template} onChange={(e) => { setFilter({ ...filter, template: e.target.value }); setPage(1); }}>
              <option value="">All templates</option>{tpl.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}</select>
            <select className={select} value={filter.days} onChange={(e) => { setFilter({ ...filter, days: +e.target.value }); setPage(1); }}>
              {[[7, "Past 7 days"], [30, "Past 30 days"], [365, "Past year"]].map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
          </div>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className={`${label} border-b border-line`}><tr><th className="py-2">Report</th><th>Format</th><th>Run time (UTC)</th><th>Size</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(led?.reports || []).map((r) => (
                <tr key={r.id} className="border-b border-line/60">
                  <td className="py-2"><div className="font-semibold">{r.title}</div><div className="font-mono text-[10px] text-muted">SHA256: {r.sha256.slice(0, 8)}…{r.sha256.slice(-4)}</div></td>
                  <td className="uppercase">{r.format}</td><td className="text-muted">{when(r.created_at)}</td><td className="text-muted">{size(r.size_bytes)}</td>
                  <td><span className="rounded-full bg-ok/15 px-2 py-0.5 text-[11px] font-semibold text-ok">● {r.status}</span></td>
                  <td className="text-right"><DownloadLink className="rounded-lg border border-line px-3 py-1 text-xs font-semibold hover:bg-field" url={`/api/reports/${r.id}/download`} name="report">Download</DownloadLink></td>
                </tr>
              ))}
              {led && led.reports.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-sm text-muted">No reports yet — generate one above.</td></tr>}
            </tbody>
          </table>
        </div>
        {led && (
          <div className="mt-3 flex items-center justify-between text-xs text-muted">
            <span>Showing {led.reports.length} of {led.total} runs · storage used {size(led.storage_bytes)}</span>
            <div className="flex gap-2">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Previous</button>
              <span className="px-1 py-1">{page} / {pages}</span>
              <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
