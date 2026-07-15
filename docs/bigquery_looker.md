# Cloud path — BigQuery + Looker Studio

The dbt project runs identically on BigQuery (the models use only standard
SQL plus dbt cross-database macros — `date_trunc`, `dateadd`, `datediff` —
so both adapters compile them natively). The local DuckDB target is the dev
loop; this is the deployment path from the original project plan.

## 1. Load raw data

```powershell
$env:GCP_PROJECT = "your-project-id"
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
.venv\Scripts\pip install google-cloud-bigquery pandas dbt-bigquery
.venv\Scripts\python ingest\load_to_bigquery.py
```

This creates `raw.saas_transactions` and `raw.subscriptions` with a
`loaded_at` timestamp. The BigQuery sandbox (no billing account) is enough —
the data is a few MB.

## 2. Build the dbt project against BigQuery

```powershell
cd dbt
..\.venv\Scripts\dbt build --profiles-dir . --target bigquery
```

The `bigquery` output in `profiles.yml` reads the same two env vars. All 52
models and tests run unchanged; marts land in the `saas_analytics` dataset.

## 3. Wire up Looker Studio

1. lookerstudio.google.com → Create → Data source → BigQuery connector.
2. Add each mart as a data source:
   `mart_revenue_trends`, `mart_churn_analysis`, `mart_cohort_retention`,
   `mart_plan_performance`.
3. Rebuild the four dashboard pages (the local `dashboard/index.html` is the
   reference layout):
   - **Revenue overview** — scorecards for MRR/ARR (latest month), stacked
     column MRR by region, stacked column MRR bridge (new/expansion vs
     contraction/churned), MoM growth time series.
   - **Churn analysis** — churn-rate time series split by `plan_tier`
     (aggregate away `churn_reason` first — the at-start columns repeat
     across reason rows), bar chart of `churned_mrr` by `churn_reason`.
   - **Cohort retention** — pivot table, rows `cohort_month`, columns
     `months_since_signup`, values `retention_rate`, heatmap conditional
     formatting with a single-hue ramp.
   - **Plan performance** — `arpu`, `nrr_12m` and `predictive_clv` by
     `plan_tier` over `revenue_month`.
4. Share → anyone with the link can view, and link it from the portfolio.

## Cost guardrails

Sandbox datasets expire after 60 days by default — set a table expiration or
re-run the loader. Marts here are a few thousand rows, so interactive Looker
queries stay far inside the free 1 TB/month query tier.
