import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";

const ROLES = ["Admin", "Manager", "Analyst"];
const FEATURES = [
  ["Automated demand & festive forecasting", "Multi-model benchmark (XGBoost, Prophet, SARIMA, LSTM) with the best model selected on a held-out backtest."],
  ["Prescriptive actions & explainability", "Every reorder, transfer and markdown lever is backed by exact SHAP attribution and a transparent calculation trail."],
  ["Anomaly guardrails", "Isolation Forest, autoencoder and Z-score detectors vote on duplicate billing, margin erosion, demand drops and cost spikes."],
];

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [personas, setPersonas] = useState([]);
  const [role, setRole] = useState("Manager");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  useEffect(() => {
    fetch("/api/auth/personas").then((r) => r.json()).then((j) => {
      setPersonas(j.personas);
      const p = j.personas.find((x) => x.role === "Manager");
      if (p) setEmail(p.email);
    }).catch(() => {});
  }, []);

  if (user) return <Navigate to={loc.state?.from || "/"} replace />;

  const pick = (r) => { setRole(r); const p = personas.find((x) => x.role === r); if (p) setEmail(p.email); setError(null); };
  const persona = personas.find((x) => x.role === role);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await login(email, password, remember); nav(loc.state?.from || "/", { replace: true }); }
    catch (err) { setError(err.message); setPassword(""); }
    finally { setBusy(false); }
  };
  const input = "h-12 w-full rounded-xl border border-line bg-field px-4 text-sm text-ink placeholder:text-[#5B688A] focus:border-accent focus:outline-none";

  return (
    <div className="grid min-h-screen bg-canvas lg:grid-cols-[1.15fr_1fr]">
      <section className="hidden flex-col justify-between bg-gradient-to-br from-[#0b1a3a] via-[#0b1020] to-[#0b1020] p-12 lg:flex">
        <div>
          <div className="flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-accent to-violet text-lg">📈</div>
            <div><div className="text-2xl font-bold">Decision<span className="text-accent">IQ</span></div><div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted">Enterprise decision intelligence</div></div></div>
          <h1 className="mt-16 text-5xl font-bold leading-tight tracking-tight">From data to decisions.<br /><span className="bg-gradient-to-r from-accent to-ok bg-clip-text text-transparent">Automated.</span> <span className="bg-gradient-to-r from-ok to-violet bg-clip-text text-transparent">Explainable. Auditable.</span></h1>
          <p className="mt-6 max-w-xl text-lg text-muted">DecisionIQ turns sales, inventory and billing data into forecasts, risk alerts and approved actions for multi-store retail teams.</p>
          <div className="mt-10 max-w-xl space-y-3">
            {FEATURES.map(([t, d]) => <div key={t} className="rounded-xl border border-line bg-card/60 p-4"><div className="font-semibold">{t}</div><div className="mt-1 text-sm text-muted">{d}</div></div>)}
          </div>
        </div>
        <div className="mt-10 border-t border-line pt-4 text-xs text-muted">Sunrise Mart tenant · Application-based business decision intelligence with predictive analytics</div>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-12">
        <form onSubmit={submit} className="w-full max-w-md">
          <span className="rounded-lg border border-line bg-card px-3 py-1.5 text-xs text-muted">🔒 Secure sign-in</span>
          <h2 className="mt-5 text-3xl font-bold tracking-tight">Sign in to your console</h2>
          <p className="mt-2 text-sm text-muted">Access Sunrise Mart's demand forecasts and decision controls.</p>

          {personas.length > 0 && (
            <>
              <div className="mt-6 text-sm font-semibold">Access role</div>
              <div className="mt-2 grid grid-cols-3 gap-1 rounded-xl border border-line bg-card p-1" role="tablist">
                {ROLES.map((r) => <button key={r} type="button" role="tab" aria-selected={role === r} onClick={() => pick(r)}
                  className={`h-10 rounded-lg text-sm ${role === r ? "border border-accent/50 bg-accent/10 font-semibold text-ink" : "text-muted hover:text-ink"}`}>{role === r && <span className="mr-1.5 text-accent">●</span>}{r}</button>)}
              </div>
              {persona && <p className="mt-2 text-xs text-muted">Demo account for this role: <b className="text-ink">{persona.name} ({persona.role})</b>. The server decides your role from your account, not from this tab.</p>}
            </>
          )}

          <label className="mt-6 block text-sm font-semibold">Work email
            <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} mt-2 font-normal`} placeholder="you@company.com" /></label>
          <div className="mt-4">
            <div className="flex justify-between text-sm font-semibold">
              <label htmlFor="password">Password</label>
              <button type="button" onClick={() => setNote("Password resets are handled by an Admin: Settings → Users, then Reset password.")} className="font-normal text-accent">Forgot password?</button>
            </div>
            <div className="relative mt-2">
              <input id="password" type={show ? "text" : "password"} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={`${input} pr-16 font-normal`} />
              <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-3 text-xs text-muted" aria-label={show ? "Hide password" : "Show password"}>{show ? "Hide" : "Show"}</button>
            </div>
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 accent-[#00A1DA]" />Remember this workstation (30 days)</label>

          {error && <div role="alert" className="mt-4 rounded-lg border border-risk bg-risk/10 p-3 text-sm text-risk">{error}</div>}
          {note && <div className="mt-4 rounded-lg border border-line bg-card p-3 text-sm text-muted">{note}</div>}

          <button type="submit" disabled={busy} className="mt-6 h-12 w-full rounded-xl bg-gradient-to-r from-accent to-[#0b82b3] font-semibold text-canvas shadow-lg shadow-accent/20 hover:opacity-95 disabled:opacity-60">{busy ? "Signing in…" : "Sign in to Decision Console →"}</button>

          <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wider text-muted"><span className="h-px flex-1 bg-line" />or continue with sso<span className="h-px flex-1 bg-line" /></div>
          <div className="grid grid-cols-2 gap-3">
            {["Google Workspace", "Microsoft Entra ID"].map((s) => <button key={s} type="button" disabled title="SSO is not configured in this deployment" className="h-11 cursor-not-allowed rounded-xl border border-line bg-card text-sm text-muted opacity-60">{s}</button>)}
          </div>
          <p className="mt-6 text-center text-xs text-muted">Need access or a role change? Contact your DecisionIQ administrator.</p>
        </form>
      </section>
    </div>
  );
}
