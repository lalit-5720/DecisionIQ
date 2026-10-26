import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const KEY = "diq_token";
export const getToken = () => localStorage.getItem(KEY) || sessionStorage.getItem(KEY);
const clearToken = () => { localStorage.removeItem(KEY); sessionStorage.removeItem(KEY); };
const setToken = (t, remember) => { clearToken(); (remember ? localStorage : sessionStorage).setItem(KEY, t); };

// Error toasts: identical messages are shown at most once every 5 seconds.
let lastNotice = { text: "", at: 0 };
function notify(kind, message) {
  const now = Date.now();
  if (lastNotice.text === message && now - lastNotice.at < 5000) return; // de-duplicate bursts
  lastNotice = { text: message, at: now };
  window.dispatchEvent(new CustomEvent("diq:apierror", { detail: { kind, message } }));
}

// Every /api call carries the bearer token; an expired/invalid session (401) signs the user out;
// 403 and 5xx responses and network failures raise a toast.
let patched = false;
function patchFetch() {
  if (patched) return;
  patched = true;
  const orig = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    const isApi = url.startsWith("/api/");
    const isLogin = url.startsWith("/api/auth/login");
    const token = getToken();
    if (isApi && !isLogin && token) init = { ...init, headers: { ...(init.headers || {}), Authorization: `Bearer ${token}` } };
    return orig(input, init).then((res) => {
      if (isApi && !isLogin && res.status === 401 && token) { clearToken(); window.dispatchEvent(new Event("diq:logout")); }
      else if (isApi && (res.status >= 500 || res.status === 403)) {
        res.clone().json().catch(() => ({})).then((j) => notify(res.status === 403 ? "warn" : "error",
          res.status === 403 ? (typeof j.detail === "string" ? j.detail : "You are not permitted to do this.") : `The server hit an error (${res.status}) on ${url.split("?")[0]}. Please try again.`));
      }
      return res;
    }, (err) => {
      if (isApi) notify("error", "Cannot reach the server. Check your connection and try again.");
      throw err;
    });
  };
}
patchFetch();

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const onLogout = () => setUser(null);
    window.addEventListener("diq:logout", onLogout);
    if (getToken()) {
      fetch("/api/auth/me").then((r) => (r.ok ? r.json() : null)).then(setUser).catch(() => {}).finally(() => setReady(true));
    } else setReady(true);
    return () => window.removeEventListener("diq:logout", onLogout);
  }, []);

  const login = useCallback(async (email, password, remember) => {
    const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password, remember }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Sign-in failed");
    setToken(j.access_token, remember);
    setUser(j.user);
    return j.user;
  }, []);
  const logout = useCallback(async () => {
    try { await fetch("/api/auth/logout", { method: "POST" }); } catch { /* offline: still sign out locally */ }
    clearToken();
    setUser(null);
  }, []);
  const can = useCallback((cap) => !!user?.capabilities?.includes(cap), [user]);
  const value = useMemo(() => ({ user, ready, login, logout, can }), [user, ready, login, logout, can]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// Downloads need the Authorization header, so plain <a href> links cannot be used.
export async function downloadFile(url, fallbackName = "download") {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Download failed (${r.status})`);
  const m = /filename="?([^";]+)"?/.exec(r.headers.get("Content-Disposition") || "");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function DownloadLink({ url, name, className, children }) {
  return <button type="button" className={className} onClick={() => downloadFile(url, name).catch((e) => alert(e.message))}>{children}</button>;
}
