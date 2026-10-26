import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderAs, reply } from "./helpers.jsx";

/**
 * Smoke tests: every page renders without crashing for a first-time user (no data, no models, nothing scanned)
 * and for the happy path where the API returns minimal data. A render crash would show the error boundary text.
 */
const noCrash = () => expect(screen.queryByText(/this page failed to render/i)).not.toBeInTheDocument();
const FC_OPTIONS = { stores: [{ id: 1, name: "Bengaluru Indiranagar", city: "Bengaluru" }], items: [{ id: 1, sku: "SKU-1", name: "Phone", category: "Consumer Tech" }], categories: ["Consumer Tech"], horizons: [7, 30, 90] };
const IDLE_STEPS = ["Multi-Source Upload", "Schema Mapping", "Clean & Validate", "Feature Engineering"].map((label, i) => ({ key: `s${i}`, label, status: "pending" }));

describe("pages for a brand-new installation (nothing processed yet)", () => {
  it("Dashboard welcomes the user and points to the next step", async () => {
    renderAs("Admin", "/", { "/api/dashboard/summary": { ready: false }, "/api/forecast/options": FC_OPTIONS });
    expect(await screen.findByText(/welcome to decisioniq/i)).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("link", { name: /data sources/i })).toBeInTheDocument();
    noCrash();
  });

  it("Data Sources shows the four pipeline steps", async () => {
    renderAs("Admin", "/data-sources", { "/api/pipeline/status": { status: "idle", steps: IDLE_STEPS } });
    expect(await screen.findByRole("heading", { name: /data sources & pipeline configuration/i })).toBeInTheDocument();
    expect(await screen.findByText("Schema Mapping")).toBeInTheDocument();
    noCrash();
  });

  it("Forecasting explains that no models exist yet and offers training to those allowed", async () => {
    renderAs("Manager", "/forecasting", { "/api/forecast/options": FC_OPTIONS, "/api/forecast/models": { available: false }, "/api/forecast/train-status": { status: "idle", steps: [] } });
    expect(await screen.findByText(/no trained models yet/i)).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("button", { name: /^train models$/i })).toBeEnabled();
    noCrash();
  });

  it("Forecasting: an Analyst cannot start training", async () => {
    renderAs("Analyst", "/forecasting", { "/api/forecast/options": FC_OPTIONS, "/api/forecast/models": { available: false }, "/api/forecast/train-status": { status: "idle", steps: [] } });
    expect(await screen.findByRole("button", { name: /^retrain models$/i })).toBeDisabled();
  });

  it("Forecasting States shows the live empty state and every state card", async () => {
    renderAs("Admin", "/forecasting/states", {
      "/api/pipeline/status": { status: "idle", steps: IDLE_STEPS }, "/api/pipeline/diagnostics": { status: "idle", failed: false, log: "", steps: [] },
      "/api/forecast/train-status": { status: "idle", steps: [] }, "/api/forecast/models": { available: false },
    });
    expect(await screen.findByText(/state 01 \/\/ idle — no data/i)).toBeInTheDocument();
    expect(screen.getByText(/state 02/i)).toBeInTheDocument();
    expect(screen.getByText(/state 03 \/\/ no faults/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /preview example/i })).toHaveLength(4);
    noCrash();
  });

  it("Risk invites the first scan", async () => {
    renderAs("Manager", "/risk", {
      "/api/risk/summary": { open_alerts: 0, high_open: 0, high_exposure: 0, total_alerts: 0, scanned: false, metrics: null }, "/api/risk/alerts": { total: 0, page: 1, page_size: 8, alerts: [] },
      "/api/risk/timeline": [], "/api/risk/scan-status": { status: "idle", steps: [] },
    });
    expect(await screen.findByText(/no scan yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run scan/i })).toBeEnabled();
    noCrash();
  });

  it("Recommendations invites the first generation", async () => {
    renderAs("Manager", "/recommendations", { "/api/recommendations/summary": { counts: {}, total: 0, by_kind: {} }, "/api/recommendations": { recommendations: [] } });
    expect(await screen.findByText(/no recommendations yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate recommendations/i })).toBeEnabled();
    noCrash();
  });

  it("Explainability reports why it cannot explain anything yet", async () => {
    renderAs("Admin", "/explainability", {
      "/api/forecast/options": FC_OPTIONS, "/api/explain/options": () => reply({ detail: "No trained models - train the forecasting models first" }, 409),
      "/api/explain/global": () => reply({ detail: "x" }, 409), "/api/explain/governance": () => reply({ detail: "x" }, 409),
    });
    expect(await screen.findByText(/no trained models - train the forecasting models first/i)).toBeInTheDocument();
    noCrash();
  });

  it("What-If renders its levers even before a simulation is available", async () => {
    renderAs("Analyst", "/what-if", {
      "/api/forecast/options": FC_OPTIONS, "/api/simulate/scenarios": { scenarios: [] },
      "/api/simulate/baseline": () => reply({ detail: "Train the forecasting models first" }, 409), "POST /api/simulate/run": () => reply({ detail: "Train the forecasting models first" }, 409),
    });
    expect(await screen.findByRole("heading", { name: /scenario & sensitivity simulator/i })).toBeInTheDocument();
    expect(screen.getAllByRole("slider").length).toBeGreaterThanOrEqual(4);
    expect(await screen.findByText(/train the forecasting models first/i)).toBeInTheDocument();
    noCrash();
  });

  it("Reports lists the templates and an empty ledger", async () => {
    renderAs("Analyst", "/reports", {
      "/api/reports/templates": { templates: [{ key: "risk_dossier", title: "Risk & Forensic Audit Dossier", group: "Audit & Compliance", description: "d", last_run: null, runs: 0 }], formats: ["pdf"] },
      "/api/reports": { total: 0, page: 1, page_size: 8, storage_bytes: 0, reports: [] },
      "/api/settings": { config: { reports: { cadence: "Weekly", email: true, slack: true, erp_sftp: false, pdf: true, xlsx: true, json_stream: false } } },
    });
    expect(await screen.findByRole("heading", { name: "Risk & Forensic Audit Dossier" })).toBeInTheDocument();
    expect(await screen.findByText(/no reports yet/i)).toBeInTheDocument();
    noCrash();
  });
});

describe("dashboard with data", () => {
  const SUMMARY = {
    ready: true, as_of: "2017-12-31", kpis: { units_30d: 671710, units_prev_30d: 923821, growth_pct: -27.3, forecast_30d: 628053, forecast_growth_pct: -6.5 },
    model: { serving: "XGBoost", version: "v", mape: 13, r2: 0.92, wape: 11 }, regions: [{ city: "Bengaluru", stores: 4, actual: 295076, forecast: 275440, share_pct: 43.9 }],
    inventory: { total_skus: 500, stock_value: 1024624856, buckets: { "Low stock (<3 days)": 46, "Healthy (3-45 days)": 416, "Overstock (>45 days)": 38 } },
    attention: [{ id: 1, alert_id: "ALT-0001", type: "demand_drop", severity: "High", amount: 850495, store: "Bengaluru Koramangala", item: "Phone", explanation: "Billed units stayed far below baseline", date: "2017-12-01" }],
    open_alerts: 737, high_exposure: 119574705, stockout_risk: { series: 24, reorders: 24 }, pending_recs: 49,
    recommendations: [{ id: 5, kind: "reorder", title: "Reorder 603 units of Phone", detail: "d", impact_inr: 13858046, impact_label: "protected revenue", confidence: 0.93 }],
  };
  const SERIES = { history: [{ date: "2017-12-30", actual: 100 }], forecast: [{ date: "2018-01-01", yhat: 90, lower: 70, upper: 110 }], backtest: [], summary: { model: "XGBoost" } };

  it("shows KPIs, the alert, the recommendation and inventory health", async () => {
    renderAs("Manager", "/", { "/api/dashboard/summary": SUMMARY, "/api/forecast/options": FC_OPTIONS, "/api/forecast/series": SERIES });
    expect(await screen.findByText("6,71,710")).toBeInTheDocument(); // Indian digit grouping
    expect(screen.getByText("737")).toBeInTheDocument();
    expect(screen.getByText(/billed units stayed far below baseline/i)).toBeInTheDocument();
    expect(screen.getByText("Reorder 603 units of Phone")).toBeInTheDocument();
    expect(await screen.findByTestId("chart-line")).toBeInTheDocument();
    expect(screen.getByTestId("chart-doughnut")).toBeInTheDocument();
    noCrash();
  });

  it("an Analyst sees recommendations but cannot approve them from the dashboard", async () => {
    renderAs("Analyst", "/", { "/api/dashboard/summary": SUMMARY, "/api/forecast/options": FC_OPTIONS, "/api/forecast/series": SERIES });
    expect(await screen.findByRole("button", { name: /^approve$/i })).toBeDisabled();
  });

  it("shows an error with retry when the dashboard cannot load", async () => {
    let n = 0;
    renderAs("Admin", "/", { "/api/dashboard/summary": () => (++n === 1 ? Promise.reject(new TypeError("offline")) : SUMMARY), "/api/forecast/options": FC_OPTIONS, "/api/forecast/series": SERIES });
    expect(await screen.findByText(/backend unreachable/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument());
  });
});
