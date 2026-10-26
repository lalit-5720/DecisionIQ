# Chapter 5 - Conclusion and Recommendations (draft)

## 5.1 Summary
Businesses collect sales, billing and inventory data but mostly use it to report the past. This project built **DecisionIQ**, a web-based decision-intelligence platform that connects four things that are usually separate:
demand forecasting, risk/anomaly detection, prescriptive recommendations and explainable dashboards, with role-based access and an audit trail.
It was developed on the Kaggle Store Item Demand data (913,000 real daily sales rows) extended with synthetic prices, inventory, costs and injected anomalies, following an iterative CRISP-DM process.

The implemented system:
- ingests CSV/Excel/Parquet files, maps and validates columns, cleans the data and engineers 12 features (100/100 quality score on the study data);
- benchmarks XGBoost, Prophet, SARIMA and LSTM on a 90-day recursive holdout and serves 90-day forecasts with confidence bands for 500 store-item series;
- detects billing and cost anomalies with an Isolation Forest, an autoencoder and Z-score rules combined by voting, and keeps an alert ledger with severity, status and forensic detail;
- converts forecasts and stock positions into reorder, transfer, markdown and budget recommendations with a visible calculation for each, plus a Monte Carlo what-if simulator;
- explains forecasts with exact TreeSHAP, plain-language summaries and drift/parity checks;
- provides dashboards, PDF/Excel/JSON reports, JWT login with Admin/Manager/Analyst roles, and a tamper-evident audit trail;
- is tested (79 backend and 39 frontend automated tests, 91% backend line coverage) and can be started with one command (`docker compose up --build` or `scripts/demo.ps1`).

## 5.2 Conclusion
The integrated approach works as a prototype. On the held-out 90 days the serving model reached **13.0% MAPE** per series-day and **3.6%** on daily chain totals - inside the 10-15% target and about 47% better than the best naive baseline (24.5%).
The anomaly ensemble (precision 0.67, recall 0.70, F1 0.68 on injected anomalies) outperformed each detector on its own, supporting the idea that combining methods is more useful than relying on one.
Because the same forecast feeds the recommendations, the simulator and the explanations, a manager can move from "what will happen" to "what should I do" and "why" within one tool - which is the gap identified in the literature review.

The conclusion must be read with its limits: apart from the sales series, the data are synthetic; recommendation quality could not be measured against real outcomes; the anomaly figures describe recovery of injected faults; there is no automatic scheduling or real-time streaming; and no user study has been conducted yet.
The system is therefore a validated *prototype of the method*, not a production-ready retail system.

## 5.3 Recommendations
**For using or extending the system**
1. **Replace the synthetic parts with real data first**: actual prices, promotions, stock levels, supplier lead times and ad spend. Price and marketing responses in the recommender and simulator are currently assumptions and should be estimated from history.
2. **Run a pilot with a small retailer** and compare recommendations with decisions and outcomes (stock-outs avoided, markdown margin, fraud found) - this is the missing evidence for recommendation quality.
3. **Add scheduling and delivery**: weekly retraining with a promotion rule (only replace the model when the new MAPE is better), scheduled scans and reports, and email/Slack/SFTP delivery. The settings and report-cadence screens already store this configuration.
4. **Reduce forecast bias**: forecasts run 2-5% low and worsen with the horizon. Direct multi-horizon models, bias correction or an ensemble of XGBoost and LSTM are the obvious next experiments.
5. **Make risk signals an input to recommendations** (for example hold a purchase order for a store with an unresolved duplicate-billing alert) and add invoice-level data so duplicate detection can match document numbers instead of relying on statistical outliers.
6. **Connect databases and ERP systems** (MySQL/PostgreSQL, SAP/Tally) and stream data so alerts become genuinely near real time.

**For production hardening**
7. Use HTTPS behind a reverse proxy, a real secret manager, a database server instead of SQLite, token revocation/refresh, two-factor login and SSO; change the demo password.
8. Add end-to-end browser tests, load tests and an accessibility audit; run the usability study (template provided) with 5-10 users.

**For research**
9. Evaluate on additional public datasets (other retailers, other years) and compare with deep global models (DeepAR, N-BEATS, temporal fusion transformers).
10. Study how explanation style affects managers' trust and decisions.

## 5.4 Future scope
Multi-tenant deployment, mobile alerts, forecast hierarchies with reconciliation, causal estimation of price and promotion effects, and automated retraining with drift monitoring tied to the governance panel.
