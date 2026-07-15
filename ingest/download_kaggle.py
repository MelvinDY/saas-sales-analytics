"""Optional: replace the synthetic data with the real Kaggle datasets.

The project plan's two datasets are both on Kaggle:
  1. B2B SaaS sales transactions (order_id, order_date, customer_id, product,
     sales, profit, region)
  2. SaaS subscription & churn lifecycle (customer_id, plan_tier, mrr,
     subscription_start, churn_date, churn_reason, country)

Requires the Kaggle CLI and ~/.kaggle/kaggle.json (create an API token at
kaggle.com/settings). Point --transactions / --subscriptions at the dataset
slugs you choose, then rename/remap the downloaded CSVs to the two schemas
above and drop them into data/raw/ with the expected file names:

    data/raw/saas_transactions.csv
    data/raw/subscriptions.csv

The dbt sources assert the primary-key contracts (unique, not_null), so a
column mismatch fails loudly at `dbt build` rather than silently.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transactions", required=True,
                        help="Kaggle slug, e.g. owner/b2b-saas-sales")
    parser.add_argument("--subscriptions", required=True,
                        help="Kaggle slug, e.g. owner/saas-churn")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    for slug in (args.transactions, args.subscriptions):
        print(f"downloading {slug} ...")
        result = subprocess.run(
            ["kaggle", "datasets", "download", "-d", slug,
             "-p", str(RAW), "--unzip"])
        if result.returncode != 0:
            sys.exit(f"kaggle download failed for {slug} — is the CLI "
                     "installed and ~/.kaggle/kaggle.json present?")
    print(f"\ndownloaded to {RAW}. Rename/remap the CSVs to "
          "saas_transactions.csv and subscriptions.csv (see module docstring), "
          "then run: python run_pipeline.py --skip-generate")


if __name__ == "__main__":
    main()
