"""Editable platform configuration, stored in the DB. Defaults apply until a section is saved.

`APPLIED` lists the keys that actually change behaviour today; the rest is stored configuration
for features that are not implemented yet (scheduler, delivery channels, retention jobs).
"""
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Setting
from app.db.session import get_engine


class RiskCfg(BaseModel):
    z_threshold: float = Field(3.0, ge=1.5, le=6.0)          # spike / sustained-drop z-score
    contamination: float = Field(0.0015, gt=0, le=0.05)      # share of rows each ML detector flags
    auto_suppress_vendor: bool = False
    slack_critical_alerts: bool = True


class InventoryCfg(BaseModel):
    overstock_cover_days: int = Field(45, ge=15, le=120)
    target_cover_days: int = Field(21, ge=7, le=60)
    max_discount_pct: float = Field(20, ge=5, le=40)
    lead_time_days: int = Field(3, ge=1, le=21)
    service_level_z: float = Field(1.65, ge=0.5, le=3.0)


class RetrainCfg(BaseModel):
    cadence: str = "Every Sunday at 02:00 (off-peak)"
    promotion_mape_delta: float = Field(0.5, ge=0, le=5)
    holdout_days: int = 90


class ComplianceCfg(BaseModel):
    pii_anonymisation: bool = True
    retention_months: int = Field(36, ge=6, le=120)


class ReportsCfg(BaseModel):
    cadence: str = "Weekly"
    email: bool = True
    slack: bool = True
    erp_sftp: bool = False
    pdf: bool = True
    xlsx: bool = True
    json_stream: bool = False


SECTIONS = {"risk": RiskCfg, "inventory": InventoryCfg, "retraining": RetrainCfg, "compliance": ComplianceCfg, "reports": ReportsCfg}
APPLIED = {"risk": ["z_threshold", "contamination"],
           "inventory": ["overstock_cover_days", "target_cover_days", "max_discount_pct", "lead_time_days", "service_level_z"]}


def defaults() -> dict:
    return {k: m().model_dump() for k, m in SECTIONS.items()}


def get_all(db: Session | None = None) -> dict:
    cfg = defaults()
    engine = get_engine()
    Setting.__table__.create(engine, checkfirst=True)
    own = db is None
    db = db or Session(engine)
    try:
        for row in db.query(Setting).all():
            if row.key in cfg:
                cfg[row.key] = SECTIONS[row.key](**{**cfg[row.key], **row.value}).model_dump()
    finally:
        if own:
            db.close()
    return cfg


def save_section(db: Session, section: str, patch: dict) -> dict:
    merged = SECTIONS[section](**{**get_all(db)[section], **patch}).model_dump()  # validates ranges
    row = db.get(Setting, section)
    if row:
        row.value, row.updated_at = merged, datetime.utcnow()
    else:
        db.add(Setting(key=section, value=merged))
    db.commit()
    return merged


def reset(db: Session) -> None:
    db.query(Setting).delete()
    db.commit()


