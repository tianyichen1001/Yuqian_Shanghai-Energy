#!/usr/bin/env python3
"""A1 质检脚本 — Taobao Shanghai 2026 building shapefile 只读 QC 报告。

用途
    对 2026 全市建筑高度数据集跑一次只读质检,输出六项报告:
    a. 总行数(与实测基准 843,062 比对;供应商宣传 843,063 多记 1,
       2026-07-04 经 DBF 头部 / SHX 索引 / geopandas 三方互证定案)
    b. CRS(预期 WGS84 / EPSG:4326)
    c. 全部字段名与数据类型
    d. 中文字段随机抽 10 行(seed=42),供人工确认无乱码
    e. height 统计:min / max / median / 空值数
    f. height >= 410 的数量与取值分布(验证 415 m 顶端截断)
    只读:不写文件、不改数据、不触碰 git。

输入
    默认路径(相对仓库根):
    data/raw/taobao/shanghai_2026_height/2026 Building/2026 Building.shp
    来源:数据仓库 git 树 shanghai_2026_building.zip
    (zip MD5 = 81EBFC2BFEC36FD956FE222051B6A9F3,
     内层 .shp MD5 = ED87E2815EACD525F21E2993DF4C77E2)。
    可用 --shp 覆盖路径。

输出
    stdout 质检报告,退出码 0(基准全部命中)/ 1(任一项偏离)。

编码规则(硬性)
    .cpg 声明 UTF-8,必须 encoding="utf-8" 读取;严禁 gbk、严禁省略
    encoding(早期 gbk 记载有误,已实测更正,见数据集 README)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHP = (
    PROJECT_ROOT
    / "data/raw/taobao/shanghai_2026_height/2026 Building/2026 Building.shp"
)

# 实测基准(2026-07-04 定案,见 data/raw/taobao/shanghai_2026_height/README.md)
EXPECTED_ROWS = 843_062
EXPECTED_EPSG = 4326
SAMPLE_SEED = 42
SUPERTALL_CUTOFF = 410  # 顶端截断检查阈值(m)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shp", type=Path, default=DEFAULT_SHP)
    args = parser.parse_args()

    gdf = gpd.read_file(args.shp, encoding="utf-8")  # 严禁 gbk / 省略 encoding
    ok = True

    print("=" * 70)
    rows_match = len(gdf) == EXPECTED_ROWS
    ok &= rows_match
    print(f"a. 总行数: {len(gdf):,} | 基准 {EXPECTED_ROWS:,} |",
          "MATCH" if rows_match else "MISMATCH")
    print("=" * 70)
    epsg = gdf.crs.to_epsg() if gdf.crs else None
    crs_match = epsg == EXPECTED_EPSG
    ok &= crs_match
    print(f"b. CRS: {gdf.crs} | EPSG: {epsg} |", "MATCH" if crs_match else "MISMATCH")
    print("=" * 70)
    print("c. 字段名与数据类型:")
    for col, dt in gdf.dtypes.items():
        print(f"   {col:<12} {dt}")
    print("=" * 70)
    print(f"d. 中文字段随机抽 10 行 (seed={SAMPLE_SEED}):")
    # geopandas>=1.0 的 pyogrio 引擎给字符串列 'str' dtype 而非 'object',
    # 故显式点名中文列,缺列时回退到全部非数值列
    text_cols = [c for c in ("district", "city", "province") if c in gdf.columns]
    if not text_cols:
        text_cols = [c for c in gdf.columns
                     if c != "geometry" and not pd.api.types.is_numeric_dtype(gdf[c])]
    sample = gdf[text_cols].sample(10, random_state=SAMPLE_SEED)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(sample.to_string())
    print("=" * 70)
    h = pd.to_numeric(gdf["height"], errors="coerce")
    print("e. height 统计:")
    print(f"   min: {h.min()}   max: {h.max()}   median: {h.median()}")
    print(f"   空值: {h.isna().sum()}  (原始 dtype: {gdf['height'].dtype})")
    print("=" * 70)
    tail = h[h >= SUPERTALL_CUTOFF]
    print(f"f. height >= {SUPERTALL_CUTOFF} 的建筑数量: {len(tail)}")
    print("   取值分布 (value: count):")
    print(tail.value_counts().sort_index().to_string())
    print("=" * 70)
    print("QC done — read-only, no files written.",
          "ALL BASELINE CHECKS PASSED" if ok else "BASELINE DEVIATION — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
