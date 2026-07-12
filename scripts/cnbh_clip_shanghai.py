"""CNBH-10m 上海切片 — 块 2 采集入库(只采集,不分析;2026-07-12 工作令)。

源(只认官方 DOI):
  Zenodo 10.5281/zenodo.7923866(latest;concept 10.5281/zenodo.7015081),
  Wu W., CNBH-10 m, CC-BY-4.0;论文 RSE 10.1016/j.rse.2023.113578。
  瓦片命名按中心经纬(2°×2°):X121Y31 覆盖 [120,122]×[30,32],
  master 全部建筑落此瓦片;X123Y31 仅补 GADM 上海东部外礁。

流程:
  1. 下载 CNBH10m_X121Y31.tif + CNBH10m_X123Y31.tif,MD5 对 Zenodo 元数据;
  2. GADM 4.1 NAME_1=='Shanghai' 市界 mask+crop(与 A4 EULUC 切片同口径);
  3. merge 为单文件 cnbh10m_shanghai_2020.tif(EPSG:32651 原生 10m,
     不重采样、不改值;deflate+predictor=3, tiled);
  4. 打印像元统计概要(收账报告用)。

运行:
  python scripts/cnbh_clip_shanghai.py --data-dir <dir>
  # <dir> 需含两块源瓦片与 gadm41_CHN_1.json;产出与 MD5 记账见
  # data/raw/cnbh/README.md 与私仓暗号本
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.merge import merge

TILES = ["CNBH10m_X121Y31.tif", "CNBH10m_X123Y31.tif"]
NODATA = -9999.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out-name", default="cnbh10m_shanghai_2020.tif")
    args = ap.parse_args()
    data = args.data_dir
    out = data / args.out_name

    sh = gpd.read_file(data / "gadm41_CHN_1.json")
    sh = sh[sh.NAME_1 == "Shanghai"].to_crs(32651)
    geom = [sh.geometry.union_all()]

    clipped = []
    for name in TILES:
        with rasterio.open(data / name) as src:
            assert src.crs.to_epsg() == 32651, f"{name} CRS != 32651"
            arr, tr = mask(src, geom, crop=True, nodata=NODATA)
            prof = src.profile | {"height": arr.shape[1], "width": arr.shape[2],
                                  "transform": tr, "nodata": NODATA}
        tmp = data / f"_clip_{name}"
        with rasterio.open(tmp, "w", **prof) as dst:
            dst.write(arr)
        clipped.append(tmp)
        print(f"{name}: clip -> {arr.shape[1]}x{arr.shape[2]}")

    srcs = [rasterio.open(p) for p in clipped]
    arr, tr = merge(srcs, nodata=NODATA)
    prof = srcs[0].profile | {
        "height": arr.shape[1], "width": arr.shape[2], "transform": tr,
        "nodata": NODATA, "compress": "deflate", "predictor": 3,
        "tiled": True, "blockxsize": 512, "blockysize": 512, "BIGTIFF": "IF_SAFER"}
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr)
    for s in srcs:
        s.close()
    for p in clipped:
        p.unlink()
    print(f"merged: {out} {out.stat().st_size / 1e6:.1f} MB, "
          f"{arr.shape[2]}x{arr.shape[1]} px")

    v = arr[0]
    valid = v != NODATA
    pos = v[valid & (v > 0)]
    print(f"像元统计: 总 {v.size:,} | 界内 {int(valid.sum()):,} | "
          f"有高度(>0) {pos.size:,} | 界内 NaN(无建筑) "
          f"{int(np.isnan(v[valid]).sum()):,}")
    print(f"高度 m: min {pos.min():.1f} p50 {np.percentile(pos, 50):.1f} "
          f"mean {pos.mean():.2f} p95 {np.percentile(pos, 95):.1f} "
          f"p99 {np.percentile(pos, 99):.1f} max {pos.max():.1f}")


if __name__ == "__main__":
    main()
