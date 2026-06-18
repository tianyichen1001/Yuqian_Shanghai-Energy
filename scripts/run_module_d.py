"""Entry point for Module D — embodied-carbon Monte Carlo.

Usage:
    python scripts/run_module_d.py --samples 5000
"""

from __future__ import annotations

import argparse
import sys

from buildings_shanghai import embodied as module_d


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Module D: embodied-carbon Monte Carlo.")
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # TODO: pass seed once Module D is implemented.
    module_d.run(n_samples=args.samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
