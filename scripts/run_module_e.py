"""Entry point for Module E — dual-track NMBE calibration and figure generation.

Usage:
    python scripts/run_module_e.py --figures
"""

from __future__ import annotations

import argparse
import sys

from buildings_shanghai import calibration, viz


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Module E: dual-track NMBE calibration and figure generation."
    )
    parser.add_argument(
        "--figures",
        action="store_true",
        help="Regenerate all paper figures after calibration completes.",
    )
    parser.add_argument(
        "--skip-calibration",
        action="store_true",
        help="Skip calibration; only regenerate figures from existing results.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.skip_calibration:
        calibration.run()
    if args.figures or args.skip_calibration:
        viz.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
