"""Training orchestrator: backtest all four models, select the best, refit, forecast the next HORIZON days.

Usage (from backend/): python -m app.forecasting.train [--quick]
"""
import argparse
import json
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd

from app.forecasting import xgb_model
from app.forecasting.classical import prophet_forecast, sarima_forecast
from app.forecasting.data import HOLDOUT_DAYS, HORIZON, extend_dates, load_matrix, models_dir
from app.forecasting.lstm_runner import run_lstm
from app.forecasting.metrics import evaluate

STEPS = [
    ("load", "Load engineered data"),
    ("xgboost", "XGBoost backtest"),
    ("prophet", "Prophet backtest"),
    ("sarima", "SARIMA backtest"),
    ("lstm", "LSTM backtest"),
    ("select", "Model selection"),
    ("final", "Refit & forecast"),
]
_lock = threading.Lock()


def is_running() -> bool:
    return _lock.locked()


def _state_path():
    return models_dir() / "train_state.json"


def read_state() -> dict:
    p = _state_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"status": "idle", "steps": [{"key": k, "label": l, "status": "pending"} for k, l in STEPS]}


def _save(state):
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    tmp.replace(_state_path())


def _step(state, key, status, detail=""):
    for s in state["steps"]:
        if s["key"] == key:
            s.update(status=status, detail=detail)
    done = sum(s["status"] == "done" for s in state["steps"])
    state["progress"] = round(done / len(state["steps"]) * 100)
    _save(state)


def _timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, round(time.perf_counter() - t0, 1)


def run_training(quick: bool = False) -> dict:
    """quick=True shrinks the benchmark for smoke tests (fewer series / trees / epochs)."""
    if not _lock.acquire(blocking=False):
        return read_state()
    state = {"status": "running", "steps": [{"key": k, "label": l, "status": "pending"} for k, l in STEPS], "progress": 0}
    t_all = time.perf_counter()
    try:
        out_dir = models_dir()
        _step(state, "load", "active")
        y, dates, series = load_matrix()
        n, T = y.shape
        T_tr = T - HOLDOUT_DAYS
        y_train, y_hold = y[:, :T_tr], y[:, T_tr:]
        rng = np.random.default_rng(7)
        per_store = 1 if quick else 2
        eval_idx = np.array(sorted(
            i for st, g in series.groupby("store") for i in rng.choice(g.index.to_numpy(), per_store, replace=False)
        ))
        _step(state, "load", "done", f"{n} series x {T} days; holdout last {HOLDOUT_DAYS} days; benchmark sample {len(eval_idx)} series")

        results, preds = {}, {}
        xgb_kw = dict(n_estimators=60) if quick else {}

        _step(state, "xgboost", "active")
        model_bt, secs = _timed(lambda: xgb_model.train(y, dates, series, T_tr, **xgb_kw))
        p_xgb = xgb_model.forecast(model_bt, y_train, dates, series, HOLDOUT_DAYS)
        preds["XGBoost"] = p_xgb
        results["XGBoost"] = {**evaluate(y_hold[eval_idx], p_xgb[eval_idx]), "train_s": secs,
                              "full_set": evaluate(y_hold, p_xgb)}
        _step(state, "xgboost", "done", f"MAPE {results['XGBoost']['mape']:.1f}% on sample")

        def per_series(fn):
            return np.vstack([fn(i) for i in eval_idx])

        _step(state, "prophet", "active")
        p, secs = _timed(lambda: per_series(lambda i: prophet_forecast(y_train[i], dates[:T_tr], HOLDOUT_DAYS)))
        results["Prophet"] = {**evaluate(y_hold[eval_idx], p), "train_s": secs}
        _step(state, "prophet", "done", f"MAPE {results['Prophet']['mape']:.1f}%")

        _step(state, "sarima", "active")
        p, secs = _timed(lambda: per_series(lambda i: sarima_forecast(y_train[i], HOLDOUT_DAYS)))
        results["SARIMA"] = {**evaluate(y_hold[eval_idx], p), "train_s": secs}
        _step(state, "sarima", "done", f"MAPE {results['SARIMA']['mape']:.1f}%")

        _step(state, "lstm", "active")
        p_lstm, secs = run_lstm(y, dates, T_tr, HOLDOUT_DAYS, quick=quick)
        preds["LSTM"] = p_lstm
        results["LSTM"] = {**evaluate(y_hold[eval_idx], p_lstm[eval_idx]), "train_s": secs, "full_set": evaluate(y_hold, p_lstm)}
        _step(state, "lstm", "done", f"MAPE {results['LSTM']['mape']:.1f}%")

        _step(state, "select", "active")
        selected = min(results, key=lambda k: results[k]["mape"])
        serving = min(("XGBoost", "LSTM"), key=lambda k: results[k]["mape"])  # only global models scale to every series
        for k, r in results.items():
            r["status"] = "Selected" if k == selected else "Baseline" if k == "SARIMA" else "Evaluated"
        resid = y_hold - preds[serving]
        sigma = resid.std(axis=1)
        pd.DataFrame({**series, "sigma": sigma}).to_parquet(out_dir / "sigma.parquet", index=False)
        hold_dates = dates[T_tr:]
        bt = pd.DataFrame({
            "store": np.repeat(series["store"].to_numpy(), HOLDOUT_DAYS),
            "item": np.repeat(series["item"].to_numpy(), HOLDOUT_DAYS),
            "date": np.tile(hold_dates, n), "actual": y_hold.ravel(), "pred": preds[serving].ravel().round(2),
        })
        bt.to_parquet(out_dir / "backtest.parquet", index=False)
        _step(state, "select", "done", f"selected {selected}; serving {serving}")

        _step(state, "final", "active")
        if serving == "XGBoost":
            final = xgb_model.train(y, dates, series, T, **xgb_kw)
            fc = xgb_model.forecast(final, y, dates, series, HORIZON)
            final.save_model(out_dir / "xgb.json")
            imp = xgb_model.importance(final)
        else:
            fc, _ = run_lstm(y, dates, T, HORIZON, quick=quick, save_model=out_dir / "lstm.keras")
            imp = xgb_model.importance(model_bt)
        fdates = extend_dates(dates, HORIZON)[T:]
        yhat = fc.ravel().round(2)
        sig = np.repeat(sigma, HORIZON)
        pd.DataFrame({
            "store": np.repeat(series["store"].to_numpy(), HORIZON), "item": np.repeat(series["item"].to_numpy(), HORIZON),
            "date": np.tile(fdates, n), "yhat": yhat,
            "lower": np.clip(yhat - 1.96 * sig, 0, None).round(2), "upper": (yhat + 1.96 * sig).round(2),
        }).to_parquet(out_dir / "forecasts.parquet", index=False)

        meta = {
            "version": f"{serving.lower()}-{datetime.now():%Y%m%d%H%M}",
            "trained_at": datetime.now().isoformat(timespec="seconds"),
            "holdout_days": HOLDOUT_DAYS, "horizon_days": HORIZON,
            "backtest_window": [hold_dates[0].date().isoformat(), hold_dates[-1].date().isoformat()],
            "forecast_window": [fdates[0].date().isoformat(), fdates[-1].date().isoformat()],
            "n_series": n, "eval_series": [{"store": int(series.store[i]), "item": int(series.item[i])} for i in eval_idx],
            "models": [{"name": k, **v} for k, v in results.items()],
            "selected": selected, "serving": serving, "importance": imp, "quick": quick,
        }
        (out_dir / "benchmark.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        _step(state, "final", "done", f"{n * HORIZON:,} forecast rows")
        state["status"] = "complete"
    except Exception as e:
        state["status"] = "failed"
        state["error"] = f"{type(e).__name__}: {e}"
        for s in state["steps"]:
            if s["status"] == "active":
                s.update(status="failed", detail=str(e))
    finally:
        state["duration_s"] = round(time.perf_counter() - t_all, 1)
        _save(state)
        _lock.release()
    return state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    s = run_training(ap.parse_args().quick)
    print(s["status"], s.get("error", ""), s["duration_s"], "s")
    for st in s["steps"]:
        print(f"  {st['key']:<8}{st['status']:<8}{st.get('detail', '')}")
