# PRD — SaaS Sales & Revenue Analytics Pipeline

**Owner:** Melvin Darial Yogiana
**Status:** Draft v1 · July 2026
**Stack:** Python · dbt Core · DuckDB (dev) / BigQuery (cloud path) · self-contained HTML dashboard · Looker Studio (cloud path)

---

## 1. Background & positioning

Australia's tech sector is dominated by SaaS companies (Atlassian, Canva, SafetyCulture, Tyro), and every SaaS data-analyst interview circles the same four metrics: **MRR, churn rate, NRR, and CLV**. This project proves I can build all of them from raw data — not just recite the definitions.

It is an end-to-end analytics pipeline over two complementary SaaS datasets — a **B2B transaction dataset** (orders, products, revenue, profit, region) and a **subscription lifecycle dataset** (plan tier, MRR, start/churn dates, churn reason, country). Data flows through a proper **dbt staging → intermediate → marts architecture** with tests and column-level documentation, and lands in a four-page dashboard: revenue overview, churn analysis, cohort retention, and plan performance.

The portfolio signal here is different from `woolworths-vs-coles-analytics` (which deliberately avoided dbt): this project demonstrates **production dbt habits** — declared sources with tests, one staging model per source, an enriched intermediate layer, mart grain assertions via `dbt_utils`, and a documented DAG — plus the **SaaS metric fluency** (MRR bridge, cohort NRR, predictive CLV) that local SaaS employers screen for.

## 2. Goals

| # | Goal | Measure of success |
|---|------|--------------------|
| G1 | Full dbt architecture | Sources → 2 staging → 2 intermediate → 4 mart models, every model and column documented in `schema.yml`, `dbt build` green including tests |
| G2 | The four interview metrics, correctly | MRR/ARR with a movement bridge (new / expansion / contraction / churned), customer & revenue churn rate, cohort-based NRR, realized + predictive CLV — each traceable to raw rows |
| G3 | Cohort retention heatmap | Signup-month × months-since-signup retention matrix, both logo and MRR retention, rendered as the dashboard centrepiece |
| G4 | Zero-cost, zero-infra dev loop | `python run_pipeline.py` runs generator → dbt build → dashboard locally on DuckDB; no cloud, no keys |
| G5 | Credible cloud path | The same dbt project targets BigQuery via a second profile; loader script and Looker Studio wiring documented |

## 3. Non-goals

- **No live data source** — the plan's Kaggle datasets require API credentials; v1 ships on a seeded synthetic generator that reproduces both schemas with realistic SaaS dynamics (growth trend, tier-dependent churn hazard, upgrades, a deliberately bad promo cohort). `ingest/download_kaggle.py` swaps in the real datasets when credentials exist.
- No orchestration/scheduler — the pipeline is a single idempotent run.
- No ML churn prediction — this is a metrics/modeling project, not a modeling-in-the-statistical-sense project.
- No paid infrastructure — BigQuery usage stays inside the free sandbox tier; Looker Studio is free.

## 4. Users

| User | Need |
|------|------|
| Hiring manager / recruiter (primary) | Open the dashboard, recognise the cohort heatmap instantly, see the four metrics computed properly in 30 seconds |
| Technical interviewer | Read the dbt models; probe how NRR and the MRR bridge are computed; check grain tests exist |
| Melvin (operator) | `python run_pipeline.py` end-to-end; `dbt build` inside `dbt/` for iteration |

## 5. Data sources

| Source | File | Schema |
|--------|------|--------|
| B2B SaaS transactions | `data/raw/saas_transactions.csv` | `order_id, order_date, customer_id, product, sales, profit, region` — one row per order line; monthly recurring invoices plus one-off add-ons |
| Subscription lifecycle | `data/raw/subscriptions.csv` | `customer_id, plan_tier, mrr, subscription_start, churn_date, churn_reason, country` — one row per customer; `mrr` is the latest (current or at-churn) monthly rate |

Grain contracts: transactions are unique on `order_id`; subscriptions are unique on `customer_id`. Both are declared as dbt **sources** with `not_null`/`unique` tests — raw files are never modified downstream.

## 6. Functional requirements

### FR-1 Ingestion (`ingest/`)
- `generate_data.py` — deterministic (seeded) generator: ~1,500 customers signing up 2023-01 → 2026-06 with an upward growth trend; three plan tiers (Basic $49 / Pro $149 / Enterprise $499, seat-scaled); tier-dependent monthly churn hazard with elevated early-life churn; a mid-2024 promo cohort with deliberately worse retention (the heatmap story); monthly recurring invoices with occasional upgrades (expansion) and one-off add-on orders; churn reasons sampled per tier.
- `download_kaggle.py` — optional: pulls the two Kaggle datasets via the Kaggle CLI into the same file names/columns.
- `load_to_bigquery.py` — optional cloud path: loads both raw CSVs into a `raw` BigQuery dataset with a `loaded_at` timestamp.

### FR-2 dbt project (`dbt/`)
- **Sources** (`sources.yml`): both raw CSVs declared with descriptions and PK tests (dbt-duckdb `external_location`; table refs under BigQuery).
- **Staging**: `stg_saas_transactions`, `stg_subscriptions` — rename, cast, parse dates, standardise plan-tier values. No joins.
- **Intermediate**: `int_customer_revenue` (one row per customer: first/last order, lifetime revenue, `subscription_length_days`, `months_active`, `is_churned`, `revenue_per_month`) and `int_customer_monthly_revenue` (customer × active month spine with billed recurring revenue — the base for MRR, NRR, and cohorts).
- **Marts**, one per dashboard page, each with a `dbt_utils.unique_combination_of_columns` grain test:
  - `mart_revenue_trends` — grain (month, region): MRR bridge (new / expansion / contraction / churned), total MRR, ARR, active customers, MoM growth.
  - `mart_churn_analysis` — grain (month, plan_tier, churn_reason): churned customers & MRR per reason; customers/MRR at start attached at (month, tier) level for rate computation.
  - `mart_cohort_retention` — grain (cohort_month, months_since_signup): cohort size, active customers, logo retention, retained MRR, MRR retention (cohort NRR).
  - `mart_plan_performance` — grain (month, plan_tier): active customers, MRR, ARPU, 12-month NRR, realized CLV of churned customers, predictive CLV (ARPU ÷ churn rate).
- Every model and column documented in `schema.yml`; `dbt build` runs models + tests in one command.

### FR-3 Dashboard (`dashboard/build_dashboard.py` → `dashboard/index.html`)
- Single static HTML file, zero external requests, light/dark aware.
- Four sections mirroring the marts: KPI scorecards (MRR, ARR, NRR, churn rate, active customers), MRR bridge over time, churn trends & reasons, the **cohort retention heatmap**, and plan-level ARPU/NRR/CLV.
- Each section led by a written insight sentence; a notes panel states the data provenance honestly.

### FR-4 Orchestration & repo
- `run_pipeline.py` — generate (or reuse) raw data → `dbt build` → dashboard; `--skip-generate` rebuilds from existing raw files.
- README: 30-second pitch, architecture diagram, metric definitions, honest limitations, run instructions, BigQuery/Looker path.
- `.gitignore` excludes `data/`, `.venv/`, dbt artifacts; the generated dashboard **is** committed so the repo demos without running anything.

## 7. Milestones

| Phase | Deliverable |
|-------|-------------|
| 1 | Synthetic generator producing both schemas with realistic dynamics |
| 2 | dbt sources + staging models, tests green |
| 3 | Intermediate layer (customer grain + monthly spine) |
| 4 | Four marts with grain tests + full schema documentation |
| 5 | Dashboard + README |
| 6 | GitHub repo; BigQuery/Looker documented as the cloud path |

## 8. Risks

| Risk | Mitigation |
|------|-----------|
| Synthetic data reads as toy data | Generator encodes real SaaS dynamics (hazard curves, expansion, seasonality, a bad cohort); README states provenance up front; Kaggle swap-in script ships in v1 |
| NRR is subtle and easy to get wrong | Computed two ways that cross-check: cohort MRR retention at month N, and 12-month rolling NRR from the monthly revenue spine |
| Metric definitions drift between SQL and dashboard | Dashboard reads only mart tables; all metric logic lives in dbt |
| dbt on DuckDB ≠ the BigQuery plan | Same models compile on both adapters (standard SQL, no adapter-specific functions outside sources); BigQuery profile + loader included |
| Portfolio already shows dbt | This is the *deep* dbt showing — tests, docs, packages, layered DAG — where the earlier projects only touched it |
