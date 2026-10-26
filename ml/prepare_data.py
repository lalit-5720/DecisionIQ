"""Build the DecisionIQ analysis dataset.

Real data  : data/raw/train.csv (Kaggle Store Item Demand Forecasting) -> `sales` is never modified.
Synthetic  : store/item master, list price, promotions, festival calendar, inventory,
             logistics costs and labelled anomalies (injected into the *billed* columns only).

Usage: python ml/prepare_data.py [--seed 42]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

STORES = [
    ("Bengaluru Indiranagar", "Bengaluru"),
    ("Bengaluru Whitefield", "Bengaluru"),
    ("Bengaluru Jayanagar", "Bengaluru"),
    ("Bengaluru Koramangala", "Bengaluru"),
    ("Mysuru Vijayanagar", "Mysuru"),
    ("Mysuru Central", "Mysuru"),
    ("Mangaluru Hub", "Mangaluru"),
    ("Mangaluru Kadri", "Mangaluru"),
    ("Hubballi Hub", "Hubballi"),
    ("Belagavi Camp", "Belagavi"),
]

# (category, price range INR, cost ratio range)
CATEGORIES = [
    ("Consumer Tech", (8000, 35000), (0.80, 0.90)),
    ("Home Appliances", (2500, 12000), (0.70, 0.82)),
    ("Packaged Food", (60, 600), (0.72, 0.85)),
    ("Ethnic Apparel", (700, 4500), (0.50, 0.68)),
    ("Beverages", (20, 400), (0.65, 0.80)),
]

# Approximate festival dates (festival -> dates). Window flag = [-3, +1] days around each.
FESTIVALS = {
    "Sankranti": ["2013-01-14", "2014-01-14", "2015-01-15", "2016-01-15", "2017-01-14", "2018-01-14"],
    "Ugadi": ["2013-04-11", "2014-03-31", "2015-03-21", "2016-04-08", "2017-03-29", "2018-03-18"],
    "Ganesh Chaturthi": ["2013-09-09", "2014-08-29", "2015-09-17", "2016-09-05", "2017-08-25", "2018-09-13"],
    "Dussehra": ["2013-10-13", "2014-10-03", "2015-10-22", "2016-10-11", "2017-09-30", "2018-10-19"],
    "Diwali": ["2013-11-03", "2014-10-23", "2015-11-11", "2016-10-30", "2017-10-19", "2018-11-07"],
}


def build_masters(rng, n_stores, n_items):
    stores = pd.DataFrame(
        {"store": np.arange(1, n_stores + 1), "name": [s[0] for s in STORES][:n_stores],
         "city": [s[1] for s in STORES][:n_stores]}
    )
    rows = []
    for item in range(1, n_items + 1):
        cat, (lo, hi), (clo, chi) = CATEGORIES[(item - 1) % len(CATEGORIES)]
        price = round(float(np.exp(rng.uniform(np.log(lo), np.log(hi)))) / 10) * 10 or lo
        rows.append(
            {"item": item, "sku_code": f"SKU-{cat[:3].upper()}-{item:04d}", "name": f"{cat} Item {item}",
             "category": cat, "base_price": float(price),
             "unit_cost": round(price * float(rng.uniform(clo, chi)), 2),
             "festival_markdown": bool(rng.random() < 0.5)}
        )
    return stores, pd.DataFrame(rows)


def festival_table(dates):
    rows = [{"festival": f, "date": pd.Timestamp(d)} for f, ds in FESTIVALS.items() for d in ds]
    fest = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    flag = pd.Series("", index=dates)
    for _, r in fest.iterrows():
        flag[(dates >= r["date"] - pd.Timedelta(days=3)) & (dates <= r["date"] + pd.Timedelta(days=1))] = r["festival"]
    return fest, flag


def simulate_inventory(sales_mat, rng_unused=None, lead_time=3):
    """Periodic-review (s, S) policy on real demand. sales_mat: (series, days)."""
    n, d = sales_mat.shape
    df = pd.DataFrame(sales_mat.T.astype(float))
    avg = df.rolling(28, min_periods=1).mean().shift(1).bfill().to_numpy().T
    std = df.rolling(28, min_periods=2).std().shift(1).bfill().fillna(0).to_numpy().T
    safety = 0.8 * std * np.sqrt(lead_time)  # lean safety stock so some stock-outs occur
    rop = np.ceil(avg * lead_time + safety)
    order_up_to = np.ceil(avg * (lead_time + 7) + safety)

    on_hand = order_up_to[:, 0].copy()
    pipeline = np.zeros((n, d + lead_time + 1))
    on_hand_out = np.zeros((n, d))
    on_order_out = np.zeros((n, d))
    short_out = np.zeros((n, d))
    for t in range(d):
        on_hand += pipeline[:, t]
        demand = sales_mat[:, t]
        short = np.maximum(demand - on_hand, 0)
        on_hand = np.maximum(on_hand - demand, 0)
        on_order = pipeline[:, t + 1 : t + lead_time + 1].sum(axis=1)
        need = (on_hand + on_order) <= rop[:, t]
        qty = np.where(need, np.maximum(order_up_to[:, t] - on_hand - on_order, 0), 0)
        pipeline[:, t + lead_time] += qty
        on_hand_out[:, t] = on_hand
        on_order_out[:, t] = pipeline[:, t + 1 : t + lead_time + 1].sum(axis=1)
        short_out[:, t] = short
    return on_hand_out, on_order_out, rop, short_out


def main(seed: int) -> None:
    rng = np.random.default_rng(seed)
    OUT.mkdir(parents=True, exist_ok=True)

    train = pd.read_csv(RAW / "train.csv", parse_dates=["date"]).sort_values(["store", "item", "date"])
    n_stores, n_items = train["store"].nunique(), train["item"].nunique()
    dates = pd.DatetimeIndex(sorted(train["date"].unique()))
    n_days, n_series = len(dates), n_stores * n_items
    assert len(train) == n_series * n_days, "train.csv is not a complete store x item x date grid"

    stores, items = build_masters(rng, n_stores, n_items)
    fest, fest_flag = festival_table(dates)

    sales_mat = train["sales"].to_numpy().reshape(n_series, n_days)
    item_idx = np.tile(np.arange(n_items), n_stores)  # series order: store-major, item-minor

    # --- price & promotions (synthetic) ---
    years = (dates - dates[0]).days.to_numpy() / 365.0
    list_price = items["base_price"].to_numpy()[item_idx][:, None] * (1 + 0.03 * years[None, :])
    n_weeks = n_days // 7 + 1
    week_disc = rng.choice([0.0, 0.05, 0.10, 0.15, 0.20], size=(n_series, n_weeks), p=[0.90, 0.03, 0.04, 0.02, 0.01])
    discount = np.repeat(week_disc, 7, axis=1)[:, :n_days]
    is_fest = (fest_flag.to_numpy() != "")[None, :]
    fest_md = items["festival_markdown"].to_numpy()[item_idx][:, None]
    discount = np.where(is_fest & fest_md, np.maximum(discount, 0.10), discount)
    price = np.round(list_price * (1 - discount), 2)
    unit_cost = items["unit_cost"].to_numpy()[item_idx][:, None] * (1 + 0.03 * years[None, :])

    # --- inventory (synthetic policy on real demand) ---
    on_hand, on_order, rop, short = simulate_inventory(sales_mat)
    # current-stock scenario: ~8% of series received an oversized supplier shipment on the last day (excess stock)
    excess = rng.random(n_series) < 0.08
    on_hand[excess, -1] = np.ceil(on_hand[excess, -1] * rng.uniform(8, 25, excess.sum()) + 20)
    # ... and ~10% had a delayed supplier delivery: low stock and nothing on order (stock-out risk scenario)
    delayed = (~excess) & (rng.random(n_series) < 0.10)
    on_hand[delayed, -1] = np.floor(on_hand[delayed, -1] * rng.uniform(0.1, 0.4, delayed.sum()))
    on_order[delayed, -1] = 0

    # --- billed columns + injected anomalies (labelled) ---
    units_billed = sales_mat.astype(float).copy()
    net_price = price.copy()
    label = np.full((n_series, n_days), "", dtype=object)

    def pick(k):
        return rng.integers(0, n_series, k), rng.integers(7, n_days - 7, k)

    s, t = pick(200)  # duplicate billing: invoice counted twice
    units_billed[s, t] = sales_mat[s, t] * 2
    label[s, t] = "duplicate_billing"
    s, t = pick(150)  # margin erosion: sold below cost
    net_price[s, t] = np.round(unit_cost[s, t] * rng.uniform(0.70, 0.95, len(s)), 2)
    label[s, t] = "margin_erosion"
    s, t = pick(150)  # demand drop: 3-5 day slump
    for si, ti in zip(s, t):
        L = int(rng.integers(3, 6))
        units_billed[si, ti : ti + L] = np.floor(sales_mat[si, ti : ti + L] * rng.uniform(0.15, 0.40))
        label[si, ti : ti + L] = "demand_drop"

    # --- logistics cost (weekly per store) with cost spikes ---
    wk = pd.date_range(dates[0], dates[-1], freq="7D")
    log = pd.DataFrame([(st, d) for st in stores["store"] for d in wk], columns=["store", "week_start"])
    log["freight_cost"] = np.round(rng.normal(42000, 4000, len(log)).clip(20000), 2)
    log["anomaly_type"] = ""
    spike = rng.choice(len(log), 40, replace=False)
    log.loc[spike, "freight_cost"] = np.round(log.loc[spike, "freight_cost"] * rng.uniform(1.30, 1.60, 40), 2)
    log.loc[spike, "anomaly_type"] = "cost_spike"

    # --- assemble long table ---
    store_col = np.repeat(stores["store"].to_numpy(), n_items * n_days)
    item_col = np.tile(np.repeat(items["item"].to_numpy(), n_days), n_stores)
    date_col = np.tile(dates.to_numpy(), n_series)
    sales = pd.DataFrame(
        {
            "date": date_col, "store": store_col, "item": item_col,
            "sales": sales_mat.ravel(),
            "list_price": np.round(list_price, 2).ravel(),
            "discount_pct": np.round(discount * 100).astype(int).ravel(),
            "net_price": net_price.ravel(),
            "units_billed": units_billed.ravel().astype(int),
            "promo_flag": (discount >= 0.05).astype(int).ravel(),
            "festival": np.tile(fest_flag.to_numpy(), n_series),
            "on_hand": on_hand.ravel().astype(int),
            "on_order": on_order.ravel().astype(int),
            "reorder_point": rop.ravel().astype(int),
            "units_short": short.ravel().astype(int),
            "anomaly_type": label.ravel(),
        }
    )
    sales["festival_flag"] = (sales["festival"] != "").astype(int)
    sales["revenue"] = np.round(sales["units_billed"] * sales["net_price"], 2)
    sales["is_anomaly"] = (sales["anomaly_type"] != "").astype(int)

    stores.to_csv(OUT / "stores.csv", index=False)
    items.to_csv(OUT / "items.csv", index=False)
    fest.to_csv(OUT / "festivals.csv", index=False)
    log.to_csv(OUT / "logistics_costs.csv", index=False)
    sales.to_csv(OUT / "sales.csv", index=False)

    print(f"sales rows      : {len(sales):,}")
    print(f"anomaly rows    : {int(sales['is_anomaly'].sum()):,}  {sales[sales.is_anomaly == 1].anomaly_type.value_counts().to_dict()}")
    print(f"cost spikes     : {len(spike)} of {len(log)} weekly logistics rows")
    print(f"stockout days   : {(sales['units_short'] > 0).mean():.2%}")
    print(f"promo days      : {sales['promo_flag'].mean():.2%}; festival days: {sales['festival_flag'].mean():.2%}")
    print(f"written to      : {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    main(ap.parse_args().seed)
