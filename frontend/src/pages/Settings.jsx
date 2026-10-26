import { useCallback, useEffect, useState } from "react";
import { PageSkeleton } from "../components/ui.jsx";

const card = "rounded-xl border border-line bg-card p-5";
const label = "text-[11px] font-semibold uppercase tracking-wider text-muted";
const select = "h-9 rounded-lg border border-line bg-field px-2 text-sm text-ink focus:border-accent focus:outline-none";

const Badge = ({ applied }) => (
  <span className={`ml-2 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${applied ? "border-ok/30 bg-ok/10 text-ok" : "border-line bg-field text-muted"}`}>{applied ? "Applied" : "Stored only"}</span>
);

function Slider({ title, note, value, min, max, step, onChange, fmt, applied }) {
  return (
    <div className="rounded-lg border border-line bg-field p-3">
      <div className="flex items-center justify-between"><div><span className="text-sm font-semibold">{title}</span><Badge applied={applied} /><div className="text-[11px] text-muted">{note}</div></div>
        <span className="font-mono text-lg font-semibold text-accent">{fmt(value)}</span></div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} className="mt-2 w-full accent-[#00A1DA]" />
      <div className="flex justify-between text-[10px] text-muted"><span>{fmt(min)}</span><span>{fmt(max)}</span></div>
    </div>
  );
}
function Toggle({ title, note, on, onChange, applied }) {
  return (
    <label className="flex cursor-pointer items-center justify-between rounded-lg border border-line bg-field p-3">
      <span><span className="text-sm font-semibold">{title}</span><Badge applied={applied} /><span className="block text-[11px] text-muted">{note}</span></span>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[#00A1DA]" />
    </label>
  );
}
const Cell = ({ v }) => (v === "locked" ? <span title="Locked by policy" className="text-muted">🔒</span> : v ? <span className="text-ok">✓</span> : <span className="text-muted">✕</span>);

export default function Settings() {
  const [data, setData] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [saved, setSaved] = useState(null);
  const [msg, setMsg] = useState(null);
  const [audit, setAudit] = useState(null);
  const [af, setAf] = useState({ user: "", category: "", days: 7 });
  const [apage, setApage] = useState(1);
  const [ver, setVer] = useState(null);

  const load = useCallback(() => fetch("/api/settings").then((r) => r.json()).then((j) => { setData(j); setCfg(j.config); setSaved(j.config); }), []);
  const loadAudit = useCallback(() => {
    const q = new URLSearchParams({ days: af.days, page: apage, ...(af.user && { user: af.user }), ...(af.category && { category: af.category }) });
    fetch(`/api/audit?${q}`).then((r) => (r.ok ? r.json() : null)).then(setAudit);
  }, [af, apage]);
  const verify = () => fetch("/api/audit/verify").then((r) => (r.ok ? r.json() : null)).then(setVer);

  useEffect(() => { load(); verify(); }, [load]);
  useEffect(() => { loadAudit(); }, [loadAudit]);

  const set = (section, key) => (v) => setCfg((c) => ({ ...c, [section]: { ...c[section], [key]: v } }));
  const dirty = cfg && JSON.stringify(cfg) !== JSON.stringify(saved);

  const save = async () => {
    setMsg(null);
    for (const section of Object.keys(cfg)) {
      if (JSON.stringify(cfg[section]) === JSON.stringify(saved[section])) continue;
      const r = await fetch(`/api/settings/${section}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg[section]) });
      if (!r.ok) return setMsg({ error: (await r.json()).detail });
    }
    setMsg({ ok: "Settings saved. Risk thresholds apply to the next scan; inventory rules apply when recommendations are regenerated." });
    await load(); loadAudit(); verify();
  };
  const reset = async () => {
    await fetch("/api/settings/reset", { method: "POST" });
    setMsg({ ok: "Settings reset to system defaults." });
    await load(); loadAudit(); verify();
  };

  if (!cfg) return <PageSkeleton rows={2} />;
  const { risk, inventory, retraining, compliance } = cfg;
  const caps = data.user.capabilities;
  const allow = (section) => caps.includes(data.section_caps[section]);
  const pages = audit ? Math.max(1, Math.ceil(audit.total / audit.page_size)) : 1;
  const u = data.user;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={label}>Karnataka regional hub · policy active</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Platform Settings & Governance</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">Role permissions, anomaly sensitivity, inventory rules, retraining schedule and the audit trail.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={reset} disabled={!caps.includes("modify_thresholds")} title={caps.includes("modify_thresholds") ? undefined : "Admin only"} className="h-9 rounded-lg border border-line px-4 text-sm font-semibold hover:bg-card disabled:opacity-40">Reset to system defaults</button>
          <button onClick={save} disabled={!dirty} className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover disabled:opacity-40">Save changes</button>
        </div>
      </div>
      {msg?.error && <div className="rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{msg.error}</div>}
      {msg?.ok && <div className="rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{msg.ok}</div>}

      <div className={`${card} flex flex-wrap items-center justify-between gap-3`}>
        <div className="flex items-center gap-3"><span className="text-2xl">🛡</span><div><div className="font-semibold">Your active role: <span className="rounded-full bg-accent/20 px-2 py-0.5 text-xs text-accent">{u.role} ({u.name})</span> <span className="text-xs text-muted">· {u.tier}</span></div>
          <div className="text-xs text-muted">Authorized for operational execution, dynamic pricing markdowns and stock-transfer approvals.</div></div></div>
        <span className="rounded bg-field px-2 py-1 font-mono text-[11px] text-muted">ACCESS SCOPE: {u.scope}</span>
      </div>

      <div className={card}>
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Role-permission matrix (RBAC)</h2><span className="rounded bg-field px-2 py-0.5 text-[10px] text-muted">Enforced by the API on every request</span></div>
        <table className="mt-3 w-full text-left text-sm">
          <thead className={`${label} border-b border-line`}><tr><th className="py-2">Platform capability</th><th className="text-center">Admin</th><th className="bg-accent/5 text-center text-accent">Manager</th><th className="text-center">Analyst</th></tr></thead>
          <tbody>{data.rbac.map((r) => (
            <tr key={r.capability} className="border-b border-line/60"><td className="py-2.5">{r.capability}{caps.includes(r.key) ? <span className="ml-2 rounded-full bg-ok/10 px-2 py-0.5 text-[10px] text-ok">you</span> : null}</td><td className="text-center"><Cell v={r.admin} /></td><td className="bg-accent/5 text-center"><Cell v={r.manager} /></td><td className="text-center"><Cell v={r.analyst} /></td></tr>
          ))}</tbody>
        </table>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Anomaly thresholds & sensitivity{!allow("risk") && <span className="ml-2 text-xs font-normal text-muted">🔒 read-only for your role</span>}</h2>
          <fieldset disabled={!allow("risk")} className="m-0 min-w-0 space-y-3 border-0 p-0 disabled:opacity-60">
          <Slider title="Spike / sustained-drop Z-score" note="Higher = fewer, stronger alerts" value={risk.z_threshold} min={1.5} max={6} step={0.1} onChange={set("risk", "z_threshold")} fmt={(v) => `${(+v).toFixed(1)}σ`} applied />
          <Slider title="ML detector sensitivity" note="Share of billed rows each ML detector flags" value={risk.contamination * 100} min={0.05} max={1} step={0.05} onChange={(v) => set("risk", "contamination")(v / 100)} fmt={(v) => `${(+v).toFixed(2)}%`} applied />
          <Toggle title="Auto-suppress recurring vendor anomalies" note="Bypass alert storms for verified bulk reconciliations" on={risk.auto_suppress_vendor} onChange={set("risk", "auto_suppress_vendor")} />
          <Toggle title="Slack webhook on critical alert" note="Dispatch to #karnataka-retail-ops" on={risk.slack_critical_alerts} onChange={set("risk", "slack_critical_alerts")} />
          </fieldset>
        </div>
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Inventory & recommendation rules{!allow("inventory") && <span className="ml-2 text-xs font-normal text-muted">🔒 read-only for your role</span>}</h2>
          <fieldset disabled={!allow("inventory")} className="m-0 min-w-0 space-y-3 border-0 p-0 disabled:opacity-60">
          <Slider title="Overstock threshold" note="Days of cover that triggers transfers / markdowns" value={inventory.overstock_cover_days} min={15} max={120} step={5} onChange={set("inventory", "overstock_cover_days")} fmt={(v) => `${v} days`} applied />
          <Slider title="Target cover after clearing" note="Cover kept at the donor store" value={inventory.target_cover_days} min={7} max={60} step={1} onChange={set("inventory", "target_cover_days")} fmt={(v) => `${v} days`} applied />
          <Slider title="Maximum markdown" note="Largest discount the engine may recommend" value={inventory.max_discount_pct} min={5} max={40} step={1} onChange={set("inventory", "max_discount_pct")} fmt={(v) => `${v}%`} applied />
          <Slider title="Supplier lead time" note="Used for reorder points" value={inventory.lead_time_days} min={1} max={21} step={1} onChange={set("inventory", "lead_time_days")} fmt={(v) => `${v} days`} applied />
          <Slider title="Service level (z)" note="1.65 ≈ 95% cycle service level" value={inventory.service_level_z} min={0.5} max={3} step={0.05} onChange={set("inventory", "service_level_z")} fmt={(v) => (+v).toFixed(2)} applied />
          </fieldset>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Retraining & data governance{!(allow("retraining") && allow("compliance")) && <span className="ml-2 text-xs font-normal text-muted">🔒 partly read-only for your role</span>}</h2>
          <fieldset disabled={!allow("retraining")} className="m-0 min-w-0 space-y-3 border-0 p-0 disabled:opacity-60">
          <label className="block text-xs text-muted">Automated retraining cadence<Badge applied={false} />
            <select className={`${select} mt-1 w-full`} value={retraining.cadence} onChange={(e) => set("retraining", "cadence")(e.target.value)}>
              {["Every Sunday at 02:00 (off-peak)", "Daily at 02:00", "Monthly (1st, 02:00)", "Manual only"].map((c) => <option key={c}>{c}</option>)}</select></label>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg border border-line bg-field p-3"><div className={label}>Holdout validation</div><div className="mt-1 font-semibold">Last {retraining.holdout_days} days</div><div className="text-[11px] text-muted">fixed in the training code</div></div>
            <div className="rounded-lg border border-line bg-field p-3"><div className={label}>Promotion rule<Badge applied={false} /></div>
              <div className="mt-1 flex items-center gap-1 font-semibold">MAPE delta &gt; <input type="number" step="0.1" min="0" max="5" value={retraining.promotion_mape_delta} onChange={(e) => set("retraining", "promotion_mape_delta")(+e.target.value)} className="h-7 w-16 rounded border border-line bg-card px-1 text-sm" />%</div></div>
          </div>
          </fieldset>
          <fieldset disabled={!allow("compliance")} className="m-0 min-w-0 space-y-3 border-0 p-0 disabled:opacity-60">
          <Toggle title="Customer PII anonymisation" note="Hash phone numbers and bill IDs at ingest (the demo data holds no PII)" on={compliance.pii_anonymisation} onChange={set("compliance", "pii_anonymisation")} />
          <Slider title="Data retention" note="Rolling history kept before archiving" value={compliance.retention_months} min={6} max={120} step={6} onChange={set("compliance", "retention_months")} fmt={(v) => `${v} months`} />
          </fieldset>
          <p className="text-xs text-muted">“Stored only” settings are saved and audited but no scheduler or retention job reads them yet.</p>
        </div>

        {!caps.includes("view_audit") ? (
          <div className={card}><h2 className="text-lg font-semibold">System audit & governance trail</h2><p className="mt-2 text-sm text-muted">🔒 Your role cannot view the audit trail.</p></div>
        ) : (
        <div className={card}>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">System audit & governance trail</h2>
            <button onClick={verify} className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${ver?.ok === false ? "border-risk/40 bg-risk/10 text-risk" : "border-ok/30 bg-ok/10 text-ok"}`}>
              {ver ? (ver.ok ? `✓ Hash chain verified · ${ver.entries} entries` : `✕ Tampering detected at entry #${ver.broken_at}`) : "Verify chain"}</button></div>
          <p className="text-xs text-muted">Each entry's hash covers the previous one, so any edit or deletion breaks the chain.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <select className={select} value={af.user} onChange={(e) => { setAf({ ...af, user: e.target.value }); setApage(1); }}><option value="">All users</option>{(audit?.users || []).map((x) => <option key={x}>{x}</option>)}</select>
            <select className={select} value={af.category} onChange={(e) => { setAf({ ...af, category: e.target.value }); setApage(1); }}><option value="">All actions</option>{(audit?.categories || []).map((x) => <option key={x}>{x}</option>)}</select>
            <select className={select} value={af.days} onChange={(e) => { setAf({ ...af, days: +e.target.value }); setApage(1); }}>{[[1, "Last 24 h"], [7, "Last 7 days"], [90, "Last 90 days"]].map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className={`${label} border-b border-line`}><tr><th className="py-2">Time (UTC)</th><th>User</th><th>Action</th><th>Hash</th></tr></thead>
              <tbody>{(audit?.entries || []).map((e) => (
                <tr key={e.id} className="border-b border-line/60 align-top"><td className="py-2 font-mono text-[11px] text-muted">{e.timestamp.replace("T", " ")}</td>
                  <td>{e.user}<div className="text-[10px] text-muted">{e.role}</div></td><td>{e.action}</td><td className="font-mono text-[10px] text-muted">{e.hash}</td></tr>
              ))}
              {audit && audit.entries.length === 0 && <tr><td colSpan={4} className="py-5 text-center text-muted">No events in this period.</td></tr>}</tbody>
            </table>
          </div>
          {audit && <div className="mt-3 flex items-center justify-between text-xs text-muted"><span>{audit.total} events</span>
            <div className="flex gap-2"><button disabled={apage <= 1} onClick={() => setApage(apage - 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Previous</button>
              <span className="py-1">{apage} / {pages}</span><button disabled={apage >= pages} onClick={() => setApage(apage + 1)} className="rounded border border-line px-3 py-1 disabled:opacity-40">Next</button></div></div>}
        </div>
        )}
      </div>

      {caps.includes("manage_users") && <Users />}
    </div>
  );
}


function Users() {
  const [rows, setRows] = useState([]);
  const [roles, setRoles] = useState([]);
  const [form, setForm] = useState({ full_name: "", email: "", role: "Analyst", password: "" });
  const [msg, setMsg] = useState(null);
  const load = useCallback(() => fetch("/api/users").then((r) => r.json()).then((j) => { setRows(j.users); setRoles(j.roles); }), []);
  useEffect(() => { load(); }, [load]);

  const call = async (url, method, body, ok) => {
    setMsg(null);
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return setMsg({ error: typeof j.detail === "string" ? j.detail : "Invalid input: check the email and use a password of at least 10 characters" });
    setMsg({ ok }); load();
    return j;
  };
  const create = async (e) => {
    e.preventDefault();
    if (await call("/api/users", "POST", form, `Created ${form.email}`)) setForm({ full_name: "", email: "", role: "Analyst", password: "" });
  };
  const reset = (u) => {
    const pw = window.prompt(`New password for ${u.email} (min 10 characters):`);
    if (pw) call(`/api/users/${u.id}`, "PATCH", { password: pw }, `Password reset for ${u.email}`);
  };
  const input = "h-9 rounded-lg border border-line bg-field px-2 text-sm text-ink focus:border-accent focus:outline-none";

  return (
    <div className={card}>
      <h2 className="text-lg font-semibold">Users & access <span className="ml-1 rounded-full bg-field px-2 py-0.5 text-xs text-muted">{rows.length}</span></h2>
      <p className="text-xs text-muted">Admin only. Roles take effect on the user's next request; deactivated accounts are signed out immediately. SSO and per-store assignment are not implemented.</p>
      {msg?.error && <div className="mt-3 rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{msg.error}</div>}
      {msg?.ok && <div className="mt-3 rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{msg.ok}</div>}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className={`${label} border-b border-line`}><tr><th className="py-2">User</th><th>Role</th><th>Status</th><th>Last sign-in (UTC)</th><th></th></tr></thead>
          <tbody>{rows.map((u) => (
            <tr key={u.id} className="border-b border-line/60">
              <td className="py-2"><div className="font-semibold">{u.name}</div><div className="text-xs text-muted">{u.email}</div></td>
              <td><select className={input} value={u.role} onChange={(e) => call(`/api/users/${u.id}`, "PATCH", { role: e.target.value }, `${u.name} is now ${e.target.value}`)}>{roles.map((r) => <option key={r}>{r}</option>)}</select></td>
              <td><button onClick={() => call(`/api/users/${u.id}`, "PATCH", { active: !u.active }, `${u.name} ${u.active ? "deactivated" : "reactivated"}`)} className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${u.active ? "border-ok/30 bg-ok/10 text-ok" : "border-line bg-field text-muted"}`}>{u.active ? "Active" : "Deactivated"}</button></td>
              <td className="text-xs text-muted">{u.last_login ? u.last_login.replace("T", " ") : "never"}</td>
              <td className="text-right"><button onClick={() => reset(u)} className="rounded-lg border border-line px-3 py-1 text-xs hover:bg-field">Reset password</button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <form onSubmit={create} className="mt-4 grid gap-2 sm:grid-cols-[1fr_1.3fr_auto_1fr_auto]">
        <input className={input} placeholder="Full name" required minLength={2} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        <input className={input} type="email" placeholder="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <select className={input} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{roles.map((r) => <option key={r}>{r}</option>)}</select>
        <input className={input} type="password" placeholder="Initial password (10+ chars)" required minLength={10} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <button className="h-9 rounded-lg bg-accent px-4 text-sm font-semibold text-canvas hover:bg-accent-hover">Add user</button>
      </form>
    </div>
  );
}
