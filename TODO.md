# DecisionIQ – Project TODO

Source: 4 Word docs + PPT (Business Decision Intelligence + Predictive Analytics, MCA 25MCA604) and 10 Stitch screens
(Login, Dashboard, Data Sources, Forecasting, Forecasting States, Risk & Anomalies, Recommendations, What-If, Explainability, Reports, Settings).
Stack from docs: Python 3.11, FastAPI, Pandas/NumPy/SQLAlchemy, Scikit-learn/XGBoost/Statsmodels/Prophet, TensorFlow/Keras (LSTM), SHAP/LIME, React + Plotly/Chart.js, MySQL (+ MongoDB), Docker, Git.
Design: dark theme, Inter font, cyan `#00A1DA` / violet `#8B7CF6`, INR formatting (₹12,45,000) – see `decisioniq/DESIGN.md`.

## Phase 0 – Setup
- [ ] `git init`, branch strategy (not done yet)
- [x] .gitignore, README
- [x] Folder layout: `backend/`, `frontend/`, `ml/`, `data/`, `docs/`, `docker/`
- [x] Python venv + `requirements.txt` (backend tests pass); Node + Vite React + Tailwind v4 (build passes)
- [x] `docker-compose.yml` (api, web, MySQL) – written, not yet run (Docker not tested)
- [x] Screens/DESIGN.md in `docs/design/`; Tailwind theme tokens in `frontend/src/index.css`
- [x] Dataset: Kaggle Store Item Demand (10 stores x 50 items, 2013-2017, date/store/item/sales) in `data/raw/`
- [ ] Decide how to adapt UI to it (10 stores/50 items instead of 12 Karnataka stores; no price/inventory/finance columns)

## Phase 1 – Data (needed before any model)
- [x] Dataset: real Kaggle sales (913,000 rows, 10 stores x 50 items, 2013-2017) kept untouched in `sales`
- [x] `ml/prepare_data.py` (seeded): store/item masters, list price, promos, festival calendar, inventory (s,S policy), logistics costs
- [x] Labelled anomalies injected into billed columns only: 199 duplicate billing, 150 margin erosion, 598 demand-drop days, 40 logistics cost spikes
- [x] Festival calendar (approximate dates). Weather table: skipped (no real source)
- [x] DB models (`backend/app/db/models.py`) + loader `python -m app.db.load_data --reset`; 6 tests pass. Alembic not added (create_all for now)
- [ ] Add `/api/...` endpoints for stores, items, sales series (needed by dashboard)

## Phase 2 – Ingestion & preprocessing pipeline (Data Sources screen)
- [x] Upload API `/api/pipeline/upload`: CSV / XLSX / Parquet, 250MB cap, alias-based column detection
- [ ] DB connectors (MySQL live, MongoDB catalog, ERP/SAP stub "offline")
- [x] Schema/column mapping + per-column validity % (`pipeline/schema.py`)
- [x] Cleaning (`pipeline/clean.py`): exact + key duplicates, date-gap fill, interpolation imputation (not MICE/KNN), IQR x3 capping
- [x] Quality score (0-100) + stats; real data: 913,000 rows, score 100, 3 outliers capped
- [x] Features (`pipeline/features.py`): lag_7, lag_30, rolling mean/std 14, calendar + month sin/cos, festival_flag, promo_flag; no look-ahead (tested). weather/category_affinity/custom feature not done
- [x] 4-step state, `/status`, `/run` (background), `/preview`; full pipeline runs in ~3s; writes `data/processed/features.parquet`
- [ ] Export config, auto-sync schedule
- [x] Schema-gate failure surfaced as pipeline exception (API + UI); diagnostic log download not done
- [x] Frontend Data Sources page (stepper, upload, quality, mapping, features, preview) - builds, not yet viewed in browser

## Phase 3 – Forecasting engine
- [x] XGBoost (global, recursive), Prophet, SARIMA (baseline), LSTM (Keras, runs in a subprocess because of a TensorFlow/numpy DLL import-order issue on this machine). DeepAR skipped
- [x] Forecast by store / category / product, horizons 7/30/90 days (daily only; weekly granularity not done)
- [x] Holdout = last 90 days (not 80/20), MAE/RMSE/MAPE/WAPE/R², auto-select best. Results on 20-series sample: XGBoost 12.3% (selected), LSTM 12.4%, Prophet 13.4%, SARIMA 23.8%. XGBoost on all 500 series: MAPE 13.0% daily per series, 3.6% on daily chain total
- [x] 95% bands from per-series backtest residuals (approximate); sparse-SKU fallback not done
- [x] Artifacts + version in `data/processed/models/`; "Retrain Models" job with progress (`/api/forecast/retrain`, full run ~2 min). TreeSHAP step not done (XGBoost gain importance for now - Phase 6)
- [ ] Scheduled retraining (weekly Sun 02:00), candidate promotion rule (MAPE delta > 0.5%)
- [x] Forecast CSV export (Excel not done); schedule table with simple drivers; Forecasting page built (Chart.js) - builds, not viewed in browser
- [ ] Forecasting States screen (empty / failure / low-confidence variants)
- Note: forecasts cover 2018-01-01 to 2018-03-31 (day after the data ends)

## Phase 4 – Risk & anomaly detection
- [x] Isolation Forest + autoencoder (sklearn MLP 8-3-8, not Keras) + Z-score rules; ensemble = at least 2 of 3 detectors (`backend/app/risk/`)
- [x] Types: duplicate billing, abnormal demand drop, margin erosion, logistics cost spike (weekly Z-score). Refund clusters not done; duplicate detection is statistical (no invoice-hash matching, data is daily)
- [x] Score 0-1 (rank-based), severity relative to ledger (top 15% exposure = High), status Open / In Review / Resolved / False Positive, statuses survive re-scans
- [x] Evaluation vs injected labels (ensemble, row level): precision 0.67, recall 0.70, F1 0.68; 79% of events caught; alert precision 0.57; cost spikes F1 0.67. IsolationForest alone is weak (F1 0.09), autoencoder 0.57, Z-score 0.43 (numbers changed slightly after the data was regenerated in Phase 5)
- [x] API `/api/risk/` (summary, alerts, alert detail, timeline, PATCH status, scan, scan-status); Risk & Anomalies page (KPIs, timeline, ledger, forensic trace, detector comparison) - checked in browser, no console errors
- [x] Actions: Investigate, Resolve, False positive. Not done: "Resolve & Refund", assign dropdown in UI (API supports assignee), audit logging
- [ ] Tunable sensitivity in UI (scan accepts contamination and z_threshold via API; Settings screen is Phase 8)
- [ ] Tune/improve detectors (IsolationForest underperforms; duplicate recall 58%)

## Phase 5 – Recommendation engine
- [x] Engine (`backend/app/recommend/engine.py`): reorder (order-up-to level with safety stock, expected-shortage impact), inter-store transfer (nearest donor with surplus), dynamic markdown (elasticity + shelf-life/write-off model), budget reallocation (expected-return index). Bundle cross-sell not done
- [x] Inputs: forecasts + stock on hand/on order + prices/costs. Risk alerts are not used as an input yet. Output: impact in INR, confidence, run-out days
- [x] Calculation audit trail per recommendation (shown in the UI)
- [x] Approve / Dismiss / Edit quantity or discount (recomputes impact) / bulk approve / CSV plan export (no PDF); Pending/Approved/Dismissed tabs; decisions survive regeneration
- [x] KPI tiles; API `/api/recommendations/` (summary, list, generate, PATCH, bulk, export.csv); Recommendations page checked in browser. 30 backend tests pass
- Assumptions NOT in the data (all in `Params`): 3-day lead time, 95% service level, price elasticities per category, shelf life and write-off rates, 25% carrying cost, marketing budget = 2.5% of revenue, placeholder ROAS (no ad-spend data). State these in the report
- Data change: `ml/prepare_data.py` now also writes `on_order` and creates a last-day scenario (8% of series with excess stock, 10% with a delayed delivery). Real sales unchanged
- [ ] Use risk alerts as an input (e.g. hold PO on suspicious billing); bundle cross-sell

## Phase 6 – Explainability
- [x] Exact TreeSHAP via XGBoost `pred_contribs` (not the `shap` package, no LIME): local per store/product/date (history or forecast day, recursion replayed so it equals the Forecast page number) and global mean |SHAP|
- [x] Waterfall bridge (base to prediction, balance verified), contribution % / raw SHAP bars, plain-language summary and 4 driver-group cards (template-based text, not an LLM)
- [x] PDP + ICE for chosen features. NOT a price-elasticity curve: price is not a model input (elasticity assumptions live in the recommendation engine)
- [x] Governance: error parity across stores (backtest WAPE spread), PSI drift (last 90 days vs earlier; partly seasonal), last retrained, model artifact sha256 (not a git commit)
- [x] API `/api/explain/` (options, local, global, dependence, governance, export.csv); Explainability page checked in browser; 37 backend tests pass
- [ ] Export SHAP as PDF (CSV only), LIME, "Quick audit" links to alerts/recommendations, explanations for non-XGBoost serving models (API returns 409)

## Phase 7 – What-if simulator
- [x] Levers: price (-20..+20%), festive voucher (0-30%), marketing push (Low/Medium/High = +0/+15/+35% budget), safety stock target, supplier lead time (1-21 days); shocks: festival spike (+45% for 7 days) and competitor price match (-5%)
- [x] Monte Carlo (`backend/app/simulate/engine.py`): per series/day demand = forecast x price response (category elasticity, sampled uncertainty) x marketing x shocks, plus an inventory policy with lead time and safety stock, so stock-outs emerge. Baseline and scenario share random draws. Live preview 250 runs, button 1,000 runs; all 500 series x 30 days takes about 1 second
- [x] Outputs: revenue, volume (p10-p90), gross margin, net profit (after marketing and holding cost), daily stock-out probability, elasticity index, safety buffer days, P90 peak, store footprint, verdict text. Trajectory views: daily units with band, cumulative revenue, stock-out %
- [x] Saved scenarios (DB `scenarios` table): save, list, delete, load back into the levers, side-by-side comparison table (first 4)
- [x] API `/api/simulate/` (baseline, run, scenarios); What-If page checked in browser; 45 backend tests pass
- Assumptions NOT in data: elasticities (shared with Phase 5), marketing elasticity 0.10, marketing budget 2.5% of revenue, 25% carrying cost, shock sizes taken from the screen mockup. Stock-out risk = share of series-days with a stock-out (not "any stock-out in 30 days")
- [ ] "Deploy to ERP" (no ERP exists), comparison picker for choosing which scenarios to compare, scenario-level confidence intervals on revenue

## Phase 8 – Dashboard, reports, settings
- [x] App shell: top bar with global search (Ctrl K; products, stores, alerts, pages), data-range chip, alert bell, user chip; pipeline status strip; sidebar badges; mobile drawer. User chip is static "Priya Sharma, Manager" until Phase 9
- [x] Dashboard: KPIs (units last 30 days, forecast next 30, stock-out risk, open alerts), actual-vs-forecast chart (category/store scope, 7D/30D/90D), attention list, top recommendations with inline Approve/Dismiss, demand by city, inventory health donut. No revenue or budget KPIs (the data has no revenue baseline/budget); "this month" is last 30 days
- [x] Reports: 3 templates (forecast summary, risk dossier, replenishment plan) generated as real PDF (reportlab), multi-sheet XLSX and JSON from live data; ledger with SHA-256, size, filters, download. No "Executive board deck" or what-if export template
- [x] Report delivery config (cadence, channels, formats) saved - NOT executed: no scheduler, email, Slack or SFTP integration exists
- [x] Settings: RBAC matrix (display only until Phase 9), anomaly thresholds and inventory rules that really change the next scan / next recommendation run, retraining + compliance settings (stored only, labelled), reset to defaults
- [x] Audit trail: hash-chained log of data uploads, pipeline/scan/retrain starts, alert and recommendation decisions, settings changes, reports, scenarios; tamper check endpoint (`/api/audit/verify`) tested by rewriting a row
- [x] Tests: 55 backend tests (conftest isolates the DB); all 9 pages checked in browser at least once
- Bug found and fixed: `Anomaly.end_date` was NOT NULL because `date` shadowed the type inside the model class
- [ ] Scheduled retraining/report jobs, real delivery channels, PDF charts with date axis, "Export Data Governance Policy (PDF)", pagination of ledger sorting

## Phase 9 – Auth & security
- [x] Login (`/api/auth/login`) with scrypt-hashed passwords, JWT (8 h, or 30 days with "remember"), `/me`, logout, change password; every other API route requires a valid token; deactivated users are rejected immediately; role comes from the DB, not the token (forged-role test)
- [x] RBAC in the API (`backend/app/auth/permissions.py`): Analyst = view + upload; Manager = + approve actions, run scans/retraining, inventory & report settings, audit view; Admin = + risk/compliance settings and user management. 403 with a clear message otherwise
- [x] UI: login page, route guard, real user chip + sign out, buttons disabled and settings sections read-only by role, audit/users panels by role; authenticated file downloads
- [x] Users admin (Admin only): create, change role, deactivate/reactivate, reset password; cannot remove the last Admin or deactivate yourself
- [x] Audit trail now records the real user and IP; failed/blocked sign-ins are logged; login throttling (5 failures per 10 minutes per email)
- [x] PII hashing/retention: setting stored only (the data holds no PII). Input validation via pydantic. Secrets via env or generated file
- [x] 70 backend tests incl. 14 auth tests; browser-checked as Analyst (read-only) and Admin
- Known limits: JWT is stateless (no server-side revocation before expiry, sign-out only clears the browser copy); tokens live in browser storage (XSS would expose them); in-memory login throttle resets on restart and is per process; no HTTPS/CSRF concerns handled here (bearer header, not cookies); Google/Microsoft SSO buttons are disabled placeholders; no per-store assignment; one shared demo password
- [ ] Refresh tokens / revocation list, 2FA, password complexity rules, HTTPS reverse proxy for deployment

## Phase 10 – Frontend polish
- [x] Responsive: desktop full sidebar (260px), tablet icon-only rail (72px, 768-1279), mobile drawer; audited every page at 375, 768 and desktop widths for horizontal overflow (found and fixed 4 mobile overflows); tables scroll inside their cards
- [x] Shared states (`components/ui.jsx`): skeleton loaders, error box with retry, empty state, error boundary per page (a crashing chart no longer blanks the app), toasts for network failures / 5xx / 403
- [x] Forecasting States page (`/forecasting/states`): the four variants from the screen (empty, training with progress, pipeline exception with diagnostic log + retry/inspect/download, low confidence with widened band and category-average prior). Each card shows the LIVE condition; "Preview example" shows the variant when it is not active
- [x] Backend: `/api/forecast/low-confidence`, `/api/pipeline/diagnostics`; 72 tests pass
- [x] Accessibility basics: skip link, visible focus ring, aria labels/titles on icon controls, reduced-motion support, per-page document titles. Not audited with a screen reader or axe
- [x] Recovery policy is honest: failed runs stop and keep previous models; retries are manual (no retry/back-off daemon)
- Incident: a scripting mistake truncated `Forecasting.jsx` to 0 bytes; it was rebuilt from the earlier version (all features re-added) and every frontend file was checked for size afterwards
- [ ] Automated frontend tests (none yet), dark/light theme, i18n, real screenshots for the report

## Phase 11 – Testing & evaluation
- [x] `python -m app.evaluation.report` regenerates `docs/results/EVALUATION.md`, 12 CSV tables and 5 figures from the trained artifacts
- [x] Forecast: XGBoost 13.0% MAPE per series-day (target 10-15%), 3.6% on chain totals, R2 0.92 on all 500 series; best naive baseline 24.5% (so 47% lower). Bias is negative (-1.8% in days 1-30, -4.9% in days 61-90) - reported, not hidden. Error is similar across stores and categories
- [x] Anomaly: ensemble P/R/F1 0.67/0.70/0.68 on synthetic labels, per-type recall, sensitivity sweep (z threshold 3.5-4 would give F1 0.71 - flagged as tuning on the test labels, defaults left unchanged)
- [x] Performance table: cleaning 1.7 s, features 0.8 s, 90-day forecast 0.2 s, API reads 15-60 ms, simulator 0.6 s, scan 14 s, full training 127 s
- [x] Backend: 73 tests incl. the slow training test, 92% line coverage (the report omits the evaluation script and LSTM subprocess); frontend: 39 tests (auth/route guard, permissions per role, error boundary, smoke render of every page with empty data, dashboard with data). A mutation check confirmed the permission tests fail when the gating is removed
- [x] Bug found by the frontend tests and fixed: the Login "Password" label pointed at the "Forgot password?" button instead of the input
- [x] Usability questionnaire template (tasks + SUS) written
- Not done: the user study itself (no participants), end-to-end browser tests (Playwright), recommendation quality evaluation (no ground truth), load testing beyond single-user timings, accessibility audit with a tool
- [ ] Run the usability study with 5-10 people and add the SUS score to the report

## Phase 12 – Deployment & academic deliverables
- [x] `python -m app.bootstrap`: builds everything from `data/raw/train.csv` (synthetic data, features, models, scan, recommendations, demo users), skips finished steps, idempotent; 6 tests
- [x] Docker: backend image (python 3.12, non-root, health check, 3.5 GB because of TensorFlow), frontend image (nginx serving the build, proxying /api, security headers), compose with a one-shot `bootstrap` service that must succeed before the API starts. **Built and run on this machine**: bootstrap, API healthy, web up, `scripts/smoke_test.py` 23/23 through nginx on :8080, login and Risk page checked in the browser
- [x] Bugs found only by running it in Docker and fixed: (1) bootstrap treated the scan as done when old files existed but the new database had no alerts; (2) nginx dropped the security headers in locations that set their own `add_header`
- [x] `scripts/demo.ps1` / `demo.sh` one-command local demo (not executed end to end; its steps are the same as the manual path that was)
- [x] `scripts/smoke_test.py`: 23 end-to-end checks (auth, role restrictions, forecast, alerts, recommendations, SHAP balance, simulation, report checksum, audit chain); also passes against the local dev servers
- [x] README rewritten (quick start A/B/C, roles, configuration, layout, limitations, troubleshooting); `.env.example`; requirements split into runtime and dev
- [x] Report material: `docs/ARCHITECTURE.md` (layered, DFD 0/1, use cases, ER, 2 sequence diagrams, deployment - Mermaid), `docs/report/` chapter 4 and 5 drafts, objectives traceability with deviations, assumptions and screen mapping, `docs/results/` evaluation
- [x] `git init` done (branch main, nothing committed or pushed); `.gitignore` keeps data, models, databases, secrets, node_modules and .venv out (about 150 files would be added)
- Final numbers: 79 backend tests (91% line coverage), 39 frontend tests, forecast MAPE 13.0%, anomaly ensemble F1 0.68
- Not done / for you: the user study, screenshots for the report (take them from the running app), updating the PPT with results, a first commit and push, MySQL (untested), running the Docker stack on Linux (tested on Docker Desktop for Windows only)
