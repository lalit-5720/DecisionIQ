"""What-if simulator: forecast + levers -> Monte Carlo demand and inventory simulation.

Scenario demand per series/day = baseline forecast x price response x marketing uplift x exogenous shocks,
with forecast uncertainty (series sigma) and elasticity uncertainty sampled per run. Inventory follows a
(reorder point, order-up-to) policy with the chosen lead time and safety stock, so stock-outs emerge from the simulation.
Baseline and scenario use the SAME random numbers, so differences come from the levers, not from noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.config import settings
from app.recommend import engine as rec_engine

MARKETING_ELASTICITY = 0.10   # demand elasticity to marketing spend (assumption)
MARKETING_BASE_SHARE = 0.025  # baseline marketing spend as share of revenue (same assumption as the recommendation engine)
FEST_SHOCK_PCT, FEST_START, FEST_LEN = 0.45, 9, 7   # festival demand shock: +45% for 7 days from day 10
COMPETITOR_SHOCK = -0.05
ELASTICITY_SD = 0.25
REVIEW_DAYS = 7
CARRY_RATE = 0.25
Z_BASE, LEAD_BASE = 1.65, 3
MARKETING_LEVELS = {"Low": 0.0, "Medium": 0.15, "High": 0.35}


@dataclass
class Levers:
    price_pct: float = 0.0            # change in retail price, percent (-20..20)
    voucher_pct: float = 0.0          # extra festive markdown voucher, percent (0..30)
    marketing: str = "Low"            # Low | Medium | High  -> +0 / +15 / +35% marketing budget
    safety_stock_units: float | None = None  # total units for the scope; None = baseline policy
    lead_time_days: int = LEAD_BASE   # supplier replenishment SLA
    festival_shock: bool = False
    competitor_match: bool = False


@dataclass
class Scope:
    series: pd.DataFrame
    F: np.ndarray            # (S, H) baseline forecast
    sigma: np.ndarray        # (S,)
    dates: pd.DatetimeIndex
    label: str = ""
    key: tuple = field(default_factory=tuple)


_cache: dict = {}


def _state():
    p = settings.data_dir / "processed"
    stamp = tuple((p / f).stat().st_mtime if (p / f).exists() else 0 for f in ("sales.csv", "models/forecasts.parquet"))
    key = ("state", str(settings.data_dir), stamp)
    if key not in _cache:
        for k in [k for k in _cache if k[0] == "state"]:
            del _cache[k]
        st = rec_engine.load_state()
        S, F, sig = rec_engine.build_series(st)
        dates = pd.DatetimeIndex(sorted(st["fc"]["date"].unique()))
        _cache[key] = (S, F, dates)
    return _cache[key]


def get_scope(store=None, item=None, category=None, horizon=30) -> Scope:
    S, F, dates = _state()
    mask = np.ones(len(S), bool)
    if store is not None:
        mask &= (S["store"] == store).to_numpy()
    if item is not None:
        mask &= (S["item"] == item).to_numpy()
    if category:
        mask &= (S["category"] == category).to_numpy()
    if not mask.any():
        raise ValueError("No series match the selected scope")
    h = min(horizon, F.shape[1])
    sub = S[mask].reset_index(drop=True)
    label = " · ".join(filter(None, [
        sub["item_name"].iloc[0] if item is not None else (category or "All products"),
        sub["store_name"].iloc[0] if store is not None else "all stores"]))
    return Scope(sub, np.clip(F[mask][:, :h], 0, None), sub["sigma"].to_numpy(), dates[:h], label, (store, item, category, h))


def baseline_safety_stock(scope: Scope) -> float:
    return float((Z_BASE * scope.sigma * np.sqrt(LEAD_BASE)).sum())


def _elasticity(scope: Scope) -> np.ndarray:
    el = rec_engine.Params().elasticity
    return scope.series["category"].map(el).fillna(-1.4).to_numpy()


def simulate(scope: Scope, lv: Levers, runs: int = 300, seed: int = 7) -> dict:
    S, H = scope.F.shape
    rng = np.random.default_rng(seed)
    eps = _elasticity(scope)
    price0 = scope.series["net_price"].to_numpy()
    cost = scope.series["cost"].to_numpy()
    stores = scope.series["store"].to_numpy()
    mu = scope.F
    avg_mu = np.maximum(mu.mean(axis=1), 0.5)
    eff = (1 + lv.price_pct / 100) * (1 - lv.voucher_pct / 100) - 1
    budget = MARKETING_LEVELS[lv.marketing]
    m_mkt = (1 + budget) ** MARKETING_ELASTICITY
    shock = np.ones(H)
    if lv.festival_shock:
        shock[FEST_START : FEST_START + FEST_LEN] *= 1 + FEST_SHOCK_PCT
    if lv.competitor_match:
        shock *= 1 + COMPETITOR_SHOCK
    price = price0 * (1 + lv.price_pct / 100) * (1 - lv.voucher_pct / 100)
    L = int(lv.lead_time_days)
    mean_after = mu * m_mkt * shock[None, :]
    ss_total = baseline_safety_stock(scope) if lv.safety_stock_units is None else float(lv.safety_stock_units)
    ss = ss_total * avg_mu / avg_mu.sum()

    chunk = int(max(1, min(runs, 3_000_000 // (S * H))))
    out = {k: [] for k in ("units", "revenue", "cogs", "holding", "so_frac", "so_any", "lost", "d_day", "f_day", "so_day", "peak")}
    store_ids = np.unique(stores)
    per_store = {s: {"units": [], "so": [], "demand": []} for s in store_ids}
    done = 0
    while done < runs:
        n = min(chunk, runs - done)
        z = rng.standard_normal((n, S, H)).astype(np.float32)
        e_noise = rng.standard_normal((n, 1)) * ELASTICITY_SD
        done += n
        m_price = (1 + eff) ** (eps[None, :] + e_noise)                        # (n, S)
        mean_d = mean_after[None] * m_price[:, :, None]                         # (n, S, H)
        sd = scope.sigma[None, :, None] * np.sqrt(mean_d / avg_mu[None, :, None])
        d = np.maximum(mean_d + sd * z, 0.0)
        # inventory policy
        rop = mean_d.mean(axis=2) * L + ss[None, :]
        order_up_to = rop + mean_d.mean(axis=2) * REVIEW_DAYS
        on_hand = np.repeat(scope.series["on_hand"].to_numpy(float)[None], n, axis=0)
        pipe = np.zeros((n, S, H + L + 2))
        pipe[:, :, 1] = scope.series["on_order"].to_numpy(float)[None]
        fulfilled, oh_sum = np.zeros((n, S, H)), np.zeros((n, S))
        for t in range(H):
            on_hand = on_hand + pipe[:, :, t]
            f = np.minimum(d[:, :, t], on_hand)
            on_hand = on_hand - f
            fulfilled[:, :, t] = f
            oh_sum += on_hand
            position = on_hand + pipe[:, :, t + 1 : t + L + 1].sum(axis=2)
            q = np.where(position <= rop, order_up_to - position, 0.0)
            pipe[:, :, t + L] += np.maximum(q, 0)
        lost = d - fulfilled
        stocked_out = lost > 1e-6
        out["units"].append(fulfilled.sum(axis=(1, 2)))
        out["revenue"].append((fulfilled.sum(axis=2) * price[None]).sum(axis=1))
        out["cogs"].append((fulfilled.sum(axis=2) * cost[None]).sum(axis=1))
        out["holding"].append((oh_sum / H * cost[None]).sum(axis=1) * CARRY_RATE * H / 365)
        out["so_frac"].append(stocked_out.mean(axis=(1, 2)))          # share of series-days with a stock-out
        out["so_any"].append(stocked_out.any(axis=2).mean(axis=1))    # share of series with at least one stock-out
        out["lost"].append(lost.sum(axis=(1, 2)))
        out["d_day"].append(d.sum(axis=1))
        out["f_day"].append(fulfilled.sum(axis=1))
        out["so_day"].append(stocked_out.mean(axis=1))
        out["peak"].append(d.sum(axis=1).max(axis=1))
        for s in store_ids:
            m = stores == s
            per_store[s]["units"].append(fulfilled[:, m].sum(axis=(1, 2)))
            per_store[s]["so"].append(stocked_out[:, m].mean(axis=(1, 2)))
            per_store[s]["demand"].append(d[:, m].sum(axis=(1, 2)))
    cat = {k: np.concatenate(v) if v[0].ndim == 1 else np.vstack(v) for k, v in out.items()}
    return {"cat": cat, "per_store": {s: {k: np.concatenate(v) for k, v in d.items()} for s, d in per_store.items()},
            "ss_total": ss_total, "ss": ss, "budget": budget, "eff": eff, "eps_index": float(np.average(eps, weights=price0 * avg_mu)),
            "mean_daily": float((mean_after * np.mean([1.0])).sum(axis=0).mean())}


def _kpis(sim: dict, base_revenue: float, budget_pct: float) -> dict:
    c = sim["cat"]
    rev, cogs = c["revenue"].mean(), c["cogs"].mean()
    mkt = MARKETING_BASE_SHARE * base_revenue * (1 + budget_pct)
    gp = rev - cogs
    return {
        "revenue": float(rev), "units": float(c["units"].mean()), "gross_profit": float(gp),
        "gross_margin_pct": float(gp / rev * 100) if rev else 0.0,
        "marketing_spend": float(mkt), "holding_cost": float(c["holding"].mean()),
        "net_profit": float(gp - mkt - c["holding"].mean()),
        "stockout_risk_pct": float(c["so_frac"].mean() * 100), "stockout_any_pct": float(c["so_any"].mean() * 100),
        "lost_units": float(c["lost"].mean()),
        "peak_p90": float(np.percentile(c["peak"], 90)), "peak_mean": float(c["peak"].mean()),
        "units_p10": float(np.percentile(c["units"], 10)), "units_p90": float(np.percentile(c["units"], 90)),
        "elasticity_index": sim["eps_index"], "safety_stock_units": float(sim["ss_total"]),
        "safety_buffer_days": float(sim["ss_total"] / max(c["d_day"].sum(axis=1).mean() / c["d_day"].shape[1], 1e-6)),
    }


def verdict(scn: dict, base: dict, lv: Levers) -> dict:
    d_rev = (scn["revenue"] / base["revenue"] - 1) * 100 if base["revenue"] else 0
    d_units = (scn["units"] / base["units"] - 1) * 100 if base["units"] else 0
    d_np = scn["net_profit"] - base["net_profit"]
    so_d = scn["stockout_risk_pct"] - base["stockout_risk_pct"]
    parts = []
    changes = []
    if lv.price_pct:
        changes.append(f"{'lowering' if lv.price_pct < 0 else 'raising'} price by {abs(lv.price_pct):g}%")
    if lv.voucher_pct:
        changes.append(f"a {lv.voucher_pct:g}% festive voucher")
    if lv.marketing != "Low":
        changes.append(f"{lv.marketing.lower()} marketing push")
    if lv.festival_shock:
        changes.append("a festival demand spike")
    if lv.competitor_match:
        changes.append("competitor price matching")
    head = ("With " + ", ".join(changes)) if changes else "At baseline settings"
    parts.append(f"{head}, units sold change by {d_units:+.1f}% and revenue by {d_rev:+.1f}%; net profit moves by {'-' if d_np < 0 else '+'}₹{abs(d_np):,.0f}.")
    parts.append(f"Daily stock-out probability is {scn['stockout_risk_pct']:.1f}% ({so_d:+.1f} pts vs baseline {base['stockout_risk_pct']:.1f}%), "
                 f"with a safety stock of {scn['safety_stock_units']:.0f} units (~{scn['safety_buffer_days']:.1f} days of demand).")
    if d_np > 0 and so_d <= 5:
        rating = "Highly favorable" if d_np > 0.05 * abs(base["net_profit"]) else "Favorable"
    elif d_np > 0:
        rating = "Favorable, but watch stock-outs"
    else:
        rating = "Unfavorable" if d_np < -0.02 * abs(base["net_profit"]) else "Neutral"
    return {"rating": rating, "text": " ".join(parts)}


def run(scope: Scope, lv: Levers, runs: int = 300, seed: int = 7) -> dict:
    key = ("base", str(settings.data_dir), scope.key, runs, seed, id(_state()[0]))
    if key not in _cache:
        _cache[key] = simulate(scope, Levers(), runs, seed)
    base_sim = _cache[key]
    scn_sim = simulate(scope, lv, runs, seed)
    bk = _kpis(base_sim, base_sim["cat"]["revenue"].mean(), 0.0)
    sk = _kpis(scn_sim, base_sim["cat"]["revenue"].mean(), scn_sim["budget"])
    delta = {k: sk[k] - bk[k] for k in sk}

    bc, sc = base_sim["cat"], scn_sim["cat"]
    price_s = scope.series["net_price"].to_numpy() * (1 + lv.price_pct / 100) * (1 - lv.voucher_pct / 100)
    avg_price_b = bc["revenue"].mean() / max(bc["units"].mean(), 1e-6)
    avg_price_s = sc["revenue"].mean() / max(sc["units"].mean(), 1e-6)
    traj = {
        "dates": [d.strftime("%Y-%m-%d") for d in scope.dates],
        "baseline_units": bc["f_day"].mean(axis=0).round(1).tolist(), "scenario_units": sc["f_day"].mean(axis=0).round(1).tolist(),
        "band_lo": np.percentile(sc["d_day"], 10, axis=0).round(1).tolist(), "band_hi": np.percentile(sc["d_day"], 90, axis=0).round(1).tolist(),
        "baseline_cum_revenue": np.cumsum(bc["f_day"].mean(axis=0) * avg_price_b).round(0).tolist(),
        "scenario_cum_revenue": np.cumsum(sc["f_day"].mean(axis=0) * avg_price_s).round(0).tolist(),
        "baseline_stockout": (bc["so_day"].mean(axis=0) * 100).round(2).tolist(), "scenario_stockout": (sc["so_day"].mean(axis=0) * 100).round(2).tolist(),
    }
    names = scope.series.drop_duplicates("store").set_index("store")["store_name"]
    ps = scn_sim["per_store"]
    stores = []
    for s, v in sorted(ps.items(), key=lambda kv: -kv[1]["demand"].mean())[:6]:
        risk = float(v["so"].mean() * 100)
        share = float(scn_sim["ss"][(scope.series["store"] == s).to_numpy()].sum())
        stores.append({"store": int(s), "name": names[s], "units": round(float(v["units"].mean()), 0), "buffer_units": round(share, 0),
                       "stockout_risk_pct": round(risk, 1), "status": "Safe" if risk < 2 else "Watch" if risk < 6 else "At risk"})
    return {"scope": scope.label, "n_series": len(scope.series), "horizon": len(scope.dates), "runs": runs,
            "baseline": bk, "scenario": sk, "delta": delta, "trajectory": traj, "stores": stores,
            "verdict": verdict(sk, bk, lv), "levers": lv.__dict__ | {"marketing_budget_pct": scn_sim["budget"] * 100},
            "baseline_safety_stock": baseline_safety_stock(scope)}
