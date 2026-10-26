import { useCallback, useEffect, useState } from "react";
import { DownloadLink, useAuth } from "../auth.jsx";

const inr = (v) => {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)}L`;
  return "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(v);
};
const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const KIND = {
  reorder: ["Inventory Reorder", "text-accent border-accent/30 bg-accent/10"],
  transfer: ["Inter-store Transfer", "text-accent border-accent/30 bg-accent/10"],
  markdown: ["Dynamic Markdown", "text-violet border-violet/30 bg-violet/10"],
  budget: ["Budget Reallocation", "text-ok border-ok/30 bg-ok/10"],
};
const TABS = [["", "All levers"], ["reorder", "Reorders"], ["transfer", "Transfers"], ["markdown", "Markdowns"], ["budget", "Budget"]];

function Rec({ r, checked, onCheck, onAction, readOnly, locked }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const pl = r.payload || {};
  const editable = r.kind === "reorder" || r.kind === "transfer" || r.kind === "markdown";
  const startEdit = () => { setVal(r.kind === "markdown" ? pl.discount_pct : pl.qty); setEditing(true); };
  const saveEdit = async () => {
    await onAction(r.id, r.kind === "markdown" ? { discount_pct: +val } : { quantity: +val });
    setEditing(false);
  };
  return (
    <div className={`${card} border-l-4 ${r.kind === "markdown" ? "border-l-violet" : r.kind === "budget" ? "border-l-ok" : "border-l-accent"}`}>
      <div className="flex flex-wrap items-start gap-3">
        {!readOnly && !locked && <input type="checkbox" checked={checked} onChange={() => onCheck(r.id)} className="mt-1 h-4 w-4 accent-[#00A1DA]" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded-full border px-2.5 py-0.5 font-semibold uppercase tracking-wide ${KIND[r.kind][1]}`}>{KIND[r.kind][0]}</span>
            {pl.sku && <span className="font-mono text-muted">{pl.sku}</span>}
            <span className="text-muted">· {Math.round(r.confidence * 100)}% confidence</span>
            {r.kind === "reorder" && pl.runout_days != null && <span className={pl.runout_days < 5 ? "text-risk" : "text-warn"}>· runs out in {pl.runout_days} days</span>}
          </div>
          <h3 className="mt-2 text-base font-semibold">{r.title}</h3>
          <p className="mt-1 text-sm text-muted">{r.detail}</p>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold text-ok">{inr(r.impact_inr)}</div>
          <div className="text-[11px] text-muted">{r.impact_label}</div>
        </div>
      </div>
      <button onClick={() => setOpen(!open)} className="mt-3 text-xs font-semibold text-accent">{open ? "Hide" : "How was this calculated?"} (audit trail)</button>
      {open && (
        <table className="mt-2 w-full rounded-lg bg-field text-left text-xs">
          <tbody>{(pl.calc || []).map(([k, v]) => (
            <tr key={k} className="border-b border-line/60 last:border-0"><td className="px-3 py-1.5 text-muted">{k}</td><td className="px-3 py-1.5 font-mono">{v}</td></tr>
          ))}</tbody>
        </table>
      )}
      {locked ? (
        <div className="mt-2 text-right text-xs text-muted">{r.status === "Pending" ? "View only — your role cannot approve actions" : r.status}</div>
      ) : !readOnly ? (
        <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
          <button onClick={() => onAction(r.id, { status: "Dismissed" })} className="px-3 py-1.5 text-sm text-muted hover:text-ink">Dismiss</button>
          {editing ? (
            <>
              <input type="number" value={val} onChange={(e) => setVal(e.target.value)} className="h-9 w-24 rounded-lg border border-accent bg-field px-2 text-sm" />
              <span className="text-xs text-muted">{r.kind === "markdown" ? "% off" : "units"}</span>
              <button onClick={saveEdit} className="h-9 rounded-lg border border-line px-3 text-sm font-semibold">Save</button>
            </>
          ) : editable && (
            <button onClick={startEdit} className="h-9 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-field">
              {r.kind === "markdown" ? "Adjust discount" : "Edit quantity"}
            </button>
          )}
          <button onClick={() => onAction(r.id, { status: "Approved" })} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover">
            {{ reorder: "Approve PO", transfer: "Approve Transfer", markdown: "Approve Promo", budget: "Approve Shift" }[r.kind]}
          </button>
        </div>
      ) : (
        <div className="mt-2 text-right text-xs text-muted">{r.status} {r.decided_at ? `· ${r.decided_at.replace("T", " ")}` : ""}
          <button onClick={() => onAction(r.id, { status: "Pending" })} className="ml-3 text-accent">Reopen</button></div>
      )}
    </div>
  );
}

export default function Recommendations() {
  const { can } = useAuth();
  const allowed = can("approve_actions");
  const [sum, setSum] = useState(null);
  const [recs, setRecs] = useState([]);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("Pending");
  const [sel, setSel] = useState(new Set());
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setSum(await fetch("/api/recommendations/summary").then((r) => r.json()));
    const q = new URLSearchParams({ status, ...(kind && { kind }) });
    setRecs((await fetch(`/api/recommendations?${q}`).then((r) => r.json())).recommendations);
  }, [kind, status]);
  useEffect(() => { load().catch((e) => setMsg({ error: e.message })); setSel(new Set()); }, [load]);

  const api = async (path, method, body) => {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) setMsg({ error: typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail) });
    return r.ok ? j : null;
  };
  const act = async (id, body) => { setMsg(null); await api(`/api/recommendations/${id}`, "PATCH", body); await load(); };
  const generate = async () => {
    setBusy(true); setMsg(null);
    const j = await api("/api/recommendations/generate", "POST");
    setBusy(false);
    if (j) setMsg({ ok: `Generated ${j.generated} recommendations (${j.decisions_kept} earlier decisions kept).` });
    await load();
  };
  const bulk = async (s) => {
    const j = await api("/api/recommendations/bulk", "POST", { ids: [...sel], status: s });
    if (j) setMsg({ ok: `${s}: ${j.updated} actions worth ${inr(j.value)}.` });
    setSel(new Set()); await load();
  };
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const selValue = recs.filter((r) => sel.has(r.id)).reduce((a, r) => a + r.impact_inr, 0);
  const c = sum?.counts || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Autonomous prescriptive engine</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Prescriptive Decision Recommendations</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">Forecasts, current stock and prices become concrete actions, each with its calculation audit trail.</p>
        </div>
        <button onClick={generate} disabled={busy || !allowed} title={allowed ? undefined : "Your role is not permitted to do this"} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover disabled:opacity-50">
          {busy ? "Generating…" : sum?.total ? "Regenerate" : "Generate recommendations"}
        </button>
      </div>

      {msg?.error && <div className="rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{msg.error}</div>}
      {msg?.ok && <div className="rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{msg.ok}</div>}
      {sum && !sum.total && <div className="rounded-lg border border-warn/40 bg-warn/10 p-4 text-sm text-warn">No recommendations yet — click <strong>Generate recommendations</strong>.</div>}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Pending value unlock", sum ? inr(sum.pending_value) : "–", `${c.Pending || 0} levers · avg confidence ${sum?.avg_confidence != null ? Math.round(sum.avg_confidence * 100) + "%" : "–"}`],
          ["Approved this cycle", sum ? inr(sum.approved_value) : "–", `${c.Approved || 0} actions executed`],
          ["Action execution rate", sum?.execution_rate != null ? `${sum.execution_rate}%` : "–", "approved ÷ decided"],
          ["Stock-out vulnerability", sum ? `${sum.stockout_risk_series} series` : "–", sum ? `across ${sum.stockout_risk_stores} stores, under 5 days of cover` : ""],
        ].map(([k, v, s]) => (
          <div key={k} className={card}><div className={label}>{k}</div><div className="mt-2 text-3xl font-bold">{v}</div><div className="mt-1 text-xs text-muted">{s}</div></div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {TABS.map(([k, t]) => (
            <button key={k} onClick={() => setKind(k)} className={`rounded-lg border px-3 py-1.5 text-sm ${kind === k ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:text-ink"}`}>
              {t}{k && sum?.by_kind?.[k] ? ` · ${sum.by_kind[k]}` : ""}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-sm">
          {["Pending", "Approved", "Dismissed"].map((s) => (
            <button key={s} onClick={() => setStatus(s)} className={`rounded-lg px-3 py-1.5 ${status === s ? "bg-card font-semibold text-ink" : "text-muted"}`}>{s} ({c[s] || 0})</button>
          ))}
          <DownloadLink url={`/api/recommendations/export.csv?status=${status}`} name="action_plan.csv" className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:bg-card">Export plan (CSV)</DownloadLink>
        </div>
      </div>

      {status === "Pending" && sel.size > 0 && (
        <div className="sticky top-2 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent/40 bg-card p-3 shadow-lg">
          <span className="text-sm"><b>{sel.size}</b> selected · combined impact <b className="text-ok">{inr(selValue)}</b></span>
          <div className="flex gap-2">
            <button onClick={() => bulk("Dismissed")} className="h-9 rounded-lg border border-line px-3 text-sm text-muted">Dismiss selected</button>
            <button onClick={() => bulk("Approved")} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas">Bulk approve ({inr(selValue)})</button>
          </div>
        </div>
      )}
      {status === "Pending" && allowed && recs.length > 0 && (
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" className="accent-[#00A1DA]" checked={sel.size === recs.length} onChange={(e) => setSel(e.target.checked ? new Set(recs.map((r) => r.id)) : new Set())} /> Select all {recs.length} shown
        </label>
      )}

      <div className="space-y-3">
        {recs.map((r) => <Rec key={r.id + r.title} r={r} checked={sel.has(r.id)} onCheck={toggle} onAction={act} readOnly={status !== "Pending"} locked={!allowed} />)}
        {sum?.total > 0 && recs.length === 0 && <p className="text-sm text-muted">Nothing here.</p>}
      </div>
    </div>
  );
}
