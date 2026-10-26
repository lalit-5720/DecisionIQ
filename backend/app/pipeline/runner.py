"""Orchestrates upload -> mapping -> clean -> features and persists progress to pipeline_state.json."""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.pipeline.clean import clean
from app.pipeline.features import FEATURE_CATALOG, build_features
from app.pipeline.schema import apply_mapping, detect_mapping

STEPS = [
    ("upload", "Multi-Source Upload"),
    ("mapping", "Schema Mapping"),
    ("clean", "Clean & Validate"),
    ("features", "Feature Engineering"),
]
_lock = threading.Lock()


def paths():
    base = settings.data_dir
    return {
        "uploads": base / "uploads",
        "processed": base / "processed",
        "state": base / "processed" / "pipeline_state.json",
        "features": base / "processed" / "features.parquet",
    }


def load_any(path: Path, nrows: int | None = None) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, nrows=nrows)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, nrows=nrows)
    if ext == ".parquet":
        df = pd.read_parquet(path)
        return df.head(nrows) if nrows else df
    raise ValueError(f"Unsupported file type: {ext}")


def find_source() -> Path:
    p = paths()
    for cand in sorted(p["uploads"].glob("current.*")) if p["uploads"].exists() else []:
        return cand
    for cand in (p["processed"] / "sales.csv", settings.data_dir / "raw" / "train.csv"):
        if cand.exists():
            return cand
    raise FileNotFoundError("No data source found: upload a file or place train.csv in data/raw/")


def read_state() -> dict:
    p = paths()["state"]
    if not p.exists():
        return {"status": "idle", "steps": [{"key": k, "label": l, "status": "pending"} for k, l in STEPS]}
    return json.loads(p.read_text(encoding="utf-8"))


def _write(state: dict) -> None:
    p = paths()["state"]
    p.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    tmp.replace(p)


def _set(state: dict, key: str, status: str, detail: str = "") -> None:
    for s in state["steps"]:
        if s["key"] == key:
            s.update(status=status, detail=detail)
    _write(state)


def is_running() -> bool:
    return _lock.locked()


def run_pipeline() -> dict:
    if not _lock.acquire(blocking=False):
        return read_state()
    t0 = time.perf_counter()
    state = {"status": "running", "steps": [{"key": k, "label": l, "status": "pending"} for k, l in STEPS]}
    try:
        src = find_source()
        state["source"] = src.name
        _set(state, "upload", "active", src.name)
        raw = load_any(src)
        _set(state, "upload", "done", f"{len(raw):,} rows from {src.name}")

        _set(state, "mapping", "active")
        found = detect_mapping(raw)
        state["mapping"] = found["mapping"]
        if found["missing_required"]:
            raise ValueError(f"Schema gate failed: missing required columns {found['missing_required']}")
        mapped = apply_mapping(raw, found["mapping"])
        _set(state, "mapping", "done", f"{len(found['mapping'])} columns mapped")

        _set(state, "clean", "active")
        cleaned, stats = clean(mapped)
        state["quality"] = stats
        _set(state, "clean", "done", f"quality {stats['quality_score']}/100")

        _set(state, "features", "active")
        feats = build_features(cleaned)
        out = paths()["features"]
        out.parent.mkdir(parents=True, exist_ok=True)
        feats.to_parquet(out, index=False)
        state["features"] = {
            "rows": len(feats),
            "stores": int(feats["store"].nunique()),
            "items": int(feats["item"].nunique()),
            "date_min": feats["date"].min().date().isoformat(),
            "date_max": feats["date"].max().date().isoformat(),
            "catalog": FEATURE_CATALOG,
        }
        _set(state, "features", "done", f"{len(FEATURE_CATALOG)} features")
        state["status"] = "complete"
    except Exception as e:  # surfaced in the UI as a pipeline exception
        state["status"] = "failed"
        state["error"] = str(e)
        for s in state["steps"]:
            if s["status"] == "active":
                s["status"] = "failed"
                s["detail"] = str(e)
    finally:
        state["latency_s"] = round(time.perf_counter() - t0, 1)
        _write(state)
        _lock.release()
    return state
