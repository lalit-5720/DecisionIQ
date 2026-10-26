"""One command to get a working system from the raw dataset: python -m app.bootstrap

Steps (each skipped when its output already exists, unless --force):
  data      data/raw/train.csv must exist (Kaggle Store Item Demand Forecasting)
  generate  synthetic prices, inventory, anomalies    -> data/processed/*.csv      (ml/prepare_data.py)
  pipeline  clean + engineer features                 -> data/processed/features.parquet
  train     benchmark 4 models, forecast 90 days      -> data/processed/models/*   (about 2 minutes)
  scan      anomaly detection + alert ledger          -> data/processed/risk/*, alerts in the DB
  recommend prescriptive actions                      -> recommendations in the DB
  users     demo accounts (when the users table is empty)
"""
import argparse
import importlib.util
import sys
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.seed import ensure_users
from app.core.config import ROOT_DIR, settings
from app.db.models import Anomaly, Recommendation
from app.db.session import get_engine
from app.forecasting.data import models_dir
from app.pipeline import runner

STEPS = ["data", "generate", "pipeline", "train", "scan", "recommend", "users"]


def _recommendation_count() -> int:
    engine = get_engine()
    Recommendation.__table__.create(engine, checkfirst=True)
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(Recommendation)) or 0


def _alert_count() -> int:
    engine = get_engine()
    Anomaly.__table__.create(engine, checkfirst=True)
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(Anomaly)) or 0


def status() -> dict[str, bool]:
    """Which steps are already done (their outputs exist)."""
    base = settings.data_dir / "processed"
    return {
        "data": (settings.data_dir / "raw" / "train.csv").exists(),
        "generate": (base / "sales.csv").exists() and (base / "items.csv").exists(),
        "pipeline": runner.paths()["features"].exists(),
        "train": (models_dir() / "forecasts.parquet").exists() and (models_dir() / "benchmark.json").exists(),
        # the scan writes files AND fills the alert ledger in the database: a new database needs a new scan
        "scan": (base / "risk" / "metrics.json").exists() and _alert_count() > 0,
        "recommend": _recommendation_count() > 0,
        "users": False,  # ensure_users() is idempotent, so it always runs
    }


def _run_generate() -> None:
    path = ROOT_DIR / "ml" / "prepare_data.py"
    spec = importlib.util.spec_from_file_location("prepare_data", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(42)


def _run_recommend() -> str:
    from app.platform import config_store
    from app.recommend import engine, service

    inv = config_store.get_all()["inventory"]
    params = engine.Params(lead_time=inv["lead_time_days"], service_z=inv["service_level_z"], overstock_cover_days=inv["overstock_cover_days"],
                           target_cover_days=inv["target_cover_days"], max_discount=inv["max_discount_pct"] / 100)
    return f"{service.generate_and_store(params)['generated']} recommendations"


def run_step(name: str, quick: bool) -> str:
    if name == "data":
        raise SystemExit(
            f"Missing {settings.data_dir / 'raw' / 'train.csv'}.\n"
            "Download the Kaggle 'Store Item Demand Forecasting Challenge' (train.csv) and place it in data/raw/ - it is not redistributed with this project."
        )
    if name == "generate":
        _run_generate()
        return "synthetic data written"
    if name == "pipeline":
        s = runner.run_pipeline()
        if s["status"] != "complete":
            raise SystemExit(f"Pipeline failed: {s.get('error')}")
        return f"{s['features']['rows']:,} feature rows, quality {s['quality']['quality_score']}/100"
    if name == "train":
        from app.forecasting import train

        s = train.run_training(quick=quick)
        if s["status"] != "complete":
            raise SystemExit(f"Training failed: {s.get('error')}")
        return f"trained in {s['duration_s']}s"
    if name == "scan":
        from app.platform import config_store
        from app.risk import scan

        cfg = config_store.get_all()["risk"]
        s = scan.run_scan(cfg["contamination"], cfg["z_threshold"])
        if s["status"] != "complete":
            raise SystemExit(f"Scan failed: {s.get('error')}")
        return f"{scan.read_metrics()['alerts']} alerts"
    if name == "recommend":
        return _run_recommend()
    if name == "users":
        n = ensure_users()
        return f"{n} demo accounts created" if n else "users already exist"
    raise ValueError(name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-run every step even if its output exists")
    ap.add_argument("--quick", action="store_true", help="smaller/faster model training (for smoke tests, not for results)")
    ap.add_argument("--only", choices=STEPS, help="run a single step")
    args = ap.parse_args(argv)

    done = status()
    if not done["data"]:
        run_step("data", args.quick)  # exits with instructions
    todo = [args.only] if args.only else [s for s in STEPS if args.force or not done[s]]
    todo = [s for s in todo if s != "data"]
    if not todo:
        print("Nothing to do: everything is already built. Use --force to rebuild.")
        return 0
    for s in todo:
        t0 = time.perf_counter()
        print(f"[{STEPS.index(s) + 1}/{len(STEPS)}] {s} ...", flush=True)
        print(f"      done: {run_step(s, args.quick)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    print("Bootstrap complete. Start the API (uvicorn app.main:app) and the frontend, or use docker compose up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
