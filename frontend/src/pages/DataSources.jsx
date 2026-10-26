import { useCallback, useEffect, useRef, useState } from "react";

const fmt = new Intl.NumberFormat("en-IN");

const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";

function Step({ n, step }) {
  const tone =
    step.status === "done" ? "text-ok" : step.status === "active" ? "text-accent" : step.status === "failed" ? "text-risk" : "text-muted";
  const ring = step.status === "active" ? "border-accent" : "border-line";
  return (
    <div className={`rounded-xl border ${ring} bg-card p-4`}>
      <div className={`${label} ${tone}`}>
        Step {n} · {step.status === "done" ? "Completed" : step.status === "active" ? "Active" : step.status === "failed" ? "Failed" : "Ready"}
      </div>
      <div className="mt-1 text-sm font-semibold">{step.label}</div>
      {step.detail && <div className="mt-1 truncate text-xs text-muted">{step.detail}</div>}
    </div>
  );
}

export default function DataSources() {
  const [state, setState] = useState(null);
  const [preview, setPreview] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const refresh = useCallback(async () => {
    const s = await fetch("/api/pipeline/status").then((r) => r.json());
    setState(s);
    if (s.status === "complete") {
      const p = await fetch("/api/pipeline/preview?n=4");
      if (p.ok) setPreview(await p.json());
    }
    return s;
  }, []);

  useEffect(() => {
    refresh().catch((e) => setMsg({ error: `Backend unreachable: ${e.message}` }));
  }, [refresh]);

  useEffect(() => {
    if (!state?.running && state?.status !== "running") return;
    const t = setInterval(() => refresh().catch(() => {}), 1000);
    return () => clearInterval(t);
  }, [state?.running, state?.status, refresh]);

  const run = async () => {
    setMsg(null);
    const r = await fetch("/api/pipeline/run", { method: "POST" });
    if (!r.ok) setMsg({ error: (await r.json()).detail });
    else setState((s) => ({ ...s, status: "running", running: true }));
    refresh();
  };

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    setMsg(null);
    const body = new FormData();
    body.append("file", file);
    const r = await fetch("/api/pipeline/upload", { method: "POST", body });
    const j = await r.json();
    setBusy(false);
    if (!r.ok) return setMsg({ error: j.detail });
    setMsg({ ok: `Uploaded ${j.filename} (${(j.size_bytes / 1048576).toFixed(1)} MB) - ${j.mapping.length} columns mapped. Re-running pipeline…` });
    run();
  };

  const q = state?.quality;
  const f = state?.features;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Data pipeline</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Data Sources & Pipeline Configuration</h1>
        </div>
        <div className="flex items-center gap-3 text-sm text-muted">
          {state?.status === "complete" && <span className="text-ok">Pipeline complete · {state.latency_s}s</span>}
          {state?.status === "failed" && <span className="text-risk">Pipeline failed</span>}
          {(state?.running || state?.status === "running") && <span className="text-accent">Running…</span>}
          <button
            onClick={run}
            disabled={state?.running}
            className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover disabled:opacity-50"
          >
            Re-run Pipeline
          </button>
        </div>
      </div>

      {msg?.error && <div className="rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{msg.error}</div>}
      {msg?.ok && <div className="rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{msg.ok}</div>}
      {state?.status === "failed" && (
        <div className="rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">
          <strong>Pipeline exception:</strong> {state.error}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(state?.steps || []).map((s, i) => (
          <Step key={s.key} n={i + 1} step={s} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div
          className="rounded-xl border-2 border-dashed border-line-strong bg-card p-6 text-center"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            upload(e.dataTransfer.files[0]);
          }}
        >
          <div className="text-lg font-semibold">Ingest Static Datasets</div>
          <p className="mt-2 text-sm text-muted">Drop CSV, Excel (.xlsx) or Parquet files here. Schema is auto-detected. Max 250MB per batch.</p>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.parquet" hidden onChange={(e) => upload(e.target.files[0])} />
          <button
            onClick={() => fileRef.current.click()}
            disabled={busy}
            className="mt-4 h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover disabled:opacity-50"
          >
            {busy ? "Uploading…" : "Browse Files"}
          </button>
          {state?.source && <p className="mt-3 text-xs text-muted">Current source: {state.source}</p>}
        </div>

        <div className={`${card} lg:col-span-2`}>
          <div className={label}>Data quality</div>
          {q ? (
            <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-5">
              <div>
                <div className="text-3xl font-bold text-ok">{q.quality_score}<span className="text-sm text-muted"> /100</span></div>
                <div className="text-sm font-semibold">{q.quality_label}</div>
              </div>
              {[
                ["Records processed", fmt.format(q.rows_in)],
                ["Missing imputed", fmt.format(q.missing_imputed + q.gaps_filled)],
                ["Duplicates removed", fmt.format(q.duplicates_removed)],
                ["Outliers capped", fmt.format(q.outliers_capped)],
              ].map(([k, v]) => (
                <div key={k}>
                  <div className="text-xl font-semibold">{v}</div>
                  <div className="text-xs text-muted">{k}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">Run the pipeline to see quality metrics.</p>
          )}
        </div>
      </div>

      <div className={card}>
        <h2 className="text-lg font-semibold">Column Mapping & Inferred Entities</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className={`${label} border-b border-line`}>
              <tr>
                {["Source column", "Target entity", "Data type", "Sample value", "Validation"].map((h) => (
                  <th key={h} className="py-2 pr-4">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(state?.mapping || []).map((m) => (
                <tr key={m.source} className="border-b border-line/60">
                  <td className="py-2 pr-4 font-mono text-xs">{m.source}</td>
                  <td className="py-2 pr-4 text-accent">{m.target_label}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-muted">{m.dtype}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{m.sample}</td>
                  <td className={`py-2 ${m.valid_pct >= 99.5 ? "text-ok" : "text-warn"}`}>Valid {m.valid_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className={card}>
        <h2 className="text-lg font-semibold">Automated Feature Engineering Pipeline</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {(f?.catalog || []).map((c) => (
            <div key={c.name} className="rounded-lg border border-line bg-field p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-semibold text-accent">{c.name}</span>
                <span className="text-[10px] text-muted">{c.group}</span>
              </div>
              <div className="mt-1 text-xs text-muted">{c.description}</div>
            </div>
          ))}
        </div>
      </div>

      {preview && (
        <div className={card}>
          <h2 className="text-lg font-semibold">Data Preview</h2>
          <p className="text-xs text-muted">Latest {preview.rows.length} rows of {fmt.format(f?.rows || 0)} engineered rows</p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className={`${label} border-b border-line`}>
                <tr>{preview.columns.map((c) => <th key={c} className="whitespace-nowrap py-2 pr-4">{c}</th>)}</tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={i} className="border-b border-line/60">
                    {preview.columns.map((c) => <td key={c} className="whitespace-nowrap py-2 pr-4 font-mono">{String(r[c] ?? "—")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
