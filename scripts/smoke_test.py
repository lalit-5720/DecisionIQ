#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING DecisionIQ (stdlib only).

    python scripts/smoke_test.py                              # API on http://localhost:8000
    python scripts/smoke_test.py --base http://localhost:8080 # through the nginx container
    DIQ_DEMO_PASSWORD=... python scripts/smoke_test.py        # if you changed the demo password

It signs in as the three demo roles and checks the main workflows and the role restrictions.
Exit code 0 = all checks passed. It only reads data, except for one generated report and one login/audit entry per role.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

ACCOUNTS = {"Admin": "rajesh.nair@sunrisemart.in", "Manager": "priya.sharma@sunrisemart.in", "Analyst": "anil.kumar@sunrisemart.in"}
results: list[tuple[bool, str]] = []


def call(base, method, path, token=None, body=None, raw=False):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return r.status, data if raw else (json.loads(data) if data else None)
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, json.loads(data)
        except ValueError:
            return e.code, data


def check(name, ok, detail=""):
    results.append((bool(ok), name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--wait", type=int, default=0, help="seconds to wait for the API to become healthy")
    args = ap.parse_args()
    base, password = args.base.rstrip("/"), os.environ.get("DIQ_DEMO_PASSWORD", "DecisionIQ@2026")

    deadline = time.time() + args.wait
    while True:
        try:
            status, _ = call(base, "GET", "/api/health")
            if status == 200:
                break
        except OSError:
            pass
        if time.time() > deadline:
            print(f"API not reachable at {base}")
            return 2
        time.sleep(3)

    print("Access control")
    check("health is public", call(base, "GET", "/api/health")[0] == 200)
    check("data endpoints reject anonymous requests", call(base, "GET", "/api/dashboard/status")[0] == 401)
    check("wrong password is rejected", call(base, "POST", "/api/auth/login", body={"email": ACCOUNTS["Admin"], "password": "wrong-password-x"})[0] == 401)
    tokens = {}
    for role, email in ACCOUNTS.items():
        s, j = call(base, "POST", "/api/auth/login", body={"email": email, "password": password})
        check(f"{role} can sign in", s == 200 and j.get("user", {}).get("role") == role, f"status {s}")
        tokens[role] = j.get("access_token") if s == 200 else None
    if not all(tokens.values()):
        print("Cannot continue without all three sessions (is DIQ_DEMO_PASSWORD set correctly?)")
        return 1
    A, M, N = tokens["Admin"], tokens["Manager"], tokens["Analyst"]

    print("Role restrictions")
    check("Analyst cannot generate recommendations", call(base, "POST", "/api/recommendations/generate", N)[0] == 403)
    check("Analyst cannot read the audit trail", call(base, "GET", "/api/audit", N)[0] == 403)
    check("Analyst can read the dashboard", call(base, "GET", "/api/dashboard/status", N)[0] == 200)
    check("Manager cannot change risk thresholds", call(base, "PUT", "/api/settings/risk", M, {"z_threshold": 3.0})[0] == 403)
    check("Manager can read the audit trail", call(base, "GET", "/api/audit", M)[0] == 200)
    check("Manager cannot list users", call(base, "GET", "/api/users", M)[0] == 403)
    check("Admin can list users", call(base, "GET", "/api/users", A)[0] == 200)

    print("Workflows (as Admin)")
    s, d = call(base, "GET", "/api/dashboard/summary", A)
    check("dashboard has data", s == 200 and d.get("ready") and d["kpis"]["forecast_30d"] > 0, "run `python -m app.bootstrap` first" if s == 200 and not d.get("ready") else "")
    s, f = call(base, "GET", "/api/forecast/series?horizon=30&history_days=60", A)
    check("30-day forecast with confidence band", s == 200 and len(f["forecast"]) == 30 and f["forecast"][0]["upper"] >= f["forecast"][0]["lower"])
    s, models = call(base, "GET", "/api/forecast/models", A)
    mape = next((m["full_set"]["mape"] for m in models.get("models", []) if m["name"] == models.get("serving")), 99) if s == 200 else 99
    check("serving model MAPE within the 10-15% target", mape <= 15, f"{mape}")
    s, r = call(base, "GET", "/api/risk/alerts?page_size=3", A)
    check("risk alerts exist", s == 200 and r["total"] > 0)
    if s == 200 and r["alerts"]:
        s2, det = call(base, "GET", f"/api/risk/alerts/{r['alerts'][0]['id']}", A)
        check("alert detail has an explanation", s2 == 200 and det.get("explanation"))
    s, rc = call(base, "GET", "/api/recommendations", A)
    check("recommendations exist with an audit trail", s == 200 and rc["recommendations"] and rc["recommendations"][0]["payload"]["calc"])
    fw = (f["forecast"][4]["date"]) if s == 200 and f.get("forecast") else "2018-01-05"
    s, e = call(base, "GET", f"/api/explain/local?store=1&item=1&date={fw}", A)
    check("SHAP explanation balances exactly", s == 200 and e["balance_check"] < 1e-3, str(e)[:120])
    s, sim = call(base, "POST", "/api/simulate/run", A, {"runs": 100, "levers": {"price_pct": -5}})
    check("what-if simulation runs", s == 200 and sim["scenario"]["units"] > sim["baseline"]["units"])
    s, rep = call(base, "POST", "/api/reports/generate", A, {"template": "forecast_summary", "format": "pdf"})
    if s == 201:
        ds, body = call(base, "GET", f"/api/reports/{rep['id']}/download", A, raw=True)
        check("PDF report downloads and its checksum matches", ds == 200 and body[:4] == b"%PDF" and hashlib.sha256(body).hexdigest() == rep["sha256"])
    else:
        check("report generation", False, f"status {s}")
    s, v = call(base, "GET", "/api/audit/verify", A)
    check("audit hash chain verifies", s == 200 and v["ok"], str(v))

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
