import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ErrorBoundary } from "./ui.jsx";
import { NAV_ITEMS } from "../nav.js";
import { useAuth } from "../auth.jsx";

const ago = (iso) => {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
};

function Search() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState([]);
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const box = useRef(null);
  const input = useRef(null);

  useEffect(() => {
    if (q.trim().length < 2) return setRes([]);
    const t = setTimeout(() => fetch(`/api/search?q=${encodeURIComponent(q)}`).then((r) => r.json()).then((j) => setRes(j.results)).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.current?.focus(); } };
    const onClick = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    window.addEventListener("keydown", onKey); document.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onClick); };
  }, []);
  const go = (p) => { setOpen(false); setQ(""); nav(p); };

  return (
    <div ref={box} className="relative w-full max-w-md">
      <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => e.key === "Enter" && res[0] && go(res[0].path)} placeholder="Search product, store or alert…  Ctrl K"
        className="h-9 w-full rounded-lg border border-line bg-field px-3 text-sm text-ink placeholder:text-[#5B688A] focus:border-accent focus:outline-none" />
      {open && res.length > 0 && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border border-line-strong bg-[#16203A] shadow-xl">
          {res.map((r, i) => (
            <button key={i} onClick={() => go(r.path)} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-field">
              <span className="truncate">{r.label}</span><span className="ml-2 text-[10px] uppercase text-muted">{r.type}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const [st, setSt] = useState(null);
  const [drawer, setDrawer] = useState(false);
  const nav = useNavigate();
  const { user, logout } = useAuth();
  const loc = useLocation();
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    const label = NAV_ITEMS.find((n) => (n.path === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.path)))?.label;
    document.title = label ? `${label} · DecisionIQ` : "DecisionIQ";
  }, [loc.pathname]);

  useEffect(() => {
    const onErr = (e) => {
      const id = Date.now() + Math.random();
      setToasts((t) => [...t.slice(-2), { id, ...e.detail }]);
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
    };
    window.addEventListener("diq:apierror", onErr);
    return () => window.removeEventListener("diq:apierror", onErr);
  }, []);

  useEffect(() => {
    const load = () => fetch("/api/dashboard/status").then((r) => r.json()).then(setSt).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  const badge = { "/risk": st?.high_alerts, "/recommendations": st?.pending_recs };
  // expanded = full labels (desktop, mobile drawer); otherwise icon-only rail (tablet 768-1279px)
  const sidebar = (expanded) => (
    <>
      <div className={`mb-6 px-2 ${expanded ? "" : "text-center"}`}>
        <div className="text-lg font-bold">{expanded ? <>Decision<span className="text-accent">IQ</span></> : <span className="text-accent">IQ</span>}</div>
        {expanded && <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">Decision Intelligence</div>}
      </div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((n) => (
          <NavLink key={n.path} to={n.path} end={n.path === "/"} onClick={() => setDrawer(false)}
            title={n.label} aria-label={n.label}
            className={({ isActive }) => `relative flex items-center rounded-lg px-3 py-2 text-sm font-medium ${expanded ? "justify-between" : "justify-center"} ${isActive ? "bg-accent text-canvas" : "text-muted hover:bg-card"}`}>
            <span className="flex items-center gap-3"><span aria-hidden className="w-5 text-center">{n.icon}</span>{expanded && n.label}</span>
            {badge[n.path] > 0 && <span className={`rounded-full px-1.5 text-[10px] font-bold ${expanded ? "" : "absolute -right-0.5 -top-0.5"} ${n.path === "/risk" ? "bg-risk text-canvas" : "bg-accent/30 text-accent"}`}>{badge[n.path]}</span>}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto rounded-lg border border-line bg-card px-3 py-2 text-xs text-muted" title={st ? (st.healthy ? "Pipeline healthy" : "Pipeline incomplete") : "Connecting"}>
        <span className={`inline-block h-2 w-2 rounded-full ${st?.healthy ? "bg-ok" : "bg-warn"} ${expanded ? "mr-1.5" : ""}`} />
        {expanded && <>{st ? (st.healthy ? "Pipeline healthy" : "Pipeline incomplete") : "Connecting…"}{st?.synced_at ? ` · synced ${ago(st.synced_at)}` : ""}</>}
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-canvas">Skip to content</a>
      <aside className="sticky top-0 hidden h-screen w-[72px] shrink-0 flex-col bg-nav p-3 md:flex xl:w-[260px] xl:p-4">
        <div className="flex h-full flex-col xl:hidden">{sidebar(false)}</div>
        <div className="hidden h-full flex-col xl:flex">{sidebar(true)}</div>
      </aside>
      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setDrawer(false)}>
          <div className="absolute inset-0 bg-black/50" />
          <aside className="absolute inset-y-0 left-0 flex w-[260px] flex-col bg-nav p-4" onClick={(e) => e.stopPropagation()}>{sidebar(true)}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-canvas/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-2.5 md:px-6">
            <button className="rounded-lg border border-line px-2.5 py-1.5 text-sm md:hidden" onClick={() => setDrawer(true)} aria-label="Open menu">☰</button>
            <Search />
            <div className="ml-auto hidden items-center gap-3 lg:flex">
              <div className="rounded-lg border border-line bg-field px-3 py-1.5 text-xs text-muted">
                {st?.data_range?.[0]?.slice(0, 7) || "…"} → {st?.data_range?.[1]?.slice(0, 7) || "…"} (forecast)
              </div>
            </div>
            <button onClick={() => nav("/risk")} className="relative rounded-lg border border-line px-2.5 py-1.5 text-sm" aria-label="Alerts">
              🔔{st?.high_alerts > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-risk px-1.5 text-[10px] font-bold text-canvas">{st.high_alerts}</span>}
            </button>
            <div className="flex items-center gap-2 text-sm">
              <div className="grid h-8 w-8 place-items-center rounded-full bg-accent/20 text-xs font-bold text-accent">{user?.name?.split(" ").map((w) => w[0]).join("").slice(0, 2)}</div>
              <span className="hidden font-semibold sm:inline">{user?.name}</span>
              <span className="hidden rounded-full bg-accent/20 px-2 py-0.5 text-[10px] font-semibold text-accent sm:inline">{user?.role}</span>
              <button onClick={async () => { await logout(); nav("/login"); }} className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-muted hover:text-ink">Sign out</button>
            </div>
          </div>
          {st && (
            <div className="flex gap-1 overflow-x-auto px-4 pb-2 text-xs md:px-6">
              {st.steps.map((s, i) => (
                <div key={s.key} className="flex shrink-0 items-center gap-1">
                  <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 ${s.ok ? "border-ok/30 text-ok" : "border-line text-muted"}`}>
                    {s.ok ? "✓" : "○"} {s.label}{s.detail ? <span className="text-muted"> · {s.detail}</span> : null}
                  </span>
                  {i < st.steps.length - 1 && <span className="text-muted">›</span>}
                </div>
              ))}
            </div>
          )}
        </header>
        <main id="main" className="min-w-0 flex-1 p-4 md:p-6"><ErrorBoundary key={loc.pathname}><Outlet /></ErrorBoundary></main>
        <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} role="alert" className={`pointer-events-auto rounded-lg border p-3 text-sm shadow-xl ${t.kind === "warn" ? "border-warn/40 bg-[#2a2210] text-warn" : "border-risk/40 bg-[#2a1215] text-risk"}`}>
              <div className="flex items-start justify-between gap-3"><span>{t.message}</span>
                <button onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} className="text-xs opacity-70 hover:opacity-100" aria-label="Dismiss">✕</button></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
