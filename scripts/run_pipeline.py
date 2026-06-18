"""Entry point for the full A->E pipeline.

Usage:
    python scripts/run_pipeline.py --city shanghai --area xuhui
"""

from __future__ import annotations

import argparse
import sys

from buildings_shanghai import calibration, embodied, ml, simulation, viz
from buildings_shanghai import data as data_module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full UBEM pipeline (Module A -> E).")
    parser.add_argument(
        "--city",
        default="shanghai",
        help="Config key under config/<city>.yaml (default: shanghai).",
    )
    parser.add_argument(
        "--area",
        default="full_city",
        help="Study-area key from the city config (default: full_city).",
    )
    parser.add_argument(
        "--skip",
        nargs="*",
        choices=["a", "b", "c", "d", "e"],
        default=[],
        help="Module letters to skip.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    skip = set(args.skip)

    if "a" not in skip:
        data_module.run(area=args.area)
    if "b" not in skip:
        ml.run(area=args.area)
    if "c" not in skip:
        simulation.run(area=args.area)
    if "d" not in skip:
        embodied.run()
    if "e" not in skip:
        calibration.run()
        viz.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
