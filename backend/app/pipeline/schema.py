"""Column mapping: cross-walk an arbitrary business file to the canonical schema."""
import pandas as pd

REQUIRED = ["date", "store", "item", "sales"]
OPTIONAL = ["net_price", "promo_flag"]

TARGET_LABELS = {
    "date": "Transaction Timestamp",
    "store": "Store Location",
    "item": "Product / SKU",
    "sales": "Units Sold",
    "net_price": "Unit Price (INR)",
    "promo_flag": "Promotion Flag",
}

ALIASES = {
    "date": ["date", "txn_date", "timestamp", "order_date", "invoice_date"],
    "store": ["store", "store_id", "outlet", "outlet_id", "branch"],
    "item": ["item", "sku", "sku_code", "product", "product_id", "item_id"],
    "sales": ["sales", "qty_sold", "units", "units_sold", "quantity", "demand"],
    "net_price": ["net_price", "unit_price", "price", "net_amt"],
    "promo_flag": ["promo_flag", "promo", "promotion"],
}


def _valid_rate(series: pd.Series, target: str) -> float:
    if len(series) == 0:
        return 0.0
    if target == "date":
        ok = pd.to_datetime(series, errors="coerce").notna()
    elif target in ("sales", "net_price", "promo_flag"):
        ok = pd.to_numeric(series, errors="coerce").notna()
    else:
        ok = series.notna()
    return float(ok.mean())


def detect_mapping(df: pd.DataFrame) -> dict:
    """Returns {"mapping": [...], "missing_required": [...]} using case-insensitive alias matching."""
    lowered = {c.lower().strip(): c for c in df.columns}
    mapping, used = [], set()
    for target in REQUIRED + OPTIONAL:
        source = next((lowered[a] for a in ALIASES[target] if a in lowered and lowered[a] not in used), None)
        if source is None:
            continue
        used.add(source)
        col = df[source]
        sample = col.dropna().iloc[0] if col.notna().any() else None
        mapping.append(
            {
                "source": source,
                "target": target,
                "target_label": TARGET_LABELS[target],
                "dtype": str(col.dtype),
                "sample": None if sample is None else str(sample),
                "valid_pct": round(_valid_rate(col, target) * 100, 1),
                "required": target in REQUIRED,
            }
        )
    found = {m["target"] for m in mapping}
    return {"mapping": mapping, "missing_required": [t for t in REQUIRED if t not in found]}


def apply_mapping(df: pd.DataFrame, mapping: list[dict]) -> pd.DataFrame:
    rename = {m["source"]: m["target"] for m in mapping}
    return df[list(rename)].rename(columns=rename)
