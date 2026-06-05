from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.kyc_generator import KYC_TARGET_ROW_COUNT
from utils.kyc_store import regenerate_kyc_database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate bulk KYC mock data aligned to account IDs from a root CSV."
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=KYC_TARGET_ROW_COUNT,
        help=f"Number of KYC rows to generate (default: {KYC_TARGET_ROW_COUNT}).",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible names.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when a full kyc_customers.csv already exists.",
    )
    args = parser.parse_args()

    count, source = regenerate_kyc_database(row_count=args.rows, seed=args.seed, force=args.force)
    print(f"Generated {count:,} KYC rows from account source: {source}")


if __name__ == "__main__":
    main()
