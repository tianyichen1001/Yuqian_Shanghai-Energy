#!/usr/bin/env python3
"""A2 质检脚本 — Taobao Shanghai 2023 central-districts FLOOR shapefile 只读 QC。

用途
    对 2023 市区建筑层数数据集跑一次只读质检,输出七项报告:
    a. 总行数(与实测基准 412,099 比对;供应商宣传 412,100 多记 1,
       DBF 头部自洽,与 2026 集差 1 先例同判,2026-07-05 定案)
    b. CRS(预期 WGS84 / EPSG:4326)
    c. 全部字段名与类型(schema 极简:仅 FLOOR + geometry)
    d. FLOOR 随机抽 10 行(本集无中文字段可抽)
    e. FLOOR 体检:min/max/median/空值/≤0/非整数/全偶数检查/>130 分布
       (>130 的 9 行按 2026-07-05 定案为合法超高层,非脏值)
    f. height/FLOOR 比值 —— 本集无 height 类字段,固定跳过并说明
    g. 与 2026 数据集字段对照(仅 geometry 共有 → A5 只能空间 join)
    只读:不写文件、不改数据、不触碰 git。

输入
    默认路径(相对仓库根):
    data/raw/taobao/shanghai_2023_floor/2023 Building/2023 Building.shp
    来源:数据仓库 git 树 shanghai_2023_floor.zip
    (zip MD5 = 6E033592072263F658DA637B504A38E4,
     内层 .shp MD5 = 674A7662AF9E36992D04F7494D3203BA)。
    可用 --shp 覆盖。

输出
    stdout 质检报告,退出码 0(基准全部命中)/ 1(任一项偏离)。

编码规则
    .cpg 声明 GBK,按声明以 encoding="gbk" 读取(与 2026 集的 UTF-8 不同,
    两集规则不可混用)。实测本集无中文字段(FLOOR 为纯数字文本),编码
    选择无实际影响,但仍遵 .cpg 声明以保持规程一致。

FLOOR 语义(2026-07-05 定案)
    FLOOR = 2 × 实际层数,换算 floors = FLOOR // 2。
    三路证据见 scripts/floor_semantics.py。本脚本仅按原始值体检。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHP = (
    PROJECT_ROOT
    / "data/raw/taobao/shanghai_2023_floor/2023 Building/2023 Building.shp"
)

# 实测基准(2026-07-05 定案,见 data/raw/taobao/shanghai_2023_floor/README.md)
EXPECTED_ROWS = 412_099
EXPECTED_EPSG = 4326
SAMPLE_SEED = 42
SUPERTALL_FLOOR_CUTOFF = 130  # FLOOR>130 段:合法超高层(隐含 66–118 层)

# 2026 集字段(对照表基准,见 data/raw/taobao/shanghai_2026_height/README.md)
FIELDS_2026 = ["height", "Area", "ep", "district", "city", "province", "geometry"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shp", type=Path, default=DEFAULT_SHP)
    args = parser.parse_args()

    gdf = gpd.read_file(args.shp, encoding="gbk")  # per .cpg 声明(本集为 GBK)
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
    print("c. 字段名与数据类型(预期仅 FLOOR + geometry):")
    for col, dt in gdf.dtypes.items():
        print(f"   {col:<12} {dt}")
    print("=" * 70)
    print(f"d. FLOOR 随机抽 10 行 (seed={SAMPLE_SEED};本集无中文字段):")
    print(gdf["FLOOR"].sample(10, random_state=SAMPLE_SEED).to_string())
    print("=" * 70)
    f = pd.to_numeric(gdf["FLOOR"], errors="coerce")  # 原始为 str,须转数值
    print("e. FLOOR 体检:")
    print(f"   min: {f.min()}   max: {f.max()}   median: {f.median()}")
    print(f"   空值: {f.isna().sum()}   ≤0: {(f <= 0).sum()}   "
          f"非整数: {(f.dropna() != f.dropna().round()).sum()}")
    odd = (f % 2 == 1).sum()
    print(f"   奇数值行数: {odd}(应为 0 —— FLOOR=2×层数,全偶数是语义指纹)")
    ok &= odd == 0
    hi = f[f > SUPERTALL_FLOOR_CUTOFF]
    print(f"   FLOOR > {SUPERTALL_FLOOR_CUTOFF}: {len(hi)} 行 "
          f"(合法超高层,隐含层数 = FLOOR//2):")
    tab = hi.value_counts().sort_index()
    for v, n in tab.items():
        print(f"      FLOOR={int(v)} ×{n} → {int(v) // 2} 层")
    print("=" * 70)
    print("f. height/FLOOR 比值:跳过 —— 本集无 height 类字段(仅 2026 集有)")
    print("=" * 70)
    cols = list(gdf.columns)
    print("g. 与 2026 数据集字段对照:")
    print(f"   两边都有 : {[c for c in cols if c in FIELDS_2026]}")
    print(f"   仅 2023  : {[c for c in cols if c not in FIELDS_2026]}")
    print(f"   仅 2026  : {[c for c in FIELDS_2026 if c not in cols]}")
    print("   ⇒ 无公共属性键,A5 双数据集关联只能空间 join")
    print("=" * 70)
    print("QC done — read-only, no files written.",
          "ALL BASELINE CHECKS PASSED" if ok else "BASELINE DEVIATION — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
