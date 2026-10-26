"""Prescriptive engine: turns forecasts + current stock into reorder, transfer, markdown and budget recommendations.

All maths is explicit and returned as an audit trail (`payload["calc"]`) so every recommendation can be justified.
Assumptions that are NOT in the data (lead time, service level, elasticities, marketing budget share) live in `Params`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm

from app.core.config import settings
from app.risk.detect import COST_DRIFT

CITY_COORDS = {"Bengaluru": (12.97, 77.59), "Mysuru": (12.30, 76.64), "Mangaluru": (12.91, 74.86),
               "Hubballi": (15.36, 75.12), "Belagavi": (15.85, 74.50)}


@dataclass
class Params:
    lead_time: int = 3
    review_days: int = 7
    service_z: float = 1.65            # 95% cycle service level
    overstock_cover_days: int = 45
    target_cover_days: int = 21
    max_discount: float = 0.20
    min_margin: float = 0.05
    carrying_rate: float = 0.25        # annual inventory carrying cost
    # shelf-life / sell-through window (days) and share of stock still unsold after it that is written off (assumptions)
    shelf_days: dict = field(default_factory=lambda: {
        "Packaged Food": 30, "Beverages": 45, "Ethnic Apparel": 90, "Consumer Tech": 120, "Home Appliances": 180})
    obsolescence: dict = field(default_factory=lambda: {
        "Packaged Food": 0.9, "Beverages": 0.8, "Ethnic Apparel": 0.5, "Consumer Tech": 0.4, "Home Appliances": 0.2})
    transfer_min_qty: int = 10
    budget_share: float = 0.025        # monthly marketing budget as share of revenue (assumption)
    budget_shift: float = 0.20
    base_roas: float = 3.0
    elasticity: dict = field(default_factory=lambda: {
        "Consumer Tech": -1.8, "Home Appliances": -1.4, "Packaged Food": -1.1, "Ethnic Apparel": -1.6, "Beverages": -0.9})
    max_per_type: dict = field(default_factory=lambda: {"reorder": 30, "transfer": 15, "markdown": 15, "budget": 3})


def _km(c1: str, c2: str) -> float:
    if c1 == c2:
        return 8.0
    (a, b), (c, d) = CITY_COORDS.get(c1, (0, 0)), CITY_COORDS.get(c2, (0, 0))
    p = math.pi / 180
    h = 0.5 - math.cos((c - a) * p) / 2 + math.cos(a * p) * math.cos(c * p) * (1 - math.cos((d - b) * p)) / 2
    return round(12742 * math.asin(math.sqrt(h)), 0)


def load_state() -> dict:
    base = settings.data_dir / "processed"
    fc = pd.read_parquet(base / "models" / "forecasts.parquet")
    cols = ["date", "store", "item", "sales", "on_hand", "on_order", "list_price", "net_price"]
    sales = pd.read_csv(base / "sales.csv", usecols=cols, parse_dates=["date"])
    last = sales["date"].max()
    cur = sales[sales["date"] == last].drop(columns="date")
    hist = sales[sales["date"] > last - pd.Timedelta(days=90)]
    return {
        "fc": fc, "cur": cur, "hist": hist, "last_date": last,
        "items": pd.read_csv(base / "items.csv"), "stores": pd.read_csv(base / "stores.csv"),
    }


def build_series(state: dict) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    fc = state["fc"].sort_values(["store", "item", "date"])
    keys = fc[["store", "item"]].drop_duplicates().reset_index(drop=True)
    H = fc.groupby(["store", "item"]).size().iloc[0]
    F = fc["yhat"].to_numpy().reshape(len(keys), H)
    sig = ((fc["upper"] - fc["yhat"]) / 1.96).to_numpy().reshape(len(keys), H).mean(axis=1)
    items, stores = state["items"].set_index("item"), state["stores"].set_index("store")
    S = keys.merge(state["cur"], on=["store", "item"], how="left")
    years = (state["last_date"] - pd.Timestamp("2013-01-01")).days / 365.0
    S["cost"] = S["item"].map(items["unit_cost"]) * (1 + COST_DRIFT * years)
    S["sku"], S["item_name"], S["category"] = (S["item"].map(items[c]) for c in ("sku_code", "name", "category"))
    S["store_name"], S["city"] = S["store"].map(stores["name"]), S["store"].map(stores["city"])
    S["pos"] = S["on_hand"] + S["on_order"]
    S["avg14"] = np.maximum(F[:, :14].mean(axis=1), 0.5)
    S["avg30"] = np.maximum(F[:, :30].mean(axis=1), 0.5)
    S["sigma"] = sig
    return S, F, sig


def _conf(rel: float) -> float:
    return round(float(np.clip(1 - 0.5 * rel, 0.5, 0.99)), 2)


def _inr(v: float) -> str:
    return f"₹{v:,.0f}"


# ---------------------------------------------------------------- reorder
def reorder_candidates(S, F, p: Params) -> pd.DataFrame:
    L, R = p.lead_time, p.review_days
    dL, dLR = F[:, :L].sum(axis=1), F[:, : L + R].sum(axis=1)
    sig = S["sigma"].to_numpy()
    sd_cov = sig * np.sqrt(L + R)
    rop = dL + p.service_z * sig * np.sqrt(L)
    order_up_to = dLR + p.service_z * sd_cov
    pos = S["pos"].to_numpy()
    k = (pos - dLR) / np.maximum(sd_cov, 1e-6)
    shortage = sd_cov * (norm.pdf(k) - k * (1 - norm.cdf(k)))  # expected units short without action
    out = S.assign(dL=dL, dLR=dLR, rop=rop, order_up_to=order_up_to, shortage=shortage,
                   need=np.ceil(np.maximum(order_up_to - pos, 0)))
    out["runout_days"] = out["on_hand"] / out["avg14"]
    return out[(pos < rop) & (out["need"] > 0)]


def _reorder_rec(r, qty: int, p: Params) -> dict:
    impact = float(r.shortage * r.net_price)
    scale = min(1.0, qty / r.need) if r.need else 1.0
    calc = [
        ("Forecast demand, next 14 days (avg/day)", f"{r.avg14:.1f} units"),
        ("Lead time + review period", f"{p.lead_time} + {p.review_days} days"),
        ("Forecast demand over cover", f"{r.dLR:.0f} units"),
        (f"Safety stock (z={p.service_z}, σ/day={r.sigma:.1f})", f"{p.service_z * r.sigma * math.sqrt(p.lead_time + p.review_days):.0f} units"),
        ("Order-up-to level", f"{r.order_up_to:.0f} units"),
        ("Inventory position (on hand + on order)", f"{r.on_hand} + {r.on_order} = {r.pos} units"),
        ("Reorder quantity = order-up-to − position", f"{qty} units"),
        ("Expected shortage without action (normal loss fn)", f"{r.shortage:.1f} units × {_inr(r.net_price)} = {_inr(impact)}"),
    ]
    return {
        "kind": "reorder", "store": int(r.store), "store_to": None, "item": int(r.item), "category": r.category,
        "title": f"Reorder {qty} units of {r.item_name} for {r.store_name}",
        "detail": f"Stock {r.on_hand} (+{r.on_order} on order) covers ~{r.runout_days:.1f} days against forecast demand of {r.avg14:.0f}/day; "
                  f"position is below the reorder point of {r.rop:.0f}.",
        "impact_inr": round(impact * scale, 2), "impact_label": "protected revenue",
        "confidence": _conf(r.sigma / r.avg14),
        "payload": {"qty": int(qty), "base_qty": int(r.need), "sku": r.sku, "runout_days": round(float(r.runout_days), 1),
                    "base_impact": round(impact, 2), "calc": calc},
    }


# ---------------------------------------------------------------- transfer
def transfers(S, reorder_df, p: Params) -> tuple[list[dict], dict, dict]:
    """Move surplus from overstocked stores to stores that need a reorder, same item, nearest first."""
    surplus = (S["pos"] - p.target_cover_days * S["avg30"]).clip(lower=0)
    over = S[(S["pos"] / S["avg30"] > p.overstock_cover_days) & (surplus >= p.transfer_min_qty)]
    donors = {(int(r["store"]), int(r["item"])): float(surplus[i]) for i, r in over.iterrows()}
    needs = {(int(r.store), int(r.item)): float(r.need) for r in reorder_df.itertuples()}
    recs, moved_out, moved_in = [], {}, {}
    sidx = S.set_index(["store", "item"])
    for (to_store, item), need in sorted(needs.items(), key=lambda kv: -kv[1]):
        cands = sorted(((s, q) for (s, i), q in donors.items() if i == item and q >= p.transfer_min_qty and s != to_store),
                       key=lambda sq: _km(sidx.loc[(sq[0], item), "city"], sidx.loc[(to_store, item), "city"]))
        for from_store, avail in cands:
            qty = int(min(avail, need))
            if qty < p.transfer_min_qty:
                continue
            a, b = sidx.loc[(from_store, item)], sidx.loc[(to_store, item)]
            km = _km(a["city"], b["city"])
            impact = qty * float(a["cost"])
            recs.append({
                "kind": "transfer", "store": int(from_store), "store_to": int(to_store), "item": int(item), "category": a["category"],
                "title": f"Transfer {qty} units of {a['item_name']} from {a['store_name']} to {b['store_name']}",
                "detail": f"{a['store_name']} holds {a['pos'] / a['avg30']:.0f} days of cover while {b['store_name']} is below its reorder point. "
                          f"Moving stock {km:.0f} km avoids a fresh purchase and frees capital.",
                "impact_inr": round(impact, 2), "impact_label": "capital released",
                "confidence": _conf(a["sigma"] / a["avg30"]),
                "payload": {"qty": qty, "base_qty": qty, "sku": a["sku"], "km": km, "unit_cost": round(float(a["cost"]), 2),
                            "calc": [("Donor inventory position", f"{a['pos']:.0f} units ({a['pos'] / a['avg30']:.0f} days of cover)"),
                                     (f"Target cover ({p.target_cover_days} days × {a['avg30']:.1f}/day)", f"{p.target_cover_days * a['avg30']:.0f} units"),
                                     ("Transferable surplus", f"{avail:.0f} units"),
                                     ("Recipient need (order-up-to − position)", f"{need:.0f} units"),
                                     ("Quantity moved = min(surplus, need)", f"{qty} units"),
                                     ("Capital released = qty × unit cost", f"{qty} × {_inr(a['cost'])} = {_inr(impact)}")]},
            })
            donors[(from_store, item)] -= qty
            moved_out[(from_store, item)] = moved_out.get((from_store, item), 0) + qty
            moved_in[(to_store, item)] = moved_in.get((to_store, item), 0) + qty
            need -= qty
            if need < p.transfer_min_qty:
                break
    return recs, moved_out, moved_in


# ---------------------------------------------------------------- markdown
def markdown_value(inp: dict, d: float) -> dict:
    """Profit effect of discount d over the horizon with a constant-elasticity demand response."""
    lift = (1 - d) ** inp["elasticity"] - 1
    units_base = inp["avg"] * inp["horizon"]
    units_new = min(inp["avg"] * (1 + lift) * inp["horizon"], inp["pos"])
    price_new = inp["price"] * (1 - d)
    d_profit = units_new * (price_new - inp["cost"]) - units_base * (inp["price"] - inp["cost"])
    extra = max(units_new - units_base, 0)
    carry_saved = inp["carry"] / 365 * inp["cost"] * extra * inp["horizon"] / 2
    unsold_base, unsold_new = max(inp["pos"] - units_base, 0), max(inp["pos"] - units_new, 0)
    writeoff_avoided = inp["obsolescence"] * inp["cost"] * (unsold_base - unsold_new)
    return {"lift": lift, "units_new": units_new, "units_base": units_base, "price_new": price_new,
            "d_profit": d_profit, "carry_saved": carry_saved, "writeoff_avoided": writeoff_avoided,
            "value": d_profit + carry_saved + writeoff_avoided}


def markdowns(S, moved_out, p: Params) -> list[dict]:
    recs = []
    for r in S.itertuples():
        pos = r.pos - moved_out.get((int(r.store), int(r.item)), 0)
        if pos / r.avg30 <= p.overstock_cover_days:
            continue
        inp = {"avg": float(r.avg30), "pos": float(pos), "price": float(r.net_price), "cost": float(r.cost),
               "elasticity": p.elasticity.get(r.category, -1.4), "horizon": p.shelf_days.get(r.category, 60),
               "carry": p.carrying_rate, "obsolescence": p.obsolescence.get(r.category, 0.3)}
        best = None
        for d in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
            if d > p.max_discount or inp["price"] * (1 - d) < inp["cost"] * (1 + p.min_margin):
                continue
            v = markdown_value(inp, d)
            if v["value"] > 0 and (best is None or v["value"] > best[1]["value"]):
                best = (d, v)
        if not best:
            continue
        d, v = best
        recs.append({
            "kind": "markdown", "store": int(r.store), "store_to": None, "item": int(r.item), "category": r.category,
            "title": f"Apply {d * 100:.0f}% markdown on {r.item_name} at {r.store_name}",
            "detail": f"{pos:.0f} units on hand/order = {pos / r.avg30:.0f} days of cover (target {p.target_cover_days}). "
                      f"A {d * 100:.0f}% discount (₹{inp['price']:,.0f} → ₹{v['price_new']:,.0f}) lifts demand ~{v['lift'] * 100:.0f}% and clears stock faster.",
            "impact_inr": round(v["value"], 2), "impact_label": "margin & carrying-cost gain",
            "confidence": round(_conf(r.sigma / r.avg30) * 0.9, 2),
            "payload": {"discount_pct": round(d * 100, 1), "inputs": inp, "sku": r.sku,
                        "calc": _markdown_calc(inp, d, v)},
        })
    return recs


def _markdown_calc(inp, d, v):
    return [("Inventory position", f"{inp['pos']:.0f} units = {inp['pos'] / inp['avg']:.0f} days of cover"),
            (f"Assumed price elasticity ε", f"{inp['elasticity']}"),
            (f"Demand lift = (1−{d:.2f})^ε − 1", f"{v['lift'] * 100:+.1f}%"),
            (f"Units sold in {inp['horizon']} days: base → new", f"{v['units_base']:.0f} → {v['units_new']:.0f}"),
            ("Gross-profit change", _inr(v["d_profit"])),
            (f"Carrying cost saved ({inp['carry'] * 100:.0f}%/yr)", _inr(v["carry_saved"])),
            (f"Write-off avoided ({inp['obsolescence'] * 100:.0f}% of stock unsold after {inp['horizon']}d)", _inr(v["writeoff_avoided"])),
            ("Net value", _inr(v["value"]))]


# ---------------------------------------------------------------- budget
def budget_shifts(S, state, p: Params) -> list[dict]:
    hist = state["hist"].merge(S[["store", "item", "category", "cost"]], on=["store", "item"])
    hist["rev"] = hist["sales"] * hist["net_price"]
    last30 = hist[hist["date"] > state["last_date"] - pd.Timedelta(days=30)]
    fc = state["fc"].merge(S[["store", "item", "category", "net_price", "cost"]], on=["store", "item"])
    fc30 = fc[fc["date"] < fc["date"].min() + pd.Timedelta(days=30)]
    cell = hist.groupby(["store", "category"]).agg(rev90=("rev", "sum")).join(
        last30.groupby(["store", "category"])["sales"].sum().rename("u30")).join(
        fc30.groupby(["store", "category"])["yhat"].sum().rename("f30")).join(
        (1 - fc.groupby(["store", "category"]).apply(lambda g: (g["cost"] * g["yhat"]).sum() / max((g["net_price"] * g["yhat"]).sum(), 1), include_groups=False)).rename("margin")).reset_index()
    cell["budget"] = cell["rev90"] / 3 * p.budget_share
    cell["growth"] = cell["f30"] / cell["u30"] - 1
    cell["eri"] = (1 + cell["growth"]).clip(lower=0.2) * cell["margin"]
    cell["roas"] = p.base_roas * cell["eri"] / cell["eri"].mean()
    names = S.drop_duplicates("store").set_index("store")["store_name"]
    cell = cell.sort_values("eri")
    donors, takers = cell.head(p.max_per_type["budget"]), cell.tail(p.max_per_type["budget"]).iloc[::-1]
    recs = []
    for d, t in zip(donors.itertuples(), takers.itertuples()):
        shift = d.budget * p.budget_shift
        gain = shift * (t.roas - d.roas)
        if gain <= 0:
            continue
        recs.append({
            "kind": "budget", "store": int(d.store), "store_to": int(t.store), "item": None, "category": f"{d.category} → {t.category}",
            "title": f"Shift {_inr(shift)}/month of marketing from {names[d.store]} {d.category} to {names[t.store]} {t.category}",
            "detail": f"{t.category} at {names[t.store]} has a higher expected return (forecast demand {t.growth * 100:+.0f}% vs recent) than "
                      f"{d.category} at {names[d.store]} ({d.growth * 100:+.0f}%).",
            "impact_inr": round(gain, 2), "impact_label": "incremental GMV (assumption-based)", "confidence": 0.6,
            "payload": {"amount": round(shift, 2), "calc": [
                ("Monthly marketing budget (assumed 2.5% of revenue)", f"{_inr(d.budget)} (donor)"),
                (f"Shift {p.budget_shift * 100:.0f}% of donor budget", _inr(shift)),
                ("Expected-return index = (1+forecast growth) × gross margin", f"{d.eri:.2f} (donor) vs {t.eri:.2f} (recipient)"),
                (f"ROAS proxy = {p.base_roas} × index / mean index", f"{d.roas:.2f}x vs {t.roas:.2f}x"),
                ("Incremental GMV = shift × (ROAS recipient − ROAS donor)", _inr(gain)),
                ("Caveat", "No ad-spend data exists; ROAS is a placeholder proportional to the expected-return index")]},
        })
    return recs


# ---------------------------------------------------------------- orchestration
def generate(state: dict | None = None, p: Params | None = None) -> list[dict]:
    p = p or Params()
    state = state or load_state()
    S, F, _ = build_series(state)
    ro = reorder_candidates(S, F, p)
    t_recs, moved_out, moved_in = transfers(S, ro, p)
    recs = list(t_recs)
    for r in ro.sort_values("shortage", ascending=False).itertuples():
        qty = int(r.need - moved_in.get((int(r.store), int(r.item)), 0))
        if qty > 0:
            recs.append(_reorder_rec(r, qty, p))
    recs += markdowns(S, moved_out, p) + budget_shifts(S, state, p)
    out = []
    for kind, cap in p.max_per_type.items():
        out += sorted((r for r in recs if r["kind"] == kind), key=lambda r: -r["impact_inr"])[:cap]
    return out


def edit(rec: dict, quantity: int | None = None, discount_pct: float | None = None) -> dict:
    """Recompute a recommendation after the manager edits its quantity or discount."""
    pl = dict(rec["payload"])
    if quantity is not None and rec["kind"] in ("reorder", "transfer"):
        old = pl["qty"]
        pl["qty"] = int(quantity)
        base_imp = pl.get("base_impact", rec["impact_inr"] * (pl["base_qty"] / max(old, 1)))
        rec["impact_inr"] = round(base_imp * min(1.0, quantity / max(pl["base_qty"], 1)), 2)
        rec["title"] = rec["title"].replace(f" {old} units", f" {quantity} units", 1)
    if discount_pct is not None and rec["kind"] == "markdown":
        d = discount_pct / 100
        v = markdown_value(pl["inputs"], d)
        pl["discount_pct"], pl["calc"] = discount_pct, _markdown_calc(pl["inputs"], d, v)
        rec["impact_inr"] = round(v["value"], 2)
        rec["title"] = rec["title"].replace(f"{rec['payload']['discount_pct']:.0f}%", f"{discount_pct:.0f}%", 1)
    rec["payload"] = pl
    return rec
