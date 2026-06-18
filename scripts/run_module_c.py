"""Entry point for Module C — EnergyPlus simulation.

Usage:
    python scripts/run_module_c.py --area xuhui --jobs 4
"""

from __future__ import annotations

import argparse
import sys

from buildings_shanghai import simulation as module_c


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Module C: EnergyPlus simulation.")
    parser.add_argument("--area", default="full_city")
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="Parallel EnergyPlus processes (default: 4).",
    )
    parser.add_argument(
        "--archetype",
        default=None,
        help="Restrict run to a single archetype (debug).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # TODO: pass jobs / archetype filter once Module C is implemented.
    module_c.run(area=args.area)
    return 0


if __name__ == "__main__":
    sys.exit(main())
