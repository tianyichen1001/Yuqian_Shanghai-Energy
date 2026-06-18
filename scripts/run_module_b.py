"""Entry point for Module B — ML archetype inference.

Usage:
    python scripts/run_module_b.py --area xuhui
"""

from __future__ import annotations

import argparse
import sys

from buildings_shanghai import ml as module_b


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Module B: ML archetype inference.")
    parser.add_argument("--area", default="full_city")
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Run Optuna hyperparameter search before fitting the final model.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # TODO: branch on --tune once Module B is implemented.
    module_b.run(area=args.area)
    return 0


if __name__ == "__main__":
    sys.exit(main())
