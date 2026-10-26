"""Risk scan: detect anomalies, build the alert ledger (DB), evaluate against injected labels.

Usage (from backend/): python -m app.risk.scan
"""
import json
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Anomaly
from app.db.session import get_engine
from app.risk import detect

STEPS = [("load", "Load billed data"), ("signals", "Compute signals"), ("score", "Score detectors"),
         ("alerts", "Build alert ledger"), ("evaluate", "Evaluate vs labels")]
_lock = threading.Lock()

TYPE_LABELS = {
    "duplicate_billing": "Duplicate billing", "demand_drop": "Abnormal demand drop",
    "margin_erosion": "Margin erosion", "cost_spike": "Logistics cost spike", "unclassified": "Unusual pattern",
}


def risk_dir():
    d = settings.data_dir / "processed" / "risk"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_running() -> bool:
    return _lock.locked()


def read_state() -> dict:
    p = risk_dir() / "scan_state.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"status": "idle", "steps": [{"key": k, "label": l, "status": "pending"} for k, l in STEPS]}


def read_metrics() -> dict | None:
    p = risk_dir() / "metrics.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save(state):
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    p = risk_dir() / "scan_state.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    tmp.replace(p)


def _step(state, key, status, detail=""):
    for s in state["steps"]:
        if s["key"] == key:
            s.update(status=status, detail=detail)
    _save(state)


def assign_severity(alerts: pd.DataFrame) -> pd.DataFrame:
    """Severity is relative to the ledger: top 15% of financial exposure = High, next 35% = Medium."""
    pct = alerts["amount"].rank(pct=True)
    alerts["severity"] = np.where(pct >= 0.85, "High", np.where(pct >= 0.5, "Medium", "Low"))
    return alerts


def _row_amount(df: pd.DataFrame, types: pd.Series) -> pd.Series:
    spike = ((df["units_billed"] - df["expected"]).clip(lower=0) * df["net_price"])
    margin = ((df["unit_cost"] - df["net_price"]).clip(lower=0) * df["units_billed"])
    drop = ((df["expected"] - df["units_billed"]).clip(lower=0) * df["net_price"])
    return np.select([types == "duplicate_billing", types == "margin_erosion", types == "demand_drop"], [spike, margin, drop], 0.0)


def _explain(t: str, r: pd.Series, n_days: int) -> str:
    if t == "duplicate_billing":
        return (f"Billed {r.units_billed:.0f} units vs ~{r.expected:.0f} expected ({r.units_billed / max(r.expected, 1):.1f}x, "
                f"z={r.z_units:.1f}); pattern consistent with an invoice counted twice.")
    if t == "demand_drop":
        return f"Billed units stayed far below the ~{r.expected:.0f}/day baseline for {n_days} day(s) (sustained-drop z={r.zd:.1f})."
    if t == "margin_erosion":
        return (f"Sold at Rs {r.net_price:,.0f} against list Rs {r.list_price:,.0f} ({r.depth * 100:.0f}% off) and cost "
                f"Rs {r.unit_cost:,.0f}: margin {r.margin * 100:.0f}%.")
    return "Flagged by multiple detectors but matches no known pattern."


def build_alerts(sig: pd.DataFrame, z_thr: float) -> pd.DataFrame:
    f = sig[sig["flag_Ensemble"]].copy()
    f["type"] = detect.classify_frame(f, z_thr)
    f["event"] = detect.group_events(sig, sig["flag_Ensemble"], f["type"].reindex(sig.index)).reindex(f.index)
    f["amount_row"] = _row_amount(f, f["type"])
    rows = []
    for _, g in f.groupby("event"):
        peak = g.loc[g["score"].idxmax()]
        t = g["type"].iloc[0]
        amount = float(g["amount_row"].sum())
        rows.append({
            "store": int(peak["store"]), "item": int(peak["item"]), "date": g["date"].min().date(), "end_date": g["date"].max().date(),
            "anomaly_type": t, "score": round(float(g["score"].max()), 4), "amount": round(amount, 2),
            "explanation": _explain(t, peak, len(g)),
            "evidence": {
                "peak_date": peak["date"].strftime("%Y-%m-%d"), "units_billed": float(peak["units_billed"]),
                "expected": float(peak["expected"]), "net_price": float(peak["net_price"]), "list_price": float(peak["list_price"]),
                "unit_cost": float(peak["unit_cost"]), "z_units": round(float(peak["z_units"]), 2), "zd": round(float(peak["zd"]), 2),
                "margin_pct": round(float(peak["margin"]) * 100, 1), "discount_pct": round(float(peak["depth"]) * 100, 1),
                "days": len(g),
                "detectors": {d: bool(peak[f"flag_{d}"]) for d in ["IsolationForest", "Autoencoder", "ZScore"]},
            },
        })
    return pd.DataFrame(rows)


def cost_spike_alerts(spikes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in spikes[spikes["flag"]].itertuples():
        amount = float(r.freight_cost - r.baseline)
        rows.append({
            "store": int(r.store), "item": None, "date": r.week_start.date(), "end_date": (r.week_start + timedelta(days=6)).date(),
            "anomaly_type": "cost_spike", "score": round(min(1.0, float(r.z) / 20), 4), "amount": round(amount, 2),
            "explanation": f"Weekly freight Rs {r.freight_cost:,.0f} is {amount / r.baseline * 100:.0f}% above the 12-week baseline of Rs {r.baseline:,.0f} (z={r.z:.1f}).",
            "evidence": {"freight_cost": float(r.freight_cost), "baseline": float(r.baseline), "z": round(float(r.z), 2)},
        })
    return pd.DataFrame(rows)


def _persist(alerts: pd.DataFrame) -> None:
    engine = get_engine()
    with Session(engine) as db:
        Anomaly.__table__.create(engine, checkfirst=True)
        old = {(a.store, a.item, a.date, a.anomaly_type): (a.status, a.assignee) for a in db.scalars(select(Anomaly))}
        db.query(Anomaly).delete()
        for r in alerts.to_dict("records"):
            status, assignee = old.get((r["store"], r["item"], r["date"], r["anomaly_type"]), ("Open", None))
            db.add(Anomaly(**r, status=status, assignee=assignee))
        db.commit()


def run_scan(contamination: float = 0.0015, z_thr: float = 3.0) -> dict:
    if not _lock.acquire(blocking=False):
        return read_state()
    t0 = time.perf_counter()
    state = {"status": "running", "steps": [{"key": k, "label": l, "status": "pending"} for k, l in STEPS],
             "params": {"contamination": contamination, "z_threshold": z_thr}}
    try:
        base = settings.data_dir / "processed"
        _step(state, "load", "active")
        cols = ["date", "store", "item", "units_billed", "net_price", "list_price", "anomaly_type", "is_anomaly"]
        sales = pd.read_csv(base / "sales.csv", usecols=cols, parse_dates=["date"], keep_default_na=False)
        sales = sales.sort_values(["store", "item", "date"]).reset_index(drop=True)
        items = pd.read_csv(base / "items.csv")
        logistics = pd.read_csv(base / "logistics_costs.csv", parse_dates=["week_start"], keep_default_na=False)
        _step(state, "load", "done", f"{len(sales):,} billed rows")

        _step(state, "signals", "active")
        sig = detect.build_signals(sales, items)
        _step(state, "signals", "done")

        _step(state, "score", "active")
        sig = detect.score(sig, contamination=contamination, z_thr=z_thr)
        _step(state, "score", "done", f"{int(sig['flag_Ensemble'].sum()):,} rows flagged")

        _step(state, "alerts", "active")
        alerts = pd.concat([build_alerts(sig, z_thr), cost_spike_alerts(detect.detect_cost_spikes(logistics, z_thr))], ignore_index=True)
        alerts = assign_severity(alerts)
        _persist(alerts)
        keep = ["date", "store", "item", "units_billed", "expected", "net_price", "list_price", "unit_cost", "z_units", "zd",
                "margin", "depth", "score", "flag_Ensemble"]
        sig[keep].to_parquet(risk_dir() / "billed.parquet", index=False)
        _step(state, "alerts", "done", f"{len(alerts):,} alerts")

        _step(state, "evaluate", "active")
        metrics = evaluate(sig, sales, logistics, alerts, z_thr)
        metrics["params"] = state["params"]
        (risk_dir() / "metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
        _step(state, "evaluate", "done", f"ensemble F1 {metrics['detectors']['Ensemble']['f1']:.2f}")
        state["status"] = "complete"
    except Exception as e:
        state["status"] = "failed"
        state["error"] = f"{type(e).__name__}: {e}"
        for s in state["steps"]:
            if s["status"] == "active":
                s.update(status="failed", detail=str(e))
    finally:
        state["duration_s"] = round(time.perf_counter() - t0, 1)
        _save(state)
        _lock.release()
    return state


def evaluate(sig, sales, logistics, alerts, z_thr) -> dict:
    valid = sig["valid"].to_numpy()
    truth = ((sales["is_anomaly"] == 1) & sig["valid"]).to_numpy()
    out = {"ran_at": datetime.now().isoformat(timespec="seconds"), "rows_scanned": int(valid.sum()),
           "rows_flagged": int(sig["flag_Ensemble"].sum()), "alerts": len(alerts),
           "detectors": {d: detect.prf(sig[f"flag_{d}"].to_numpy() & valid, truth) for d in detect.DETECTORS}}
    labels = sales["anomaly_type"].where(sig["valid"], "")
    flagged = sig["flag_Ensemble"]
    out["recall_by_type"] = {t: round(float(flagged[labels == t].mean()), 4) for t in ["duplicate_billing", "demand_drop", "margin_erosion"]}
    ev = detect.group_events(sales, labels != "", labels)
    ev_hit = flagged.groupby(ev).any()
    out["event_recall"] = round(float(ev_hit.mean()), 4)
    # alert precision: share of series alerts overlapping at least one injected anomaly row
    series_alerts = alerts[alerts["anomaly_type"] != "cost_spike"]
    lab_rows = sales.loc[truth, ["store", "item", "date"]]
    hit = 0
    by_series = {k: g["date"].to_numpy() for k, g in lab_rows.groupby(["store", "item"])}
    for r in series_alerts.itertuples():
        d = by_series.get((r.store, r.item))
        if d is not None and ((d >= np.datetime64(r.date)) & (d <= np.datetime64(r.end_date))).any():
            hit += 1
    out["alert_precision"] = round(hit / max(len(series_alerts), 1), 4)
    spikes = detect.detect_cost_spikes(logistics, z_thr)
    out["cost_spike"] = detect.prf(spikes["flag"].to_numpy(), (spikes["anomaly_type"] == "cost_spike").to_numpy())
    return out


if __name__ == "__main__":
    s = run_scan()
    print(s["status"], s.get("error", ""), s["duration_s"], "s")
    print(json.dumps(read_metrics(), indent=1) if s["status"] == "complete" else "")
