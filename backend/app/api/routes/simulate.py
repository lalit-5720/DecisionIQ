from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Scenario
from app.db.session import get_db, get_engine
from app.platform import audit
from app.simulate import engine

router = APIRouter(prefix="/simulate", tags=["simulator"])


class ScopeIn(BaseModel):
    store: int | None = None
    item: int | None = None
    category: str | None = None


class LeversIn(BaseModel):
    price_pct: float = Field(0, ge=-20, le=20)
    voucher_pct: float = Field(0, ge=0, le=30)
    marketing: Literal["Low", "Medium", "High"] = "Low"
    safety_stock_units: float | None = Field(None, ge=0)
    lead_time_days: int = Field(engine.LEAD_BASE, ge=1, le=30)
    festival_shock: bool = False
    competitor_match: bool = False


class RunIn(BaseModel):
    scope: ScopeIn = ScopeIn()
    horizon: int = Field(30, ge=7, le=90)
    levers: LeversIn = LeversIn()
    runs: int = Field(300, ge=50, le=2000)


def _scope(s: ScopeIn, horizon: int) -> engine.Scope:
    if not (settings.data_dir / "processed" / "models" / "forecasts.parquet").exists():
        raise HTTPException(409, "Train the forecasting models first")
    try:
        return engine.get_scope(s.store, s.item, s.category, horizon)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/baseline")
def baseline(store: int | None = None, item: int | None = None, category: str | None = None, horizon: int = 30) -> dict:
    sc = _scope(ScopeIn(store=store, item=item, category=category), horizon)
    ss = engine.baseline_safety_stock(sc)
    return {
        "label": sc.label, "n_series": len(sc.series), "horizon": len(sc.dates),
        "avg_daily_units": round(float(sc.F.sum(axis=0).mean()), 1), "baseline_safety_stock": round(ss),
        "safety_stock_max": round(max(ss * 3, 10)), "current_stock_units": int(sc.series["on_hand"].sum()),
        "elasticity_index": round(float(engine._elasticity(sc).mean()), 2),
        "reference": f"Forecast {sc.dates[0]:%d %b} – {sc.dates[-1]:%d %b %Y} ({engine.LEAD_BASE}-day lead time, 95% service level)",
    }


@router.post("/run")
def run(body: RunIn) -> dict:
    sc = _scope(body.scope, body.horizon)
    return engine.run(sc, engine.Levers(**body.levers.model_dump()), runs=body.runs)


def ensure_table(db: Session = Depends(get_db)) -> Session:
    Scenario.__table__.create(get_engine(), checkfirst=True)
    return db


class SaveIn(RunIn):
    name: str = Field(min_length=1, max_length=100)
    runs: int = Field(500, ge=50, le=2000)


def _row(s: Scenario) -> dict:
    r = s.results or {}
    return {"id": s.id, "name": s.name, "created_at": s.created_at.isoformat(timespec="seconds"), "scope": r.get("scope"),
            "scope_ids": s.levers.get("scope"), "horizon": s.levers.get("horizon"), "levers": s.levers.get("levers"),
            "scenario": r.get("scenario"), "baseline": r.get("baseline"), "verdict": r.get("verdict")}


@router.get("/scenarios")
def list_scenarios(db: Session = Depends(ensure_table)) -> dict:
    return {"scenarios": [_row(s) for s in db.scalars(select(Scenario).order_by(Scenario.created_at.desc()))]}


@router.post("/scenarios", status_code=201)
def save_scenario(body: SaveIn, db: Session = Depends(ensure_table)) -> dict:
    sc = _scope(body.scope, body.horizon)
    res = engine.run(sc, engine.Levers(**body.levers.model_dump()), runs=body.runs)
    snap = {k: res[k] for k in ("scope", "scenario", "baseline", "verdict")}
    s = Scenario(name=body.name.strip(), levers={"scope": body.scope.model_dump(), "horizon": body.horizon, "levers": body.levers.model_dump()}, results=snap)
    db.add(s)
    db.commit()
    audit.record(f"Saved what-if scenario '{s.name}'", "simulation", f"scenario #{s.id}")
    return _row(s)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: int, db: Session = Depends(ensure_table)) -> None:
    s = db.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(404, "Scenario not found")
    db.delete(s)
    db.commit()
