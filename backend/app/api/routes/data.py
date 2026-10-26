import pandas as pd
from fastapi import APIRouter, HTTPException

from app.core.config import settings

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/summary")
def dataset_summary() -> dict:
    """Quick profile of the raw store-item demand dataset."""
    path = settings.data_dir / "raw" / "train.csv"
    if not path.exists():
        raise HTTPException(404, "data/raw/train.csv not found")
    df = pd.read_csv(path, parse_dates=["date"])
    return {
        "rows": len(df),
        "stores": int(df["store"].nunique()),
        "items": int(df["item"].nunique()),
        "date_min": df["date"].min().date().isoformat(),
        "date_max": df["date"].max().date().isoformat(),
        "total_units": int(df["sales"].sum()),
        "missing_values": int(df.isna().sum().sum()),
    }
