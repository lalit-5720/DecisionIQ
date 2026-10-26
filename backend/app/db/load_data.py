"""Load data/processed/*.csv into the database.

Usage (from backend/): python -m app.db.load_data [--reset]
"""
import argparse

import pandas as pd

from app.core.config import settings
from app.db.models import Base, Festival, Item, LogisticsCost, Sale, Store
from app.db.session import get_engine

PROCESSED = settings.data_dir / "processed"

# table model, csv file, date columns
SOURCES = [
    (Store, "stores.csv", []),
    (Item, "items.csv", []),
    (Festival, "festivals.csv", ["date"]),
    (LogisticsCost, "logistics_costs.csv", ["week_start"]),
    (Sale, "sales.csv", ["date"]),
]


def main(reset: bool) -> None:
    engine = get_engine()
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    for model, fname, date_cols in SOURCES:
        path = PROCESSED / fname
        if not path.exists():
            raise SystemExit(f"{path} missing - run `python ml/prepare_data.py` first")
        df = pd.read_csv(path, parse_dates=date_cols, keep_default_na=False, na_values=[])
        for c in date_cols:
            df[c] = df[c].dt.date
        cols = [c.name for c in model.__table__.columns if c.name in df.columns]
        df[cols].to_sql(model.__tablename__, engine, if_exists="append", index=False, chunksize=20000)
        print(f"{model.__tablename__:<16} {len(df):>9,} rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop all tables first")
    main(ap.parse_args().reset)
