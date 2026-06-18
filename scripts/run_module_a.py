"""Entry point for Module A — data acquisition and CRS unification.

Usage:
    python scripts/run_module_a.py --area xuhui
    python scripts/run_module_a.py --area full_city --generate-poi-candidates
"""

from __future__ import annotations

import argparse
import sys

from buildings_shanghai import data as module_a


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Module A: data acquisition.")
    parser.add_argument(
        "--area",
        default="full_city",
        help="Study-area key from config/shanghai.yaml (default: full_city).",
    )
    parser.add_argument(
        "--generate-poi-candidates",
        action="store_true",
        help="Dump distinct Amap POI categories that intersect buildings, "
        "to seed manual review of config/poi_mapping.yaml.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # TODO: branch on --generate-poi-candidates once Module A is implemented.
    module_a.run(area=args.area)
    return 0


if __name__ == "__main__":
    sys.exit(main())
