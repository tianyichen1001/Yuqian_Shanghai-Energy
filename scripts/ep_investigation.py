#!/usr/bin/env python3
"""A1 附加侦查 — 2026 数据集 ep 字段身份鉴定(只读)。

用途
    检验假设「ep = 层数」,输出四组证据:
    1. ep 全貌:唯一值数量 / value_counts / min-max / 空零负值计数,
       以及取值是否构成连续整数区间(层数应为 100+ 连续整数;
       分类编码只有少量离散值)
    2. height/ep 比值分布(中位数、P5–P95、落在 2.5–5.0 m 合理层高
       区间的占比):若 ep 是层数,比值应集中于合理层高
    3. 两栋 height=415 建筑的全部字段(上海中心实际 128 层、环球金融
       中心 101 层,若 ep≈128/101 则假设成立)
    4. height 降序 top 20 全字段 + 每个 ep 取值的画像(计数 / height
       与 Area 中位数 / 最集中区县),供人工识别语义
    只读:不写文件、不改数据。

结论(2026-07-04 实测,写入数据集 README)
    三项证据一致否定「ep = 层数」:仅 14 个离散取值
    {1,2,4,6,7,8,9,10,11,12,13,14,18,26};height/ep 中位数 1.33 m,
    落入合理层高区间的仅 ~19%;两栋 415 m 建筑 ep=2 而非 128/101。
    ep 是分类编码(疑似高度/体量档位,ep=2 ≈ 约百米以上高层专属),
    语义待供应商核实,严禁当层数用。

输入
    默认路径(相对仓库根):
    data/raw/taobao/shanghai_2026_height/2026 Building/2026 Building.shp
    可用 --shp 覆盖。编码规则同 qc_shanghai_2026.py:必须 utf-8,严禁 gbk。

输出
    stdout 侦查报告。
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

PLAUSIBLE_STOREY_HEIGHT = (2.5, 5.0)  # 合理层高区间 (m)
CAP_HEIGHT = 415                      # 顶端截断值 (m)
TOP_N = 20


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shp", type=Path, default=DEFAULT_SHP)
    args = parser.parse_args()

    gdf = gpd.read_file(args.shp, encoding="utf-8")  # 严禁 gbk / 省略 encoding
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    ep = df["ep"]

    print("=" * 72)
    print("1. ep 全貌")
    print("=" * 72)
    uniq = sorted(int(v) for v in ep.unique())
    print(f"唯一值数量: {ep.nunique()}   min: {ep.min()}   max: {ep.max()}")
    print(f"空值: {ep.isna().sum()}   零值: {(ep == 0).sum()}   负值: {(ep < 0).sum()}")
    print("\nvalue_counts 前 30:")
    print(ep.value_counts().head(30).to_string())
    full_range = list(range(uniq[0], uniq[-1] + 1))
    print("\n唯一值构成连续整数区间:", "是" if uniq == full_range else "否")
    missing = [v for v in full_range if v not in set(uniq)]
    print(f"区间内缺失取值 ({len(missing)} 个): {missing}")

    print("=" * 72)
    print("2. height/ep 比值分布 (ep>0)")
    print("=" * 72)
    pos = df[df["ep"] > 0]
    ratio = pos["height"] / pos["ep"]
    q = ratio.quantile([0.05, 0.25, 0.50, 0.75, 0.95])
    lo, hi = PLAUSIBLE_STOREY_HEIGHT
    share = ((ratio >= lo) & (ratio <= hi)).mean() * 100
    print(f"样本数: {len(pos):,}   中位数: {q[0.50]:.3f} m")
    print(f"P5: {q[0.05]:.3f}   P25: {q[0.25]:.3f}   P75: {q[0.75]:.3f}   P95: {q[0.95]:.3f} (m)")
    print(f"落在 {lo}–{hi} m 合理层高区间的占比: {share:.2f}%")

    print("=" * 72)
    print(f"3. height={CAP_HEIGHT} 建筑的全部字段")
    print("=" * 72)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(df[df["height"] == CAP_HEIGHT].to_string())

    print("=" * 72)
    print(f"4a. height 降序 top {TOP_N} (全部字段)")
    print("=" * 72)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(df.sort_values("height", ascending=False).head(TOP_N).to_string())

    print("=" * 72)
    print("4b. 每个 ep 取值的画像")
    print("=" * 72)
    profile = df.groupby("ep").agg(
        n=("ep", "size"),
        h_med=("height", "median"), h_min=("height", "min"), h_max=("height", "max"),
        area_med=("Area", "median"),
    )
    profile["top_district"] = df.groupby("ep")["district"].agg(
        lambda s: s.value_counts().index[0])
    profile["top_district_share"] = df.groupby("ep").apply(
        lambda s: s["district"].value_counts(normalize=True).iloc[0],
        include_groups=False).round(2)
    print(profile.to_string())
    print("=" * 72)
    print("done — read-only, no files written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
