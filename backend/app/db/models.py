from datetime import date, datetime

DateType = date  # `date` is shadowed by column attributes inside some models

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------- master & fact tables (loaded from data/processed) ----------
class Store(Base):
    __tablename__ = "stores"
    store: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(50))


class Item(Base):
    __tablename__ = "items"
    item: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    base_price: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float)
    festival_markdown: Mapped[bool] = mapped_column(Boolean)


class Festival(Base):
    __tablename__ = "festivals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    festival: Mapped[str] = mapped_column(String(50))
    date: Mapped[date] = mapped_column(Date)


class Sale(Base):
    """One row per store x item x day. `sales` is real (Kaggle); other columns are synthetic."""

    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    store: Mapped[int] = mapped_column(ForeignKey("stores.store"))
    item: Mapped[int] = mapped_column(ForeignKey("items.item"))
    sales: Mapped[int] = mapped_column(Integer)
    list_price: Mapped[float] = mapped_column(Float)
    discount_pct: Mapped[int] = mapped_column(Integer)
    net_price: Mapped[float] = mapped_column(Float)
    units_billed: Mapped[int] = mapped_column(Integer)
    promo_flag: Mapped[int] = mapped_column(Integer)
    festival: Mapped[str] = mapped_column(String(50), default="")
    festival_flag: Mapped[int] = mapped_column(Integer)
    on_hand: Mapped[int] = mapped_column(Integer)
    on_order: Mapped[int] = mapped_column(Integer, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer)
    units_short: Mapped[int] = mapped_column(Integer)
    anomaly_type: Mapped[str] = mapped_column(String(30), default="")
    revenue: Mapped[float] = mapped_column(Float)
    is_anomaly: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_sales_store_item_date", "store", "item", "date"),
        Index("ix_sales_date", "date"),
    )


class LogisticsCost(Base):
    __tablename__ = "logistics_costs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store: Mapped[int] = mapped_column(ForeignKey("stores.store"))
    week_start: Mapped[date] = mapped_column(Date)
    freight_cost: Mapped[float] = mapped_column(Float)
    anomaly_type: Mapped[str] = mapped_column(String(30), default="")


# ---------- application tables (filled by later phases) ----------
class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(50))
    version: Mapped[str] = mapped_column(String(30))
    mae: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    mape: Mapped[float | None] = mapped_column(Float)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    params: Mapped[dict | None] = mapped_column(JSON)


class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id"))
    store: Mapped[int] = mapped_column(ForeignKey("stores.store"))
    item: Mapped[int] = mapped_column(ForeignKey("items.item"))
    date: Mapped[date] = mapped_column(Date)
    yhat: Mapped[float] = mapped_column(Float)
    lower: Mapped[float] = mapped_column(Float)
    upper: Mapped[float] = mapped_column(Float)


class Anomaly(Base):
    """Alert ledger. One row per detected event (consecutive flagged days of one series form one alert)."""

    __tablename__ = "anomalies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store: Mapped[int] = mapped_column(ForeignKey("stores.store"))
    item: Mapped[int | None] = mapped_column(ForeignKey("items.item"))
    date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[DateType | None] = mapped_column(Date)
    anomaly_type: Mapped[str] = mapped_column(String(30))
    score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(10))
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="Open")
    assignee: Mapped[str | None] = mapped_column(String(100))
    explanation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_anomalies_status_sev", "status", "severity"),)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # reorder | transfer | markdown | budget
    store: Mapped[int | None] = mapped_column(ForeignKey("stores.store"))
    store_to: Mapped[int | None] = mapped_column(Integer)
    item: Mapped[int | None] = mapped_column(ForeignKey("items.item"))
    category: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(250))
    detail: Mapped[str | None] = mapped_column(Text)
    impact_inr: Mapped[float] = mapped_column(Float, default=0)
    impact_label: Mapped[str | None] = mapped_column(String(60))
    confidence: Mapped[float] = mapped_column(Float, default=0)
    payload: Mapped[dict | None] = mapped_column(JSON)  # editable inputs + calculation audit trail
    status: Mapped[str] = mapped_column(String(20), default="Pending")  # Pending | Approved | Dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    levers: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    template: Mapped[str] = mapped_column(String(50))
    format: Mapped[str] = mapped_column(String(10))  # pdf | xlsx | json
    scope: Mapped[str | None] = mapped_column(String(200))
    file_path: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="Ready")
    generated_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(150), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))  # Admin | Manager | Analyst
    password_hash: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """Append-only, hash-chained event log: each entry hashes the previous one, so edits are detectable."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(30))
    entity: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


class Setting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
