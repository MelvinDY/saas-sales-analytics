# SaaS Sales & Revenue Analytics Pipeline

**The four metrics every SaaS analytics interview asks about — MRR, churn
rate, NRR, and CLV — built from raw data through a tested dbt pipeline.**
Two raw datasets (B2B order transactions + subscription lifecycle) flow
through a dbt staging → intermediate → marts architecture with 44 data tests
and full column-level documentation, and land in a four-page dashboard whose
centrepiece is the cohort retention heatmap.

**Finding (as of Jun 2026):** MRR sits at $520K (+5.1% MoM) but retention
splits sharply by tier — Pro runs at 103% twelve-month NRR (seat expansion
outpaces churn) while Basic retains only 68% of its year-ago revenue and
churns ~4x faster than Enterprise. The heatmap shows exactly why: the
May–Jul 2024 discount-promo cohorts kept just 37–49% of customers at month
six versus ~71% for neighbouring cohorts — cheap signups, expensive churn.

![dbt build](https://img.shields.io/badge/dbt%20build-52%2F52%20passing-brightgreen)

## Architecture

```
ingest/generate_data.py ──► data/raw/*.csv ──► dbt sources (tested contracts)
 (seeded synthetic SaaS       saas_transactions        │
  dynamics; Kaggle swap-in    subscriptions            ▼
  script included)                              staging (2 models)
                                                stg_saas_transactions
dashboard/index.html ◄── build_dashboard.py     stg_subscriptions
 (one static file,            ▲                        │
  inline SVG, light/dark,     │                        ▼
  tooltips + table views)     │                 intermediate (2 models)
                              │                 int_customer_revenue
                        DuckDB warehouse        int_customer_monthly_revenue
                       (dev; BigQuery target           │
                        + Looker path in docs/)        ▼
                                                marts (4 models, grain-tested)
                                                mart_revenue_trends
                                                mart_churn_analysis
                                                mart_cohort_retention
                                                mart_plan_performance
```

- **dbt project** (`dbt/`): sources with primary-key tests, one staging model
  per source, an enriched customer grain plus a customer × month revenue
  spine, and four marts — one per dashboard page — each guarded by a
  `dbt_utils.unique_combination_of_columns` grain test. Every model and
  column is documented in `schema.yml`. Models use dbt cross-database macros
  only, so the same SQL compiles on DuckDB (dev) and BigQuery (cloud).
- **Metrics are computed, not asserted:** the MRR bridge decomposes month
  deltas into new / expansion / contraction / churned per customer (the
  bridge identity `MRR_t = MRR_{t-1} + net_new` holds exactly); NRR is the
  12-month cohort definition (churned = 0, expansion in full, new logos
  excluded); CLV ships both realized (lifetime revenue of churned customers)
  and predictive (ARPU ÷ trailing 12-month churn).
- **Dashboard** is one static HTML file: inline SVG, KPI tiles, crosshair
  tooltips, a table view per chart, light/dark theming, no CDN, no framework.

## Run it

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_pipeline.py     # generate → dbt build → dashboard
start dashboard\index.html
```

`run_pipeline.py --skip-generate` rebuilds from existing raw files. To
iterate on models: `cd dbt && ..\.venv\Scripts\dbt build --profiles-dir .`.
The BigQuery + Looker Studio deployment path is documented in
[docs/bigquery_looker.md](docs/bigquery_looker.md).

## Honest limitations

- **The data is synthetic.** The generator is seeded and encodes real SaaS
  dynamics (tier-dependent churn hazards, elevated early-life churn, seat
  expansion, a deliberately bad promo cohort), but the numbers describe a
  simulated company. `ingest/download_kaggle.py` swaps in the plan's two
  Kaggle datasets; the source tests enforce the schema contract either way.
- Subscription `mrr` is a latest-snapshot value, so churn-reason MRR uses
  the rate at churn; historical per-month MRR comes from invoices instead.
- Monthly churn rates on the Enterprise tier are noisy (small denominator) —
  that's why predictive CLV uses the trailing-12-month rate.
- "Active in month m" is defined as "billed a recurring invoice in m", which
  is exact here because billing is monthly; on real data with annual prepay
  you'd build the activity spine from coverage windows, not invoices.

## Stack

Python · dbt Core (dbt-duckdb, dbt_utils) · DuckDB · vanilla SVG/JS ·
BigQuery + Looker Studio as the documented cloud path. $0 to run.
