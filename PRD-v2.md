# PRD v2 — Semantic Layer, Data CI & Power BI

**Owner:** Melvin Darial Yogiana
**Status:** Draft v2 · August 2026
**Extends:** [PRD.md](PRD.md) (v1 — shipped dbt pipeline on the real Kaggle SaaS extract)
**Stack added:** dbt exposures + metrics · SQLFluff · GitHub Actions (dbt CI) · Power BI

---

## 1. Background & positioning

v1 built the part that is hardest to fake: four SaaS metrics derived correctly
from a real extract, through a documented dbt DAG with grain tests, plus a
cohort heatmap as the centrepiece. What sits either side of that DAG is thinner.
Upstream there is no CI on the models; downstream there is a static HTML file.

Both gaps map to specific hiring signals:

- **Power BI appears in roughly 43% of Australian data-analyst job ads; Tableau in about 2%.** The portfolio's only Power BI artifact belongs to the labour-market project, whose Azure backend has been torn down. This project is the natural second home for it, because SaaS metrics are exactly what a BI semantic model is for.
- **CI for data** — running `dbt build` on every pull request — is the habit that separates "wrote some models" from "worked on a data team". v1 has no workflow file at all.
- **A metrics/semantic layer** is what stops MRR being defined three times in three tools. Interviewers ask about it because every company has been burned by it.

## 2. Goals

| # | Goal | Measure of success |
|---|------|--------------------|
| G1 | Metrics defined once | MRR, churn rate, NRR and CLV declared in one semantic layer; the dashboard and any BI tool consume those definitions rather than re-implementing them |
| G2 | CI on every pull request | `dbt build` + `sqlfluff lint` run on PRs against a scratch schema; a failing test blocks the merge |
| G3 | Power BI report on the marts | Four pages matching the HTML dashboard, built on an explicit star-schema model with documented DAX measures |
| G4 | Lineage ends at a human | dbt `exposures` declare the dashboard and the Power BI report, so the DAG terminates at consumers |
| G5 | Still zero-cost and still one command | Power BI Desktop is free; `run_pipeline.py` unchanged; the `.pbix` builds off the local DuckDB marts |

## 3. Non-goals

- **No paid BI licence.** Power BI Desktop plus a committed `.pbix` and page exports. No Fabric capacity, no Pro seat for publishing.
- **No dbt Cloud.** Core plus GitHub Actions, consistent with the other projects.
- No new metrics. v2 is about how the existing four are defined, tested and consumed — not about adding a fifth.
- No replacement of the static HTML dashboard. It stays as the zero-click artifact for recruiters; Power BI is the second surface, aimed at a different reader.
- No orchestration. Scheduling belongs to the YouTube project; this pipeline remains a single idempotent run.

## 4. Users

| User | Need |
|------|------|
| Hiring manager / recruiter (primary) | Recognise the cohort heatmap in the HTML dashboard; see a Power BI screenshot and a green CI badge in the README |
| Technical interviewer | Read the semantic layer definitions; ask why NRR is defined once and consumed twice; check the CI workflow actually blocks on test failure |
| Melvin (operator) | `run_pipeline.py` unchanged; open the `.pbix` against the built marts without reconfiguring anything |

## 5. Functional requirements

### FR-1 Semantic layer (`dbt/models/semantic/`)
- Declare the four metrics with explicit grain, filters and time dimension.
- Each definition carries a one-line prose statement of what it means in business terms — the sentence that belongs in a data dictionary, not a formula restated in English.
- The HTML dashboard builder reads metric values through the semantic layer rather than re-querying marts with its own SQL. Where that is not yet supported by the adapter, the builder queries a single dedicated mart per metric and the duplication is documented as a known limitation instead of hidden.

### FR-2 Data CI (`.github/workflows/ci.yml`)
- Trigger: pull requests touching `dbt/**` or `ingest/**`.
- Steps: install, `dbt deps`, `dbt build --target ci` against DuckDB in the runner, `sqlfluff lint dbt/models`.
- Fails the PR on any test failure or lint violation. Badge in the README.
- `.sqlfluff` config matching the YouTube project's, so both repos lint to one house style.

### FR-3 Power BI report (`powerbi/`)
- Star schema over the marts: a date dimension, a customer dimension, a plan dimension, and monthly revenue as the fact — modelled explicitly rather than reporting off wide flat tables.
- Measures in DAX for the four metrics, named identically to the semantic-layer definitions. Any deviation forced by DAX is annotated in the model documentation.
- Four pages mirroring the HTML dashboard: revenue overview, churn, cohort retention, plan performance.
- Committed: `.pbix`, a PNG per page, and a `powerbi/README.md` covering the model diagram and the refresh path from local marts.

### FR-4 Exposures
- `exposures.yml` declaring the HTML dashboard and the Power BI report as consumers, each with owner and description, so `dbt docs` lineage runs raw → mart → consumer.

### FR-5 Documentation
- README gains a CI badge, a Power BI screenshot, and one paragraph on why a metric is defined once and consumed twice.
- PRD.md (v1) gets a pointer to this document; v1's shipped-state narrative is not rewritten.

## 6. Milestones

| Phase | Deliverable | Estimate |
|-------|-------------|----------|
| P1 | CI workflow green on a throwaway PR | Half a day |
| P2 | Semantic layer definitions + dashboard consuming them | 1 day |
| P3 | Power BI model, measures, four pages | 1–2 days |
| P4 | Exposures, README, screenshots | Half a day |

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Semantic-layer tooling churns fast and adapter support varies | Definitions live in the dbt project as the single source of truth; if the adapter cannot serve them, the fallback is one mart per metric and a documented limitation — never two hand-written definitions |
| `.pbix` is a binary blob in git | Commit it once per meaningful revision, not per tweak; PNG exports and the model README carry the reviewable detail |
| Power BI measures silently disagree with dbt marts | A reconciliation page in the report comparing each DAX measure against its mart value; any gap is a bug, not a rounding story |
| CI on DuckDB diverges from the BigQuery path | CI target mirrors the local dev profile; the BigQuery path stays documented as the cloud option it already is |

## 8. Cost

$0. Power BI Desktop is free, GitHub Actions minutes are free for public repos,
DuckDB is local.

## 9. Definition of done

A PR that breaks a grain test is blocked by CI, the four metrics have one
definition each, the Power BI report reconciles against the marts on every
metric, and `dbt docs` lineage ends at two declared exposures.

## 10. Note for the portfolio site

v1's PRD records that the project shipped on the **real Kaggle extract**
(1,000 customers), replacing the seeded synthetic generator in the original
plan. The portfolio case study still describes this project as synthetic and
cites test and invoice counts from the pre-Kaggle build. That copy needs
correcting on the site when v2 lands — a project described as synthetic when it
is real undersells it, and every number on the site is supposed to trace to
something real.
