"""Optional cloud path: load the raw CSVs into BigQuery.

Creates (if needed) a `raw` dataset in the project given by $GCP_PROJECT and
loads both files as tables with a loaded_at timestamp, matching the dbt
source declarations under the `bigquery` target. Raw tables are replaced
atomically on each load and never modified downstream.

Requires: pip install google-cloud-bigquery pandas
Auth:     a service-account JSON via $GOOGLE_APPLICATION_CREDENTIALS
          (BigQuery sandbox tier is fine — this data is a few MB).

Run, then: cd dbt && dbt build --profiles-dir . --target bigquery
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
TABLES = {
    "saas_transactions": ["order_date"],
    "subscriptions": ["subscription_start", "churn_date"],
}


def main() -> None:
    try:
        import pandas as pd
        from google.cloud import bigquery
    except ImportError:
        sys.exit("pip install google-cloud-bigquery pandas")

    project = os.environ.get("GCP_PROJECT")
    if not project:
        sys.exit("set GCP_PROJECT to your GCP project id")

    client = bigquery.Client(project=project)
    dataset_ref = bigquery.Dataset(f"{project}.raw")
    client.create_dataset(dataset_ref, exists_ok=True)

    for table, date_cols in TABLES.items():
        df = pd.read_csv(RAW / f"{table}.csv", parse_dates=date_cols)
        df["loaded_at"] = datetime.now(timezone.utc)
        job = client.load_table_from_dataframe(
            df, f"{project}.raw.{table}",
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"))
        job.result()
        print(f"loaded {len(df):,} rows -> {project}.raw.{table}")


if __name__ == "__main__":
    main()
