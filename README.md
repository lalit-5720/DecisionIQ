# DecisionIQ – Decision Intelligence & Predictive Analytics

A web platform that turns business data into **forecasts → risk alerts → recommended actions → explanations**, with dashboards, reports, role-based access and an audit trail.
Built for the MCA project *Application-Based Business Decision Intelligence Integrated with Predictive Analytics System* (retail scenario: 10 stores × 50 products).

| Module | What it does | Where |
|---|---|---|
| Data pipeline | Upload CSV/XLSX/Parquet, map columns, clean, engineer 12 features | `backend/app/pipeline` |
| Forecasting | Benchmarks XGBoost, Prophet, SARIMA, LSTM; 90-day forecasts with confidence bands | `backend/app/forecasting` |
| Risk & anomalies | Isolation Forest + autoencoder + Z-score voting; alert ledger and forensic trace | `backend/app/risk` |
| Recommendations | Reorder, inter-store transfer, markdown, budget shift – each with a calculation trail | `backend/app/recommend` |
| What-if simulator | Monte Carlo demand + inventory simulation with price/marketing/stock levers | `backend/app/simulate` |
| Explainability | Exact TreeSHAP, PDP/ICE, drift and fairness checks | `backend/app/explain` |
| Reports | PDF / Excel / JSON dossiers with SHA-256 checksums | `backend/app/reports` |
| Security | JWT login, Admin/Manager/Analyst roles, hash-chained audit log | `backend/app/auth`, `app/platform` |
| UI | React + Vite + Tailwind + Chart.js, 10 screens, responsive | `frontend/` |

**Results at a glance** (details in [docs/results/EVALUATION.md](docs/results/EVALUATION.md)): forecast MAPE 13.0% per series-day / 3.6% on chain totals (best naive baseline 24.5%);
anomaly ensemble precision/recall/F1 0.67/0.70/0.68 on injected anomalies; 79 backend + 39 frontend tests passing.

> **Honest scope.** Only the daily sales are real (Kaggle). Prices, costs, inventory, logistics costs, the festival calendar and every anomaly label are **synthetic**, and several response
> parameters (elasticities, write-off rates, marketing share) are assumptions. See [docs/report/OBJECTIVES_TRACEABILITY.md](docs/report/OBJECTIVES_TRACEABILITY.md).

## Quick start

You need the dataset first: download **train.csv** of the Kaggle *Store Item Demand Forecasting Challenge* and put it in `data/raw/train.csv` (it is not redistributed with this project).

### Option A – Docker (one command)
```bash
docker compose up --build
```
Then open **http://localhost:8080** (API and docs: http://localhost:8000/docs).
The first start runs `python -m app.bootstrap` in a `bootstrap` container: synthetic data, features, model training (≈2–5 min), anomaly scan, recommendations and demo users. Later starts skip finished steps.
Copy `.env.example` to `.env` to change the demo password or JWT secret. The images are large (TensorFlow); allow ~6 GB of disk and 4 GB of memory.

### Option B – Local, one command (Windows PowerShell)
```powershell
.\scripts\demo.ps1          # creates .venv, installs, bootstraps, starts API :8000 and frontend :5173
```
Linux/macOS/Git Bash: `./scripts/demo.sh`.

### Option C – Manual
```bash
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.bootstrap                                  # builds data, models, alerts, recommendations, users
uvicorn app.main:app --reload                            # http://localhost:8000/docs

cd ../frontend && npm install && npm run dev             # http://localhost:5173
```

### Check that it works
```bash
python scripts/smoke_test.py                             # 23 end-to-end checks against http://localhost:8000
python scripts/smoke_test.py --base http://localhost:8080   # same, through the Docker nginx front end
```

## Sign-in and roles
Three demo accounts are created on first start: Admin `rajesh.nair@sunrisemart.in`, Manager `priya.sharma@sunrisemart.in`, Analyst `anil.kumar@sunrisemart.in`.
They share the demo password set by `DIQ_DEMO_PASSWORD` (default in `.env.example`) – **change it** or create real users in *Settings → Users* before exposing the app.

| Role | Can do |
|---|---|
| Analyst | view everything, upload data, run what-if scenarios, generate reports |
| Manager | + approve recommendations and alerts, run scans and retraining, edit inventory rules, view the audit trail |
| Admin | + change risk thresholds and compliance settings, manage users |

The API enforces this on every request (JWT bearer token; the role is read from the database, not the token). Repeated failed sign-ins are throttled.

## Configuration (environment variables, prefix `DIQ_`)
| Variable | Meaning | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL | SQLite file (`decisioniq.db`; `data/decisioniq.db` in Docker). MySQL via `pymysql` is untested |
| `JWT_SECRET` | token signing secret | generated once into `data/.jwt_secret` |
| `TOKEN_HOURS` | token lifetime | 8 (30 days with "remember this workstation") |
| `DEMO_MODE` | show demo role tabs on the login page | `true` |
| `DEMO_PASSWORD` | demo accounts' password (first start only) | see `.env.example` |
| `DATA_DIR`, `CORS_ORIGINS` | data folder, allowed browser origins | `./data`, `http://localhost:5173` |

## Project layout
```
backend/   FastAPI app (app/api routes, pipeline, forecasting, risk, recommend, simulate, explain, reports, auth, platform, bootstrap) + 78 tests
frontend/  React app (src/pages, src/components, src/test) + 39 tests
ml/        prepare_data.py – generates the synthetic data around the real sales (seeded)
data/      raw/ (you provide train.csv), processed/ (generated), reports/, uploads/ – git-ignored
docker/    Dockerfiles + nginx.conf      scripts/   demo.ps1, demo.sh, smoke_test.py
docs/      design/ (UI mock-ups), results/ (evaluation), report/ (chapters 4-5 draft, traceability), ARCHITECTURE.md (diagrams)
```

## Testing and evaluation
```bash
cd backend && pytest                                  # 78 tests (+ `pytest -m slow` trains all models end to end)
cd frontend && npm test                               # 39 tests (Vitest + Testing Library)
cd backend && python -m app.evaluation.report --with-tests   # regenerates docs/results/ (tables, figures, EVALUATION.md)
```
Full evaluation: [docs/results/EVALUATION.md](docs/results/EVALUATION.md). Usability-study template: [docs/results/usability_questionnaire.md](docs/results/usability_questionnaire.md).

## Documentation
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – layered architecture, DFDs, ER diagram, sequence diagrams (Mermaid)
- [docs/report/CHAPTER_4_Findings_and_Results.md](docs/report/CHAPTER_4_Findings_and_Results.md), [CHAPTER_5](docs/report/CHAPTER_5_Conclusion_and_Recommendations.md) – report drafts
- [docs/report/OBJECTIVES_TRACEABILITY.md](docs/report/OBJECTIVES_TRACEABILITY.md) – objectives vs implementation, deviations from the proposal, assumptions, screen mapping
- [TODO.md](TODO.md) – phase-by-phase log of what was built, what was not, and known limits

## Known limitations
No scheduler (retraining, scans and report delivery are manual / stored configuration only); batch rather than real-time anomaly detection; file ingestion only (no DB/ERP connectors);
SQLite single-node database; stateless JWTs (no server-side revocation); no SSO; recommendation quality and usability not yet validated with real users or outcomes.

## Troubleshooting
- *Bootstrap says `data/raw/train.csv` is missing* – download it from Kaggle as described above.
- *Windows: TensorFlow "DLL load failed"* – expected if numpy/pandas are imported first; the app already runs the LSTM in its own process. Install the Microsoft Visual C++ Redistributable if it still fails.
- *Port in use* – change the left side of the `ports:` mappings in `docker-compose.yml`, or the `--port` of uvicorn / `server.port` in `frontend/vite.config.js`.
- *Linux bind mount permission errors in Docker* – the containers run as UID 1000: `sudo chown -R 1000:1000 data`.
