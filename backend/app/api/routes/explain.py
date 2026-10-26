import csv
import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.explain import service

router = APIRouter(prefix="/explain", tags=["explainability"])


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except service.ExplainError as e:
        raise HTTPException(409 if "train" in str(e).lower() or "serving model" in str(e) else 422, str(e))


@router.get("/options")
def options() -> dict:
    return _run(service.options)


@router.get("/local")
def local(store: int, item: int, date: str) -> dict:
    return _run(service.explain_local, store, item, date)


@router.get("/global")
def global_view() -> dict:
    return _run(service.global_importance)


@router.get("/dependence")
def dependence(feature: str = Query("dow"), store: int | None = None, item: int | None = None) -> dict:
    return _run(service.dependence, feature, store, item)


@router.get("/governance")
def governance() -> dict:
    return _run(service.governance)


@router.get("/export.csv")
def export(store: int, item: int, date: str):
    e = _run(service.explain_local, store, item, date)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["store", "item", "date", "feature", "feature_value", "shap_units", "share_pct"])
    for r in e["contributions"]:
        w.writerow([store, item, e["date"], r["feature"], round(r["value"], 3), round(r["shap"], 3), r["share_pct"]])
    w.writerow([store, item, e["date"], "BASE_VALUE", "", e["base_value"], ""])
    w.writerow([store, item, e["date"], "PREDICTION", "", e["prediction"], ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=shap_explanation.csv"})
