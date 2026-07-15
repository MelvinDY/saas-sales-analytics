"""End-to-end pipeline: raw data -> dbt build (models + tests) -> dashboard.

Usage (from the project venv):
    python run_pipeline.py                  # full run
    python run_pipeline.py --skip-generate  # rebuild from existing raw CSVs
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DBT_DIR = ROOT / "dbt"


def run(desc: str, cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"\n=== {desc} ===")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        sys.exit(f"FAILED: {desc} (exit {result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-generate", action="store_true",
                        help="reuse existing data/raw CSVs")
    args = parser.parse_args()

    if not args.skip_generate:
        run("generate raw data", [sys.executable, "ingest/generate_data.py"])

    dbt = Path(sys.executable).with_name("dbt")
    if not (DBT_DIR / "dbt_packages").exists():
        run("dbt deps", [str(dbt), "deps", "--profiles-dir", "."], DBT_DIR)
    run("dbt build (models + tests)",
        [str(dbt), "build", "--profiles-dir", "."], DBT_DIR)

    run("build dashboard", [sys.executable, "dashboard/build_dashboard.py"])
    print("\ndone — open dashboard/index.html")


if __name__ == "__main__":
    main()
