"""Window-scan sampling with deterministic fallback expansion.

Given a footprint GeoDataFrame in a metric CRS and one :class:`Window`,
:func:`sample_window` will:

1. Clip to ``area >= 100 m²``.
2. Clip to the metric square ``[cx ± halfwidth, cy ± halfwidth]``.
3. Dedup via :func:`dedup_same_building` (same-model rule).
4. If ``len(kept) >= quota``, draw ``quota`` samples with ``rng``.
   Otherwise expand halfwidth by +300 m and retry, up to ``max_halfwidth_m``.

All randomness comes from a single ``numpy.random.Generator`` passed in
by the caller, so the pipeline is bit-reproducible with ``seed=42``.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

from .dedup import dedup_same_building
from .windows import Window


MIN_FOOTPRINT_AREA_M2: float = 100.0
HALFWIDTH_STEP_M: int = 300
DEFAULT_MAX_HALFWIDTH_M: int = 3000


@dataclass(frozen=True)
class SampleResult:
    """Outcome of :func:`sample_window`."""

    window: Window
    final_halfwidth_m: int
    #: The 40 sampled rows (index preserved from the input GeoDataFrame).
    picked: gpd.GeoDataFrame
    #: All post-dedup candidates (superset of ``picked``); useful for QC.
    all_kept: gpd.GeoDataFrame
    #: The rows dropped by the same-model rule.
    dropped_duplicates: pd.DataFrame
    #: Cluster sizes at the final halfwidth (cluster_id -> total members).
    cluster_sizes: dict[int, int]


class NotEnoughCandidatesError(RuntimeError):
    """Raised when a window cannot yield ``quota`` candidates even at
    ``max_halfwidth_m``. Caller (pipeline) is expected to stop and report."""


def _clip_to_window(
    gdf_metric: gpd.GeoDataFrame,
    cx: float,
    cy: float,
    halfwidth_m: int,
    x_col: str,
    y_col: str,
) -> gpd.GeoDataFrame:
    xs = gdf_metric[x_col].to_numpy()
    ys = gdf_metric[y_col].to_numpy()
    mask = (
        (xs >= cx - halfwidth_m)
        & (xs <= cx + halfwidth_m)
        & (ys >= cy - halfwidth_m)
        & (ys <= cy + halfwidth_m)
    )
    return gdf_metric.loc[mask]


def sample_window(
    footprints_metric: gpd.GeoDataFrame,
    window: Window,
    *,
    centre_x: float,
    centre_y: float,
    rng: np.random.Generator,
    area_col: str = "Area",
    height_col: str = "height",
    x_col: str = "x_m",
    y_col: str = "y_m",
    max_halfwidth_m: int = DEFAULT_MAX_HALFWIDTH_M,
) -> SampleResult:
    """Extract ``window.quota`` candidates from one window.

    ``footprints_metric`` is the *full-city* GeoDataFrame projected to a
    metric CRS, with columns ``area_col``, ``height_col``, ``x_col``,
    ``y_col`` (representative-point coords). The rest of the columns are
    preserved on the returned rows.
    """
    area_mask = footprints_metric[area_col] >= MIN_FOOTPRINT_AREA_M2
    base = footprints_metric.loc[area_mask]

    halfwidth = window.halfwidth_m
    while True:
        window_gdf = _clip_to_window(base, centre_x, centre_y, halfwidth, x_col, y_col)
        dedup = dedup_same_building(
            window_gdf,
            area_col=area_col,
            height_col=height_col,
            x_col=x_col,
            y_col=y_col,
        )
        n_kept = len(dedup.kept)
        if n_kept >= window.quota:
            break
        if halfwidth >= max_halfwidth_m:
            raise NotEnoughCandidatesError(
                f"window={window.key} exhausted at halfwidth={halfwidth}m: "
                f"only {n_kept} candidates after dedup, need {window.quota}. "
                f"Pipeline stops per rule 2c."
            )
        halfwidth += HALFWIDTH_STEP_M

    kept = dedup.kept
    dropped = dedup.dropped
    cluster_sizes = dedup.cluster_sizes

    # Deterministic random draw of `quota` rows from the kept set. We work
    # on the *positional* range 0..n-1 so the same rng.choice call gives
    # the same rows for the same input and seed.
    picked_positions = rng.choice(n_kept, size=window.quota, replace=False)
    picked_positions.sort()
    picked = kept.iloc[picked_positions].reset_index(drop=True)

    return SampleResult(
        window=window,
        final_halfwidth_m=halfwidth,
        picked=picked,
        all_kept=kept,
        dropped_duplicates=dropped,
        cluster_sizes=cluster_sizes,
    )


__all__ = [
    "MIN_FOOTPRINT_AREA_M2",
    "HALFWIDTH_STEP_M",
    "DEFAULT_MAX_HALFWIDTH_M",
    "SampleResult",
    "NotEnoughCandidatesError",
    "sample_window",
]
