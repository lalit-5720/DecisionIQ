import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "../App.jsx";
import { AuthProvider } from "../auth.jsx";

export const USERS = {
  Admin: { id: 1, name: "Rajesh Nair", email: "rajesh.nair@sunrisemart.in", role: "Admin", capabilities: ["approve_actions", "manage_users", "modify_thresholds", "run_analysis", "upload_data", "view", "view_audit"] },
  Manager: { id: 2, name: "Priya Sharma", email: "priya.sharma@sunrisemart.in", role: "Manager", capabilities: ["approve_actions", "run_analysis", "upload_data", "view", "view_audit"] },
  Analyst: { id: 3, name: "Anil Kumar", email: "anil.kumar@sunrisemart.in", role: "Analyst", capabilities: ["upload_data", "view"] },
};

export const STATUS = { steps: [{ key: "data", label: "Data uploaded", ok: true, detail: "sales.csv" }], healthy: true, synced_at: new Date().toISOString(), open_alerts: 3, high_alerts: 2, pending_recs: 4, data_range: ["2013-01", "2018-03"] };

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/**
 * Install a fake API. `routes` maps "METHOD /api/path" (or just "/api/path" for GET) to a body or a function(url, init) -> body | Response.
 * The longest matching path prefix wins; anything unmatched is a 404 so missing mocks are visible. Returns the list of calls.
 */
export function mockApi(routes = {}) {
  const calls = [];
  globalThis.__mockFetch = vi.fn(async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    const method = (init.method || "GET").toUpperCase();
    const path = url.split("?")[0];
    calls.push({ method, url, init });
    const keys = Object.keys(routes).filter((k) => {
      const [m, p] = k.includes(" ") ? k.split(" ") : ["GET", k];
      return m === method && path.startsWith(p);
    });
    if (!keys.length) return json({ detail: `not mocked: ${method} ${path}` }, 404);
    const best = keys.sort((a, b) => b.length - a.length)[0];
    const v = routes[best];
    const out = typeof v === "function" ? await v(url, init) : v;
    return out instanceof Response ? out : json(out);
  });
  return calls;
}

export const reply = (body, status) => json(body, status);

/** Render the whole app at `path` as a signed-in user (token in sessionStorage + /api/auth/me). */
export function renderAs(role, path, routes = {}) {
  if (role) sessionStorage.setItem("diq_token", `test-token-${role}`);
  const calls = mockApi({ "/api/auth/me": USERS[role], "/api/dashboard/status": STATUS, "/api/auth/logout": { status: "signed out" }, ...routes });
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
  return { ...view, calls };
}
