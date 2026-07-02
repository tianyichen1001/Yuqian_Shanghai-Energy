"""Same-building clustering: "同款楼去重".

Rule (per task spec):

    Within one window, two buildings A and B are considered *same-model*
    duplicates when ALL three hold:
      - |area_A - area_B| / max(area_A, area_B) <= 0.05
      - |height_A - height_B| <= 0.5 m
      - Euclidean distance between representative points <= 250 m

    Buildings are then transitively grouped into clusters (union-find).
    Within each cluster, keep at most three buildings, chosen by lowest
    input row-index (stable across runs).

The 250 m radius is a rough "same podium / same estate" threshold: two
identical residential towers 300 m apart in different compounds should
stay independent samples, but the ten twin towers on one plot should
collapse to three.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


AREA_REL_TOL: float = 0.05
HEIGHT_ABS_TOL_M: float = 0.5
DISTANCE_TOL_M: float = 250.0
KEEP_PER_CLUSTER: int = 3


@dataclass(frozen=True)
class DedupResult:
    """Outcome of running :func:`dedup_same_building` on one window."""

    kept: pd.DataFrame
    dropped: pd.DataFrame
    cluster_sizes: dict[int, int]  # cluster_id -> total members


class _UnionFind:
    """Minimal union-find over consecutive integer ids."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def dedup_same_building(
    gdf_metric: pd.DataFrame,
    *,
    area_col: str = "Area",
    height_col: str = "height",
    x_col: str = "x_m",
    y_col: str = "y_m",
) -> DedupResult:
    """Cluster same-model buildings and keep at most ``KEEP_PER_CLUSTER`` per cluster.

    ``gdf_metric`` must be sorted by the caller's chosen deterministic order
    (typically the source row index) and expose four columns:

    - ``Area``   footprint area in m²
    - ``height`` building height in m
    - ``x_m``, ``y_m`` representative-point coordinates in the metric CRS

    Returns a :class:`DedupResult` where ``kept`` contains the surviving
    rows (with an extra ``cluster_id`` and ``cluster_size`` column) and
    ``dropped`` contains the discarded siblings (same extra columns).
    """
    n = len(gdf_metric)
    if n == 0:
        return DedupResult(
            kept=gdf_metric.copy(),
            dropped=gdf_metric.copy(),
            cluster_sizes={},
        )

    df = gdf_metric.reset_index(drop=False)
    orig_index_col = df.columns[0]  # name of the preserved input index

    xy = df[[x_col, y_col]].to_numpy()
    tree = cKDTree(xy)
    neighbours = tree.query_ball_tree(tree, r=DISTANCE_TOL_M)

    areas = df[area_col].to_numpy(dtype=float)
    heights = df[height_col].to_numpy(dtype=float)

    uf = _UnionFind(n)
    for i, nbrs in enumerate(neighbours):
        area_i, height_i = areas[i], heights[i]
        for j in nbrs:
            if j <= i:
                continue
            if abs(heights[j] - height_i) > HEIGHT_ABS_TOL_M:
                continue
            denom = max(areas[j], area_i)
            if denom <= 0:
                continue
            if abs(areas[j] - area_i) / denom > AREA_REL_TOL:
                continue
            uf.union(i, j)

    cluster_ids = np.array([uf.find(i) for i in range(n)])
    df["_cluster_root"] = cluster_ids

    # Re-label roots to consecutive 0..k-1 for readability.
    unique_roots, inverse = np.unique(cluster_ids, return_inverse=True)
    df["cluster_id"] = inverse

    sizes = pd.Series(inverse).value_counts().to_dict()
    df["cluster_size"] = df["cluster_id"].map(sizes)

    # Keep the first KEEP_PER_CLUSTER rows of each cluster by input row order.
    df = df.sort_values([orig_index_col]).reset_index(drop=True)
    rank_within = df.groupby("cluster_id").cumcount()
    keep_mask = rank_within < KEEP_PER_CLUSTER

    kept = df.loc[keep_mask].drop(columns=["_cluster_root"]).reset_index(drop=True)
    dropped = df.loc[~keep_mask].drop(columns=["_cluster_root"]).reset_index(drop=True)

    return DedupResult(kept=kept, dropped=dropped, cluster_sizes=sizes)


__all__ = [
    "AREA_REL_TOL",
    "HEIGHT_ABS_TOL_M",
    "DISTANCE_TOL_M",
    "KEEP_PER_CLUSTER",
    "DedupResult",
    "dedup_same_building",
]
