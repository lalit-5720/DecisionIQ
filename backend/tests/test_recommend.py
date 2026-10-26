import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.recommend import engine

client = TestClient(app)
LAST = pd.Timestamp("2017-12-31")

# (store, item): (on_hand, on_order)
STOCK = {
    (1, 1): (500, 0),     # healthy: 25 days of cover
    (2, 1): (5, 0),       # about to stock out
    (3, 1): (3000, 0),    # massive excess of the same item -> transfer donor
    (1, 2): (2000, 0),    # perishable overstock -> markdown
    (2, 2): (300, 0), (3, 2): (300, 0),
}


def make_state():
    stores = pd.DataFrame({"store": [1, 2, 3], "name": ["Blr", "Mys", "Blr2"], "city": ["Bengaluru", "Mysuru", "Bengaluru"]})
    items = pd.DataFrame({"item": [1, 2], "sku_code": ["T-1", "F-2"], "name": ["Phone", "Biscuit"],
                          "category": ["Consumer Tech", "Packaged Food"], "unit_cost": [60.9, 60.9]})
    fdates = pd.date_range(LAST + pd.Timedelta(days=1), periods=90)
    fc = pd.DataFrame([(s, i, d, 20.0, 12.0, 28.0) for (s, i) in STOCK for d in fdates], columns=["store", "item", "date", "yhat", "lower", "upper"])
    cur = pd.DataFrame([(s, i, 20, oh, oo, 100.0, 100.0) for (s, i), (oh, oo) in STOCK.items()],
                       columns=["store", "item", "sales", "on_hand", "on_order", "list_price", "net_price"])
    hdates = pd.date_range(LAST - pd.Timedelta(days=89), LAST)
    hist = pd.DataFrame([(d, s, i, 20, 100.0) for (s, i) in STOCK for d in hdates], columns=["date", "store", "item", "sales", "net_price"])
    return {"fc": fc, "cur": cur, "hist": hist, "last_date": LAST, "items": items, "stores": stores}


def by(recs, kind, store=None, item=None):
    return [r for r in recs if r["kind"] == kind and (store is None or r["store"] == store) and (item is None or r["item"] == item)]


def test_reorder_only_for_understocked_series():
    recs = engine.generate(make_state())
    assert not by(recs, "reorder", store=1, item=1)  # healthy
    assert not by(recs, "reorder", store=2, item=1)  # need is covered by a transfer instead (see next test)
    # without the donor the same store gets a reorder
    st = make_state()
    st["cur"].loc[(st["cur"].store == 3) & (st["cur"].item == 1), "on_hand"] = 100
    recs = engine.generate(st)
    r = by(recs, "reorder", store=2, item=1)[0]
    # order-up-to = demand over lead+review (10d x 20) + 1.65 * sigma * sqrt(10), sigma = (28 - 20) / 1.96
    assert r["payload"]["qty"] == int(np.ceil(200 + 1.65 * (8 / 1.96) * np.sqrt(10) - 5))
    assert r["impact_inr"] > 0 and r["payload"]["calc"]


def test_transfer_moves_surplus_to_stockout_store():
    recs = engine.generate(make_state())
    t = by(recs, "transfer")
    assert len(t) == 1 and (t[0]["store"], t[0]["store_to"], t[0]["item"]) == (3, 2, 1)
    assert 200 < t[0]["payload"]["qty"] < 260
    assert t[0]["impact_label"] == "capital released"


def test_markdown_for_perishable_overstock_only():
    recs = engine.generate(make_state())
    m = by(recs, "markdown")
    perishable = by(m, "markdown", store=1, item=2)
    assert perishable and 0 < perishable[0]["payload"]["discount_pct"] <= 20 and perishable[0]["impact_inr"] > 0
    assert not by(m, "markdown", store=1, item=1)  # healthy 25 days of cover
    st = make_state()
    st["cur"].loc[st["cur"].item == 1, "net_price"] = 71.0  # thin margin: no discount is allowed
    assert not by(engine.generate(st), "markdown", item=1)


def test_markdown_value_and_edit():
    inp = {"avg": 20, "pos": 2000, "price": 100, "cost": 70, "elasticity": -1.1, "horizon": 30, "carry": 0.25, "obsolescence": 0.9}
    v5, v10 = engine.markdown_value(inp, 0.05), engine.markdown_value(inp, 0.10)
    assert v10["lift"] > v5["lift"] > 0 and v10["units_new"] > v5["units_new"]
    rec = by(engine.generate(make_state()), "markdown", store=1, item=2)[0]
    before = rec["impact_inr"]
    edited = engine.edit(rec, discount_pct=5)
    assert edited["payload"]["discount_pct"] == 5 and "5%" in edited["title"] and edited["impact_inr"] != before


def test_budget_shift_moves_from_weak_to_strong_cell():
    st = make_state()
    # make store 2 / Packaged Food clearly the fastest-growing cell
    st["fc"].loc[(st["fc"].store == 2) & (st["fc"].item == 2), ["yhat", "lower", "upper"]] = [60.0, 50.0, 70.0]
    recs = engine.generate(st)
    b = by(recs, "budget")
    assert b and b[0]["payload"]["amount"] > 0 and b[0]["store_to"] == 2 and b[0]["impact_inr"] > 0


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 't.db'}")
    proc = tmp_path / "processed"
    (proc / "models").mkdir(parents=True)
    st = make_state()
    st["fc"].to_parquet(proc / "models" / "forecasts.parquet")
    st["items"].to_csv(proc / "items.csv", index=False)
    st["stores"].to_csv(proc / "stores.csv", index=False)
    hist = st["hist"].merge(st["cur"][["store", "item", "on_hand", "on_order", "list_price"]], on=["store", "item"])
    hist.to_csv(proc / "sales.csv", index=False)


def test_api_flow(files):
    assert client.post("/api/recommendations/generate").json()["generated"] >= 3
    s = client.get("/api/recommendations/summary").json()
    assert s["counts"]["Pending"] == s["total"] and s["pending_value"] > 0 and s["execution_rate"] is None

    recs = client.get("/api/recommendations?kind=transfer").json()["recommendations"]
    assert recs and recs[0]["store_name"] and recs[0]["payload"]["calc"]
    t = recs[0]
    u = client.patch(f"/api/recommendations/{t['id']}", json={"quantity": 50, "status": "Approved"}).json()
    assert u["status"] == "Approved" and u["payload"]["qty"] == 50 and "50 units" in u["title"]
    assert client.patch(f"/api/recommendations/{t['id']}", json={"discount_pct": 5}).status_code == 422
    assert client.patch(f"/api/recommendations/{t['id']}", json={"status": "Nope"}).status_code == 422

    md = client.get("/api/recommendations?kind=markdown").json()["recommendations"][0]
    out = client.post("/api/recommendations/bulk", json={"ids": [md["id"]], "status": "Dismissed"}).json()
    assert out["updated"] == 1
    s = client.get("/api/recommendations/summary").json()
    assert s["counts"]["Approved"] == 1 and s["execution_rate"] == 50 and s["approved_value"] > 0

    csv = client.get("/api/recommendations/export.csv?status=Approved").text.strip().splitlines()
    assert len(csv) == 2 and "transfer" in csv[1]

    assert client.post("/api/recommendations/generate").json()["decisions_kept"] == 2  # decisions survive regeneration
    assert client.get("/api/recommendations?status=Approved").json()["recommendations"][0]["payload"]["qty"] == 50


def test_generate_requires_forecasts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'e.db'}")
    assert client.post("/api/recommendations/generate").status_code == 409
    assert client.get("/api/recommendations").json() == {"recommendations": []}
