# DecisionIQ - architecture and diagrams

All diagrams are [Mermaid](https://mermaid.js.org/): they render on GitHub, in VS Code (Markdown preview) and at mermaid.live, and can be exported as PNG/SVG for the report.

## 1. Layered architecture (matches the proposal's five layers)

```mermaid
flowchart TB
    subgraph SRC[Data sources]
        S1[Sales / billing CSV, XLSX, Parquet]
        S2[Inventory, finance, logistics]
        S3[External factors: festival calendar]
    end
    subgraph ING[Ingestion and preprocessing - backend/app/pipeline]
        I1[Column mapping + validation]
        I2[Clean: duplicates, gaps, missing values, IQR outliers]
        I3[Feature engineering: lags, rolling stats, calendar, festival]
    end
    subgraph ML[AI / ML engine]
        F[Forecasting - XGBoost, Prophet, SARIMA, LSTM<br/>backend/app/forecasting]
        A[Risk and anomaly detection - Isolation Forest, autoencoder, Z-score<br/>backend/app/risk]
        R[Recommendation engine - reorder, transfer, markdown, budget<br/>backend/app/recommend]
        W[What-if simulator - Monte Carlo<br/>backend/app/simulate]
    end
    subgraph INS[Insight and explainability]
        X[TreeSHAP, PDP/ICE, drift and parity<br/>backend/app/explain]
        K[KPIs, alerts, reports<br/>backend/app/reports]
    end
    subgraph WEB[Decision dashboard - React + Vite + Tailwind + Chart.js]
        P[Dashboard, Data Sources, Forecasting, Risk, Recommendations,<br/>What-If, Explainability, Reports, Settings, Login]
    end
    SRC --> ING --> ML --> INS --> WEB
    F --> R
    A --> R
    F --> W
    R --> W
    SEC[Security: JWT, RBAC, hash-chained audit - backend/app/auth, app/platform] -.guards.-> WEB
    SEC -.guards.-> INS
```

## 2. Context diagram (DFD level 0)

```mermaid
flowchart LR
    U1([Analyst]) -->|upload files, read forecasts| SYS((DecisionIQ))
    U2([Manager]) -->|approve actions, run scans, edit rules| SYS
    U3([Admin]) -->|thresholds, users, audit| SYS
    SYS -->|forecasts, alerts, recommendations, explanations, reports| U1
    SYS -->|dashboards, PDF/XLSX reports| U2
    SYS -->|audit trail, user list| U3
    DS[(Sales and inventory files)] -->|CSV / XLSX / Parquet| SYS
```

## 3. Data flow (DFD level 1)

```mermaid
flowchart LR
    RAW[(data/raw/train.csv)] --> P1[1 Generate synthetic<br/>prices, inventory, anomalies<br/>ml/prepare_data.py]
    P1 --> D1[(data/processed/*.csv)]
    UP[Uploaded file] --> P2
    D1 --> P2[2 Ingest, map, clean,<br/>engineer features]
    P2 --> D2[(features.parquet<br/>pipeline_state.json)]
    D2 --> P3[3 Train and benchmark<br/>4 models, refit, forecast 90 days]
    P3 --> D3[(models/: xgb.json, forecasts, backtest,<br/>benchmark.json)]
    D1 --> P4[4 Detect anomalies]
    P4 --> D4[(risk/: metrics, billed.parquet)]
    P4 --> DB[(SQLite: anomalies)]
    D3 --> P5[5 Recommend actions]
    D1 --> P5
    P5 --> DB2[(SQLite: recommendations)]
    D3 --> P6[6 Explain / simulate / report]
    DB --> P6
    DB2 --> P6
    P6 --> OUT[API responses, reports/*.pdf|xlsx|json]
    OUT --> UI[React dashboard]
    UI -->|approve, edit, settings| DB3[(SQLite: decisions, settings, audit_log, users)]
```

## 4. Use cases by role

```mermaid
flowchart LR
    An([Analyst]) --- UC1(View dashboard, forecasts, alerts, explanations)
    An --- UC2(Upload data and run the pipeline)
    An --- UC3(Run what-if scenarios, generate reports)
    Mg([Manager]) --- UC1
    Mg --- UC2
    Mg --- UC3
    Mg --- UC4(Approve or dismiss recommendations and alerts)
    Mg --- UC5(Run scans and retraining, edit inventory rules)
    Mg --- UC6(View audit trail)
    Ad([Admin]) --- UC1
    Ad --- UC4
    Ad --- UC5
    Ad --- UC6
    Ad --- UC7(Change risk thresholds and compliance settings)
    Ad --- UC8(Manage users and roles)
```

## 5. Data model

The application keeps *analytical* data in files (CSV/Parquet/JSON under `data/`) and *operational* data in the relational database (SQLite by default, SQLAlchemy models in `backend/app/db/models.py`).
`sales`, `model_runs` and `forecasts` tables exist in the schema (and `python -m app.db.load_data` can fill `sales`) but the running application reads those from files.

```mermaid
erDiagram
    USERS ||--o{ AUDIT_LOG : "acts in"
    STORES ||--o{ ANOMALIES : "raised at"
    ITEMS  ||--o{ ANOMALIES : "about"
    STORES ||--o{ RECOMMENDATIONS : "for"
    ITEMS  ||--o{ RECOMMENDATIONS : "for"
    STORES ||--o{ SALES : "records"
    ITEMS  ||--o{ SALES : "records"
    STORES ||--o{ LOGISTICS_COSTS : "incurs"
    MODEL_RUNS ||--o{ FORECASTS : "produces"

    USERS { int id PK  string email  string full_name  string role  string password_hash  bool active  datetime last_login }
    AUDIT_LOG { int id PK  datetime timestamp  string user_name  string role  string action  string category  string prev_hash  string entry_hash }
    APP_SETTINGS { string key PK  json value  datetime updated_at }
    ANOMALIES { int id PK  int store FK  int item FK  date date  date end_date  string anomaly_type  float score  string severity  float amount  string status  string assignee  json evidence }
    RECOMMENDATIONS { int id PK  string key  string kind  int store FK  int store_to  int item FK  float impact_inr  float confidence  json payload  string status  datetime decided_at }
    SCENARIOS { int id PK  string name  json levers  json results }
    REPORTS { int id PK  string title  string template  string format  int size_bytes  string sha256  string status }
    STORES { int store PK  string name  string city }
    ITEMS { int item PK  string sku_code  string name  string category  float base_price  float unit_cost }
    SALES { int id PK  date date  int store FK  int item FK  int sales  float net_price  int units_billed  int on_hand  int on_order  string anomaly_type }
    LOGISTICS_COSTS { int id PK  int store FK  date week_start  float freight_cost }
    MODEL_RUNS { int id PK  string model_name  string version  float mape  bool selected }
    FORECASTS { int id PK  int model_run_id FK  int store FK  int item FK  date date  float yhat }
```

## 6. Sequence: approving a recommendation

```mermaid
sequenceDiagram
    actor M as Manager
    participant UI as React page
    participant API as FastAPI
    participant AUTH as get_current_user / require
    participant DB as SQLite
    participant AUD as audit_log
    M->>UI: click "Approve PO"
    UI->>API: PATCH /api/recommendations/12 {status: Approved} + Bearer token
    API->>AUTH: verify JWT, load user, check approve_actions
    AUTH-->>API: Manager OK (403 for Analyst)
    API->>DB: update status, decided_at
    API->>AUD: append entry (hash of previous entry + who/what/IP)
    API-->>UI: updated recommendation
    UI-->>M: card moves to Approved, KPIs refresh
```

## 7. Sequence: training and forecast serving

```mermaid
sequenceDiagram
    participant API as POST /api/forecast/retrain
    participant T as train.run_training
    participant X as XGBoost (in process)
    participant Q as Prophet / SARIMA (per series)
    participant L as LSTM worker (subprocess)
    participant FS as data/processed/models
    API->>T: background task (lock: one run at a time)
    T->>X: backtest on all 500 series, last 90 days held out
    T->>Q: backtest on a 20-series sample
    T->>L: backtest (TensorFlow runs in its own process)
    T->>T: select best by MAPE; serving model = best global model
    T->>X: refit on all data, recursive 90-day forecast
    T->>FS: forecasts.parquet, backtest.parquet, sigma.parquet, xgb.json, benchmark.json
    Note over API,FS: GET /api/forecast/* reads these files (cached by mtime)
```

## 8. Deployment (docker compose)

```mermaid
flowchart LR
    B[Browser] -->|:8080| N[web: nginx<br/>static React build]
    N -->|/api/ proxy| A[api: uvicorn FastAPI :8000]
    BS[bootstrap: python -m app.bootstrap<br/>runs once, then exits] -.must succeed first.-> A
    A --- V[(./data volume<br/>raw, processed, models, reports, SQLite)]
    BS --- V
```
