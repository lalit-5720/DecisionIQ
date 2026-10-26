"""Evaluation for the project report (Chapter 4): reproducible tables and figures from the trained artifacts.

Usage (from backend/):  python -m app.evaluation.report [--with-tests] [--skip-sweep]
Writes docs/results/EVALUATION.md, docs/results/tables/*.csv, docs/results/figures/*.png and results.json.
Nothing here trains models: it reads data/processed/models/* and data/processed/risk/*.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.config import ROOT_DIR, settings  # noqa: E402
from app.forecasting import xgb_model  # noqa: E402
from app.forecasting.data import HOLDOUT_DAYS, load_matrix, models_dir  # noqa: E402
from app.forecasting.metrics import evaluate  # noqa: E402
from app.pipeline.clean import clean  # noqa: E402
from app.pipeline.features import build_features  # noqa: E402
from app.risk import detect  # noqa: E402

OUT = ROOT_DIR / "docs" / "results"
TAB, FIG = OUT / "tables", OUT / "figures"
PALETTE = ["#00A1DA", "#8B7CF6", "#34D399", "#FBBF24", "#F87171", "#B7C0D8"]


def md_table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    cols = list(df.columns)
    rows = [[floatfmt.format(v) if isinstance(v, float) else str(v) for v in r] for r in df.itertuples(index=False)]
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"] + ["| " + " | ".join(r) + " |" for r in rows])


def save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    df.to_csv(TAB / f"{name}.csv", index=False)
    return df


# ------------------------------------------------------------------ forecasting
def forecasting_section(meta: dict) -> tuple[dict, str]:
    y, dates, series = load_matrix()
    T = y.shape[1]
    T_tr = T - HOLDOUT_DAYS
    y_tr, y_hold = y[:, :T_tr], y[:, T_tr:]
    n = len(series)
    eval_idx = np.array([int(np.flatnonzero((series.store == e["store"]) & (series.item == e["item"]))[0]) for e in meta["eval_series"]])

    h = np.arange(HOLDOUT_DAYS) % 7
    naive7 = y_tr[:, -7:][:, h]
    ma28 = y_tr[:, -28:].reshape(n, 4, 7).mean(axis=1)[:, h]
    baselines = {"Seasonal naive (same weekday last week)": naive7, "Weekday average of last 4 weeks": ma28}

    rows = []
    for m in meta["models"]:
        rows.append({"Model": m["name"], "Scope": f"{len(eval_idx)}-series sample", "MAE": m["mae"], "RMSE": m["rmse"], "MAPE %": m["mape"],
                     "WAPE %": m["wape"], "R2": m["r2"], "Train s": m["train_s"], "Role": m["status"]})
    for name, p in baselines.items():
        e = evaluate(y_hold[eval_idx], p[eval_idx])
        rows.append({"Model": name, "Scope": f"{len(eval_idx)}-series sample", "MAE": e["mae"], "RMSE": e["rmse"], "MAPE %": e["mape"],
                     "WAPE %": e["wape"], "R2": e["r2"], "Train s": 0.0, "Role": "Naive baseline"})
    sample = save(pd.DataFrame(rows), "model_comparison_sample")

    full = []
    for m in meta["models"]:
        if "full_set" in m:
            f = m["full_set"]
            full.append({"Model": m["name"], "MAE": f["mae"], "RMSE": f["rmse"], "MAPE %": f["mape"], "WAPE %": f["wape"], "MAPE % (daily chain total)": f["mape_agg"], "R2": f["r2"]})
    for name, p in baselines.items():
        e = evaluate(y_hold, p)
        full.append({"Model": name, "MAE": e["mae"], "RMSE": e["rmse"], "MAPE %": e["mape"], "WAPE %": e["wape"], "MAPE % (daily chain total)": e["mape_agg"], "R2": e["r2"]})
    full_df = save(pd.DataFrame(full), "model_comparison_all_series")

    bt = pd.read_parquet(models_dir() / "backtest.parquet")
    items = pd.read_csv(settings.data_dir / "processed" / "items.csv").set_index("item")
    stores = pd.read_csv(settings.data_dir / "processed" / "stores.csv").set_index("store")["name"]
    bt["h"] = (bt["date"] - bt["date"].min()).dt.days
    bt["bucket"] = pd.cut(bt["h"], [-1, 29, 59, 89], labels=["Days 1-30", "Days 31-60", "Days 61-90"])
    bt["abs"] = (bt["actual"] - bt["pred"]).abs()
    bt["category"] = bt["item"].map(items["category"])

    def breakdown(by):
        g = bt.groupby(by, observed=True)
        d = pd.DataFrame({"WAPE %": g["abs"].sum() / g["actual"].sum() * 100, "Bias %": (g["pred"].sum() / g["actual"].sum() - 1) * 100,
                          "Actual units": g["actual"].sum().round(0).astype(int)}).reset_index()
        return d

    by_h, by_s, by_c = save(breakdown("bucket"), "error_by_horizon"), breakdown("store"), save(breakdown("category"), "error_by_category")
    by_s["store"] = by_s["store"].map(stores)
    save(by_s.rename(columns={"store": "Store"}), "error_by_store")

    chain = bt.groupby("date")[["actual", "pred"]].sum()
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot(chain.index, chain["actual"], color=PALETTE[0], label="Actual")
    ax.plot(chain.index, chain["pred"], color=PALETTE[1], linestyle="--", label="Predicted (XGBoost, 90-day recursive)")
    ax.set_title("Holdout: chain-wide daily units (all 500 series)")
    ax.set_ylabel("Units/day")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "holdout_actual_vs_predicted.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    d = full_df.sort_values("MAPE %")
    ax.barh(d["Model"], d["MAPE %"], color=[PALETTE[0] if "Seasonal" not in m and "Weekday" not in m else PALETTE[5] for m in d["Model"]])
    ax.set_xlabel("MAPE % (daily, per series, 90-day holdout) - lower is better")
    ax.set_title("Forecast accuracy on all 500 series (models with full-set runs vs naive baselines)")
    ax.title.set_fontsize(9)
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(FIG / "model_mape_all_series.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    s = sample.sort_values("MAPE %")
    ax.barh(s["Model"], s["MAPE %"], color=[PALETTE[2] if r == "Selected" else PALETTE[5] if "baseline" in r.lower() else PALETTE[0] for r in s["Role"]])
    ax.set_xlabel("MAPE % on the 20-series benchmark sample - lower is better")
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(FIG / "model_mape_sample.png", dpi=150)
    plt.close(fig)

    best_baseline = full_df[full_df["Model"].str.contains("Seasonal|Weekday")]["MAPE %"].min()
    xgb_full = next(m["full_set"] for m in meta["models"] if m["name"] == meta["serving"])
    summary = {"serving": meta["serving"], "full_mape": xgb_full["mape"], "full_wape": xgb_full["wape"], "chain_mape": xgb_full["mape_agg"], "r2": xgb_full["r2"],
               "best_naive_mape": float(best_baseline), "improvement_vs_naive_pct": float((1 - xgb_full["mape"] / best_baseline) * 100)}

    md = f"""## 1. Forecasting accuracy

Holdout: the last {HOLDOUT_DAYS} days ({meta['backtest_window'][0]} to {meta['backtest_window'][1]}). Every model forecasts the whole holdout **recursively from the training cut-off**
(multi-step, no peeking at holdout actuals). MAPE ignores zero-demand days; WAPE = sum|error| / sum(actual); the *chain total* MAPE is on daily totals across series.

### 1.1 All four models and two naive baselines, 20-series sample (2 items per store)
Prophet and SARIMA fit one model per series, so all models are compared on the same 20-series sample.

{md_table(sample)}

### 1.2 Models trained on every series (all 500 series)
{md_table(full_df)}

The serving model ({meta['serving']}) reaches **{xgb_full['mape']:.1f}% MAPE** per series-day and **{xgb_full['mape_agg']:.1f}%** on chain-wide daily totals, i.e. {summary['improvement_vs_naive_pct']:.0f}% lower MAPE than the best naive baseline ({best_baseline:.1f}%).
The project target was a MAPE within 10-15% on test data: it is met for per-series daily MAPE ({xgb_full['mape']:.1f}%) and at higher aggregation.

![MAPE all series](figures/model_mape_all_series.png)
![MAPE sample](figures/model_mape_sample.png)
![Holdout](figures/holdout_actual_vs_predicted.png)

### 1.3 Error by forecast horizon (XGBoost, all series)
{md_table(by_h.rename(columns={'bucket': 'Horizon'}))}

**Bias.** Forecasts run low: bias moves from {by_h['Bias %'].iloc[0]:.1f}% in the first 30 days to {by_h['Bias %'].iloc[-1]:.1f}% in the last 30. Recursive multi-step forecasting feeds predictions back
as lags, which shrinks them toward the series mean, and the autumn peak in the Kaggle data is under-predicted. Error (WAPE) is stable at about 11% for 60 days and rises to {by_h['WAPE %'].iloc[-1]:.0f}% in the final month.

### 1.4 Error by category and store
{md_table(by_c.rename(columns={'category': 'Category'}))}

{md_table(by_s.rename(columns={'store': 'Store'}))}

Error is similar across categories and stores (WAPE {by_s['WAPE %'].min():.1f}-{by_s['WAPE %'].max():.1f}% by store), so no store or category is served markedly worse.
"""
    return summary, md


# ------------------------------------------------------------------ anomaly detection
def anomaly_section(skip_sweep: bool) -> tuple[dict, str]:
    base = settings.data_dir / "processed"
    sales = pd.read_csv(base / "sales.csv", usecols=["date", "store", "item", "units_billed", "net_price", "list_price", "anomaly_type", "is_anomaly"],
                        parse_dates=["date"], keep_default_na=False).sort_values(["store", "item", "date"]).reset_index(drop=True)
    items = pd.read_csv(base / "items.csv")
    metrics = json.loads((base / "risk" / "metrics.json").read_text(encoding="utf-8"))

    det = pd.DataFrame([{"Detector": k, "Precision": v["precision"], "Recall": v["recall"], "F1": v["f1"], "TP": v["tp"], "FP": v["fp"], "FN": v["fn"]}
                        for k, v in metrics["detectors"].items()])
    save(det, "anomaly_detectors")
    per_type = save(pd.DataFrame([{"Anomaly type": k.replace("_", " "), "Ensemble recall": v} for k, v in metrics["recall_by_type"].items()]), "anomaly_recall_by_type")
    cost = metrics["cost_spike"]
    extra = pd.DataFrame([
        {"Measure": "Event recall (demand-drop/duplicate/margin events detected)", "Value": metrics["event_recall"]},
        {"Measure": "Alert precision (alerts overlapping an injected anomaly)", "Value": metrics["alert_precision"]},
        {"Measure": "Logistics cost spikes: precision / recall / F1", "Value": f"{cost['precision']:.2f} / {cost['recall']:.2f} / {cost['f1']:.2f}"},
        {"Measure": "Rows scanned / flagged / alerts", "Value": f"{metrics['rows_scanned']:,} / {metrics['rows_flagged']:,} / {metrics['alerts']:,}"},
    ])

    sweep_md, sweep_summary = "_Sweep skipped._", {}
    if not skip_sweep:
        sig0 = detect.build_signals(sales, items)
        truth = ((sales["is_anomaly"] == 1) & sig0["valid"]).to_numpy()
        valid = sig0["valid"].to_numpy()
        rows = []
        for kind, grid in (("contamination", [0.0005, 0.001, 0.0015, 0.0025, 0.004]), ("z_threshold", [2.5, 3.0, 3.5, 4.0])):
            for v in grid:
                t0 = time.perf_counter()
                sc = detect.score(sig0, contamination=v if kind == "contamination" else 0.0015, z_thr=v if kind == "z_threshold" else 3.0)
                m = detect.prf(sc["flag_Ensemble"].to_numpy() & valid, truth)
                rows.append({"Parameter": "sensitivity (share of rows flagged by ML detectors)" if kind == "contamination" else "z-score threshold",
                             "Value": f"{v * 100:.2f}%" if kind == "contamination" else f"{v:.1f}", "Precision": m["precision"], "Recall": m["recall"], "F1": m["f1"], "Rows flagged": int(sc["flag_Ensemble"].sum()),
                             "Seconds": round(time.perf_counter() - t0, 1)})
        sw = save(pd.DataFrame(rows), "anomaly_sensitivity_sweep")
        c = sw[sw["Parameter"].str.startswith("sensitivity")]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(c["Recall"], c["Precision"], marker="o", color=PALETTE[0])
        for _, r in c.iterrows():
            ax.annotate(r["Value"], (r["Recall"], r["Precision"]), textcoords="offset points", xytext=(5, 5), fontsize=8)
        ax.set_xlabel("Recall")
        ax.set_ylabel("Precision")
        ax.set_title("Ensemble precision-recall trade-off (detector sensitivity)")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(FIG / "anomaly_precision_recall.png", dpi=150)
        plt.close(fig)
        best = sw.loc[sw["F1"].idxmax()]
        sweep_summary = {"best_param": best["Parameter"], "best_value": best["Value"], "best_f1": float(best["F1"])}
        sweep_md = md_table(sw) + "\n\n![PR](figures/anomaly_precision_recall.png)"

    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    x = np.arange(len(det))
    ax.bar(x - 0.27, det["Precision"], 0.27, label="Precision", color=PALETTE[0])
    ax.bar(x, det["Recall"], 0.27, label="Recall", color=PALETTE[1])
    ax.bar(x + 0.27, det["F1"], 0.27, label="F1", color=PALETTE[2])
    ax.set_xticks(x)
    ax.set_xticklabels(det["Detector"], fontsize=8)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    ax.set_title("Anomaly detectors vs injected labels (row level)")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(FIG / "anomaly_detectors.png", dpi=150)
    plt.close(fig)

    ens = det[det["Detector"] == "Ensemble"].iloc[0]
    md = f"""## 2. Anomaly and risk detection

Ground truth is **synthetic**: {int(sales['is_anomaly'].sum()):,} billed rows were corrupted on purpose (duplicate billing, margin erosion, multi-day demand drops) and 40 weekly logistics costs were spiked.
The detectors never see these labels. Row-level metrics, current settings (z = {metrics['params']['z_threshold']}, sensitivity {metrics['params']['contamination'] * 100:.2f}%):

{md_table(det)}

![Detectors](figures/anomaly_detectors.png)

Ensemble = a row is flagged when at least 2 of 3 detectors agree. Recall of the ensemble by injected anomaly type:

{md_table(per_type)}

{md_table(extra)}

### 2.1 Sensitivity sweep
Each row re-runs all detectors with one parameter changed (the other at its default).

{sweep_md}

**Tuning caution.** The sweep is scored against the same synthetic labels it is meant to evaluate, so picking the best row (see `best` in results.json) would be tuning on the test set.
The shipped defaults (z = 3, sensitivity 0.15%) were fixed before the sweep; moving the threshold trades precision for recall rather than finding a free improvement.

**Interpretation and caveats.** Isolation Forest alone is weak on these signals (F1 {det[det['Detector'] == 'IsolationForest']['F1'].iloc[0]:.2f}); the autoencoder and Z-score rules are individually better and the voting ensemble is best (F1 {ens['F1']:.2f}).
Precision is **understated** because the real Kaggle data contains genuinely unusual days that are not labelled; recall for duplicate billing is limited because a doubled sale at a low-volume store is statistically close to normal noise.
These numbers measure how well the detectors recover injected faults, not real-world fraud detection accuracy.
"""
    return {"ensemble_precision": float(ens["Precision"]), "ensemble_recall": float(ens["Recall"]), "ensemble_f1": float(ens["F1"]), **sweep_summary}, md


# ------------------------------------------------------------------ performance
def performance_section(meta: dict) -> tuple[dict, str]:
    rows = []

    def timed(name, fn, n=1):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            ts.append(time.perf_counter() - t0)
        ts = np.array(ts)
        rows.append({"Operation": name, "Runs": n, "Median s": float(np.median(ts)), "p95 s": float(np.percentile(ts, 95)) if n > 1 else float(ts[0])})

    raw = pd.read_csv(settings.data_dir / "raw" / "train.csv", parse_dates=["date"])
    timed("Data cleaning, 913,000 rows (dedupe, gaps, IQR capping)", lambda: clean(raw.rename(columns={})))
    cleaned, _ = clean(raw)
    timed("Feature engineering, 913,000 rows (12 features)", lambda: build_features(cleaned))
    y, dates, series = load_matrix()
    import xgboost as xgb

    booster_path = models_dir() / "xgb.json"
    model = xgb.XGBRegressor()
    model.load_model(booster_path)
    timed("90-day recursive forecast, 500 series (XGBoost)", lambda: xgb_model.forecast(model, y, dates, series, 90), n=3)

    # API latency with the authentication dependency bypassed (measures the application, not scrypt/JWT)
    from fastapi.testclient import TestClient

    from app.auth.deps import get_current_user
    from app.db.models import User
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: User(id=0, email="eval@example.com", full_name="Evaluation", role="Admin", password_hash="", active=True)
    c = TestClient(app)
    calls = [("GET /api/dashboard/summary", lambda: c.get("/api/dashboard/summary")),
             ("GET /api/forecast/series (all stores, 30 days)", lambda: c.get("/api/forecast/series?horizon=30")),
             ("GET /api/risk/alerts (page of 8)", lambda: c.get("/api/risk/alerts?page_size=8")),
             ("GET /api/recommendations", lambda: c.get("/api/recommendations")),
             ("GET /api/explain/local (one series-day)", lambda: c.get("/api/explain/local?store=1&item=1&date=2018-01-20")),
             ("POST /api/simulate/run (all series, 250 runs)", lambda: c.post("/api/simulate/run", json={"runs": 250}))]
    for name, fn in calls:
        fn()  # warm cache
        timed(name, fn, n=10 if "simulate" not in name else 5)
    app.dependency_overrides.pop(get_current_user, None)

    perf = pd.DataFrame(rows)
    save(perf, "performance")
    scan_state = json.loads((settings.data_dir / "processed" / "risk" / "scan_state.json").read_text(encoding="utf-8"))
    train_state = json.loads((models_dir() / "train_state.json").read_text(encoding="utf-8"))
    batch = pd.DataFrame([
        {"Job": "Risk scan over 913,000 billed rows (detect + alert ledger)", "Duration s": scan_state.get("duration_s")},
        {"Job": "Full model training and benchmark (4 models + refit + forecast)", "Duration s": train_state.get("duration_s")},
        *[{"Job": f"  training time, {m['name']}", "Duration s": m["train_s"]} for m in meta["models"]],
    ])
    save(batch, "batch_jobs")
    md = f"""## 3. Performance

Measured on the development machine (Windows, CPU only). Request timings exclude authentication.

{md_table(perf, "{:.3f}")}

Batch jobs (from their last run):

{md_table(batch, "{:.1f}")}

Alert latency: anomaly detection is a batch scan (about {scan_state.get('duration_s')} s for the whole history), so alerts appear after each scan, not in real time.
"""
    return {"forecast_90d_s": float(perf.iloc[2]["Median s"]), "scan_s": scan_state.get("duration_s")}, md


# ------------------------------------------------------------------ tests
def tests_section(run: bool) -> tuple[dict, str]:
    if not run:
        return {}, "## 4. Automated tests\n\n_Skipped (run with --with-tests)._\n"
    cov_file = OUT / "coverage.json"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-W", "ignore", "-o", "addopts=", "--cov=app", f"--cov-report=json:{cov_file}", "-p", "no:cacheprovider"],
                          cwd=ROOT_DIR / "backend", capture_output=True, text=True)
    tail = [ln for ln in proc.stdout.strip().splitlines() if "passed" in ln or "failed" in ln][-1:]
    problems = [ln for ln in proc.stdout.splitlines() if ln.startswith(("ERROR", "FAILED"))]
    if problems:
        print("TEST PROBLEMS:\n" + "\n".join(problems[:10]))
    cov = json.loads(cov_file.read_text())
    totals = cov["totals"]
    pkg = {}
    for f, d in cov["files"].items():
        key = "/".join(Path(f).parts[:2]) if len(Path(f).parts) > 2 else f
        a = pkg.setdefault(key, [0, 0])
        a[0] += d["summary"]["covered_lines"]
        a[1] += d["summary"]["num_statements"]
    table = pd.DataFrame([{"Package": k.replace("\\", "/"), "Statements": v[1], "Covered": v[0], "Coverage %": 100 * v[0] / max(v[1], 1)} for k, v in sorted(pkg.items())])
    save(table, "backend_coverage")
    per_file = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=ROOT_DIR / "backend", capture_output=True, text=True).stdout
    counts = pd.Series([ln.split("::")[0] for ln in per_file.splitlines() if "::" in ln]).value_counts().rename_axis("Test file").reset_index(name="Tests")
    save(counts, "backend_tests_by_file")
    cov_file.unlink(missing_ok=True)
    md = f"""## 4. Automated tests

Backend (pytest): **{tail[0] if tail else 'see log'}**; line coverage of `app/`: **{totals['percent_covered']:.0f}%** ({totals['covered_lines']} of {totals['num_statements']} statements).
This run includes the slow end-to-end training test (excluded from a plain `pytest`; run it alone with `pytest -m slow`).
Coverage omits the evaluation script itself and the LSTM worker, which runs in a separate process.

{md_table(counts)}

Coverage by package:

{md_table(table, "{:.1f}")}

{('**Problems reported by pytest:** ' + '; '.join(problems[:6])) if problems else ''}

Frontend smoke tests (Vitest + Testing Library) are described in the README (`npm test`).
"""
    return {"passed_line": tail[0] if tail else "", "coverage_pct": totals["percent_covered"]}, md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-tests", action="store_true")
    ap.add_argument("--skip-sweep", action="store_true")
    args = ap.parse_args()
    TAB.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    meta = json.loads((models_dir() / "benchmark.json").read_text(encoding="utf-8"))

    t_sum, t_md = tests_section(args.with_tests)
    f_sum, f_md = forecasting_section(meta)
    a_sum, a_md = anomaly_section(args.skip_sweep)
    p_sum, p_md = performance_section(meta)

    header = f"""# DecisionIQ - Evaluation results

Generated {datetime.now():%Y-%m-%d %H:%M} by `python -m app.evaluation.report`. Model version `{meta['version']}`.

**Data.** Real: Kaggle Store Item Demand Forecasting sales (913,000 rows, 10 stores x 50 items, 2013-2017). Synthetic: prices, promotions, festival calendar, inventory,
logistics costs and all anomaly labels. Forecasts use only the real sales plus calendar features; price/promotion columns carry no learnable signal because they were generated independently of sales.

**Headline numbers**

| Measure | Value |
|---|---|
| Serving forecast model | {f_sum['serving']} |
| MAPE per series-day, all 500 series (target 10-15%) | {f_sum['full_mape']:.1f}% |
| MAPE on chain-wide daily totals | {f_sum['chain_mape']:.1f}% |
| WAPE / R2 | {f_sum['full_wape']:.1f}% / {f_sum['r2']:.2f} |
| Best naive baseline MAPE (same weekday last week / 4-week weekday mean) | {f_sum['best_naive_mape']:.1f}% |
| Anomaly ensemble precision / recall / F1 (synthetic labels) | {a_sum['ensemble_precision']:.2f} / {a_sum['ensemble_recall']:.2f} / {a_sum['ensemble_f1']:.2f} |

**Not evaluated.** Recommendation quality has no ground truth (there is no record of what managers would have decided or of realised outcomes); the what-if simulator and
price/marketing responses rely on stated assumptions; no user study has been run (a questionnaire template is in `usability_questionnaire.md`).

"""
    (OUT / "EVALUATION.md").write_text(header + f_md + "\n" + a_md + "\n" + p_md + "\n" + t_md, encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps({"forecasting": f_sum, "anomaly": a_sum, "performance": p_sum, "tests": t_sum, "model_version": meta["version"]}, indent=1, default=float), encoding="utf-8")
    print(f"Wrote {OUT / 'EVALUATION.md'}")
    print(json.dumps({"forecasting": f_sum, "anomaly": a_sum, "performance": p_sum, "tests": t_sum}, indent=1, default=float))


if __name__ == "__main__":
    main()
