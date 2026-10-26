import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile

from app.auth.deps import require

from app.pipeline import runner
from app.platform import audit
from app.pipeline.schema import detect_mapping

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

MAX_BYTES = 250 * 1024 * 1024
ALLOWED = {".csv", ".xlsx", ".xls", ".parquet"}


@router.get("/status")
def status() -> dict:
    state = runner.read_state()
    state["running"] = runner.is_running()
    return state


@router.post("/upload", dependencies=[Depends(require("upload_data"))])
async def upload(file: UploadFile = File(...)) -> dict:
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in ALLOWED:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Use CSV, XLSX or Parquet.")
    updir = runner.paths()["uploads"]
    updir.mkdir(parents=True, exist_ok=True)
    for old in updir.glob("current.*"):
        old.unlink()
    dest = updir / f"current{ext}"
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                f.close()
                dest.unlink()
                raise HTTPException(413, "File exceeds the 250MB batch limit")
            f.write(chunk)
    try:
        found = detect_mapping(runner.load_any(dest, nrows=1000))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not read file: {e}")
    if found["missing_required"]:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"Missing required columns: {found['missing_required']}")
    audit.record(f"Uploaded data file {file.filename} ({size // 1024} KB)", "data", file.filename)
    return {"filename": file.filename, "size_bytes": size, **found}


@router.post("/run", status_code=202, dependencies=[Depends(require("upload_data"))])
def run(background: BackgroundTasks) -> dict:
    if runner.is_running():
        raise HTTPException(409, "Pipeline already running")
    audit.record("Started data pipeline run", "data")
    background.add_task(runner.run_pipeline)
    return {"status": "started"}


@router.get("/diagnostics")
def diagnostics() -> dict:
    """Human-readable failure details of the last data-pipeline run (for the Forecasting States page)."""
    s = runner.read_state()
    lines = [f"[{s.get('updated_at', '-')}] pipeline status: {s.get('status')}  source: {s.get('source', '-')}  duration: {s.get('latency_s', '-')}s"]
    for st in s.get("steps", []):
        lines.append(f"[STEP] {st['label']}: {st['status']}" + (f" - {st['detail']}" if st.get("detail") else ""))
    if s.get("error"):
        lines.append(f"[CRITICAL] {s['error']}")
        lines.append("[POLICY] Automatic fall-through rejected. Model training halted to prevent poisoned downstream forecasts.")
    for m in s.get("mapping", []):
        lines.append(f"[MAPPING] {m['source']} -> {m['target']} ({m['dtype']}, valid {m['valid_pct']}%)")
    return {"status": s.get("status"), "error": s.get("error"), "failed": s.get("status") == "failed", "steps": s.get("steps", []),
            "source": s.get("source"), "log": "\n".join(lines)}


@router.get("/preview")
def preview(n: int = Query(4, ge=1, le=50)) -> dict:
    path = runner.paths()["features"]
    if not path.exists():
        raise HTTPException(404, "No processed data yet - run the pipeline")
    df = pd.read_parquet(path).tail(n)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return {"columns": list(df.columns), "rows": df.round(3).where(df.notna(), None).to_dict("records")}
