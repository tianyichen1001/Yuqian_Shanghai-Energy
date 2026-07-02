"""Build validation-set #9 annotation workbook (200 buildings, 5 windows).

Three staged sub-commands, matching the task's two owner checkpoints:

    # Stage 1 — extract + preview PNGs; STOP for checkpoint 1 review.
    python scripts/build_validation_workbook.py extract \\
        --shp scratch_data/shanghai_2026_building/2026 Building.shp

    # Stage 2 — print 3 test Baidu links; STOP for checkpoint 2 review.
    python scripts/build_validation_workbook.py links-test [--bd09ll]

    # Stage 3 — build xlsx + KML + README.
    python scripts/build_validation_workbook.py emit \\
        --shp scratch_data/shanghai_2026_building/2026 Building.shp

Outputs land in ``data/raw/validation/working/`` by default; override
with ``--out-root``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from buildings_shanghai import project_root
from buildings_shanghai.validation.pipeline import (
    DEFAULT_SEED,
    PipelinePaths,
    run_emit,
    run_extract,
    run_links_test,
)


def _default_out_root() -> Path:
    return project_root() / "data" / "raw" / "validation" / "working"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build validation-set #9 annotation workbook (200 buildings).",
    )
    subs = parser.add_subparsers(dest="stage", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--out-root",
            type=Path,
            default=None,
            help="Deliverable root (default: data/raw/validation/working/).",
        )
        p.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_SEED,
            help=f"Random seed (default: {DEFAULT_SEED}).",
        )

    p_extract = subs.add_parser("extract", help="Stage 1 — extract + preview PNGs.")
    p_extract.add_argument(
        "--shp",
        type=Path,
        required=True,
        help="Path to the 2026 building shapefile (WGS84, UTF-8 attributes per .cpg).",
    )
    _add_common(p_extract)

    p_links = subs.add_parser("links-test", help="Stage 2 — emit 3 test Baidu links.")
    p_links.add_argument(
        "--bd09ll",
        action="store_true",
        help="Fall back to client-side WGS84→BD09 conversion.",
    )
    _add_common(p_links)

    p_emit = subs.add_parser("emit", help="Stage 3 — build xlsx + KML + README.")
    p_emit.add_argument(
        "--shp",
        type=Path,
        required=True,
        help="Path to the 2026 building shapefile (WGS84, UTF-8 attributes per .cpg).",
    )
    p_emit.add_argument(
        "--bd09ll",
        action="store_true",
        help="Use client-side WGS84→BD09 conversion (checkpoint-2 fallback path).",
    )
    _add_common(p_emit)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    paths = PipelinePaths(root=(args.out_root or _default_out_root()).resolve())

    if args.stage == "extract":
        run_extract(shp_path=args.shp, paths=paths, seed=args.seed)
        print(
            f"\ncheckpoint 1 assets written under {paths.checkpoint1_dir}\n"
            f"send these 5 PNGs to owner and STOP:"
        )
        for w in ("lujiazui", "xujiahui", "xinzhuang", "zhangjiang", "lingang"):
            print(f"  - {paths.preview_png(w)}")
        return 0

    if args.stage == "links-test":
        coord_type = "bd09ll" if args.bd09ll else "wgs84"
        links = run_links_test(coord_type=coord_type)
        print(json.dumps(links, ensure_ascii=False, indent=2))
        print(
            "\nOwner: click each URL, confirm the pin lands on the actual building.\n"
            "If any is off, re-run with `--bd09ll`.",
            file=sys.stderr,
        )
        return 0

    if args.stage == "emit":
        coord_type = "bd09ll" if args.bd09ll else "wgs84"
        runs = run_extract(shp_path=args.shp, paths=paths, seed=args.seed)
        out = run_emit(runs, paths, coord_type=coord_type, seed=args.seed)
        print("deliverables:")
        for name, path in out.items():
            print(f"  {name}: {path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
