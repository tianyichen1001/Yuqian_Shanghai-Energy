"""块 3|CNBH-10m 40m 封顶法证 — 只查因,不做处置。

三路证据:
  A. 切裁前原始瓦片全域最大值 + 直方图顶端(判断封顶是产品固有还是切裁引入);
  B. 与切裁后成品(cnbh10m_shanghai_2020.tif)最大值对照;
  C. 地标像元实测:金茂(实高 420.5m)/ 环球金融中心(492m)/ 上海中心(632m),
     坐标取 data/reference/supertall_height_floor_crosswalk.csv confirmed 行,
     WGS84 → EPSG:32651 后取 3×3 窗口最大。

运行:python scripts/cnbh_saturation_probe.py --data-dir <含原始瓦片与成品的目录>
结论写入 data/raw/cnbh/README.md(独立 commit);误差分布与 28 栋裁定
归 CNBH 验证链正段,本脚本不涉及。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer

LANDMARKS = [  # (名称, lon, lat, 实高 m) — crosswalk confirmed 行
    ("金茂大厦", 121.50137, 31.237206, 420.5),
    ("环球金融中心", 121.503268, 31.2366, 492.0),
    ("上海中心", 121.50132, 31.235561, 632.0),
]
TILES = ["CNBH10m_X121Y31.tif", "CNBH10m_X123Y31.tif"]
CLIP = "cnbh10m_shanghai_2020.tif"


def tile_stats(path: Path) -> None:
    with rasterio.open(path) as r:
        v = r.read(1)
    finite = v[np.isfinite(v)]
    pos = finite[finite > 0]
    print(f"\n== {path.name}(切裁前原始)==")
    print(f"有限像元 {finite.size:,} | >0 像元 {pos.size:,} | 全域 max {pos.max():.2f} m")
    edges = [30, 35, 38, 39, 40, 41, 42, 45, 50, 100, 700]
    hist, _ = np.histogram(pos, bins=edges)
    for lo, hi, n in zip(edges[:-1], edges[1:], hist):
        print(f"  ({lo:>3},{hi:>3}] m: {n:>10,}")
    for q in (99.9, 99.99, 99.999):
        print(f"  p{q}: {np.percentile(pos, q):.2f} m")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True)
    args = ap.parse_args()

    for t in TILES:
        tile_stats(args.data_dir / t)

    with rasterio.open(args.data_dir / CLIP) as r:
        v = r.read(1)
        valid = (v != r.nodata) & np.isfinite(v)
        print(f"\n== {CLIP}(切裁后成品)== max {v[valid & (v > 0)].max():.2f} m")

    print("\n== 地标像元(3×3 窗口 max)==")
    tr = Transformer.from_crs(4326, 32651, always_xy=True)
    with rasterio.open(args.data_dir / TILES[0]) as r:
        for name, lon, lat, true_h in LANDMARKS:
            x, y = tr.transform(lon, lat)
            row, col = r.index(x, y)
            win = r.read(1, window=((row - 1, row + 2), (col - 1, col + 2)))
            wmax = float(np.nanmax(win))
            print(f"  {name}: 实高 {true_h:.0f} m -> CNBH {wmax:.1f} m "
                  f"(低估 {true_h - wmax:.0f} m / {100 * (1 - wmax / true_h):.0f}%)")


if __name__ == "__main__":
    main()
