import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderAs } from "./helpers.jsx";

const REC = {
  id: 1, kind: "reorder", kind_label: "Inventory Reorder", title: "Reorder 100 units of Phone for Bengaluru", detail: "Stock covers 2 days", store: 1, item: 1, sku: "SKU-1",
  impact_inr: 125000, impact_label: "protected revenue", confidence: 0.9, status: "Pending", payload: { sku: "SKU-1", qty: 100, runout_days: 2, calc: [["Order-up-to level", "300 units"]] },
};
const recRoutes = () => ({
  "/api/recommendations/summary": { counts: { Pending: 1 }, total: 1, by_kind: { reorder: 1 }, pending_value: 125000, approved_value: 0, avg_confidence: 0.9, execution_rate: null, stockout_risk_series: 1, stockout_risk_stores: 1 },
  "/api/recommendations": { recommendations: [REC] },
  "PATCH /api/recommendations/1": { ...REC, status: "Approved" },
});

describe("recommendations: who can approve", () => {
  it("an Analyst sees the action but cannot approve, edit or generate", async () => {
    renderAs("Analyst", "/recommendations", recRoutes());
    expect(await screen.findByText(REC.title)).toBeInTheDocument();
    expect(screen.getByText(/view only — your role cannot approve actions/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve po/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit quantity/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeDisabled();
  });

  it("a Manager can approve, and the request carries the new status", async () => {
    const { calls } = renderAs("Manager", "/recommendations", recRoutes());
    await userEvent.click(await screen.findByRole("button", { name: /approve po/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.url === "/api/recommendations/1")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(JSON.parse(patch.init.body)).toEqual({ status: "Approved" });
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeEnabled();
  });

  it("shows the calculation audit trail on demand", async () => {
    renderAs("Manager", "/recommendations", recRoutes());
    await userEvent.click(await screen.findByRole("button", { name: /how was this calculated/i }));
    expect(screen.getByText("Order-up-to level")).toBeInTheDocument();
    expect(screen.getByText("300 units")).toBeInTheDocument();
  });
});

const ALERT = { id: 7, alert_id: "ALT-0007", type: "duplicate_billing", type_label: "Duplicate billing", store: 1, store_name: "Bengaluru Indiranagar", item: 1, item_name: "Phone", date: "2017-12-01", end_date: "2017-12-01", amount: 86400, score: 0.99, severity: "High", status: "Open", assignee: null, explanation: "Billed 42 vs 21 expected" };
const riskRoutes = () => ({
  "/api/risk/summary": { open_alerts: 1, high_open: 1, high_exposure: 86400, total_alerts: 1, scanned: true, metrics: { detectors: { Ensemble: { precision: 0.67, recall: 0.7, f1: 0.68, fp: 3 } }, event_recall: 0.79, cost_spike: { precision: 0.6, recall: 0.8, f1: 0.7 } } },
  "/api/risk/alerts/7": { ...ALERT, evidence: { detectors: { ZScore: true } }, distribution: null, window: [] },
  "/api/risk/alerts": { total: 1, page: 1, page_size: 8, alerts: [ALERT] },
  "/api/risk/timeline": [{ id: 7, date: "2017-12-01", amount: 86400, severity: "High", status: "Open", type: "duplicate_billing" }],
  "/api/risk/scan-status": { status: "complete", steps: [] },
});

describe("risk alerts: who can decide", () => {
  it("an Analyst can read the forensic trace but not resolve or scan", async () => {
    renderAs("Analyst", "/risk", riskRoutes());
    expect((await screen.findAllByText("Duplicate billing")).length).toBeGreaterThan(0);
    expect(await screen.findByRole("button", { name: /^resolve$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /re-scan/i })).toBeDisabled();
  });

  it("a Manager can resolve and re-scan", async () => {
    renderAs("Manager", "/risk", riskRoutes());
    expect(await screen.findByRole("button", { name: /^resolve$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /re-scan/i })).toBeEnabled();
  });
});

const CFG = {
  risk: { z_threshold: 3, contamination: 0.0015, auto_suppress_vendor: false, slack_critical_alerts: true },
  inventory: { overstock_cover_days: 45, target_cover_days: 21, max_discount_pct: 20, lead_time_days: 3, service_level_z: 1.65 },
  retraining: { cadence: "Daily at 02:00", promotion_mape_delta: 0.5, holdout_days: 90 }, compliance: { pii_anonymisation: true, retention_months: 36 },
  reports: { cadence: "Weekly", email: true, slack: true, erp_sftp: false, pdf: true, xlsx: true, json_stream: false },
};
const RBAC = [{ key: "view", capability: "View dashboards", admin: true, manager: true, analyst: true }, { key: "manage_users", capability: "Manage users", admin: true, manager: "locked", analyst: false }];
const CAPS = { risk: "modify_thresholds", compliance: "modify_thresholds", inventory: "approve_actions", retraining: "run_analysis", reports: "approve_actions" };
const settingsRoutes = (role, caps) => ({
  "/api/settings": { config: CFG, applied: {}, rbac: RBAC, section_caps: CAPS, user: { name: "X", role, tier: "Enterprise", scope: "All", capabilities: caps } },
  "/api/audit/verify": { ok: true, entries: 4 }, "/api/audit": { total: 0, page: 1, page_size: 8, users: [], categories: [], entries: [] },
  "/api/users": { users: [{ id: 1, name: "Rajesh Nair", email: "r@x.in", role: "Admin", active: true, last_login: null }], roles: ["Admin", "Manager", "Analyst"] },
});

describe("settings: who can change what", () => {
  it("an Analyst gets read-only sections, no audit trail and no user management", async () => {
    renderAs("Analyst", "/settings", settingsRoutes("Analyst", ["view", "upload_data"]));
    expect(await screen.findByRole("heading", { name: /platform settings/i })).toBeInTheDocument();
    expect(await screen.findByText(/your role cannot view the audit trail/i)).toBeInTheDocument();
    expect(screen.queryByText(/users & access/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset to system defaults/i })).toBeDisabled();
    const sliders = screen.getAllByRole("slider");
    expect(sliders.length).toBeGreaterThan(3);
    sliders.forEach((s) => expect(s).toBeDisabled());
  });

  it("a Manager can edit inventory rules but not risk thresholds", async () => {
    renderAs("Manager", "/settings", settingsRoutes("Manager", ["view", "approve_actions", "run_analysis", "view_audit"]));
    await screen.findByRole("heading", { name: /platform settings/i });
    const z = (await screen.findAllByRole("slider"))[0]; // risk: z threshold
    expect(z).toBeDisabled();
    const overstock = screen.getAllByRole("slider").find((s) => s.getAttribute("max") === "120" && s.getAttribute("min") === "15");
    expect(overstock).toBeEnabled();
    expect(screen.queryByText(/users & access/i)).not.toBeInTheDocument();
  });

  it("an Admin sees everything, including user management", async () => {
    renderAs("Admin", "/settings", settingsRoutes("Admin", ["view", "approve_actions", "modify_thresholds", "run_analysis", "manage_users", "view_audit"]));
    expect(await screen.findByText(/users & access/i)).toBeInTheDocument();
    expect((await screen.findAllByText("Rajesh Nair")).length).toBeGreaterThan(1); // header chip + users table
    screen.getAllByRole("slider").forEach((s) => expect(s).toBeEnabled());
  });
});
