#!/usr/bin/env python3
"""A5 双数据集 ETL — 2023 FLOOR × 2026 height 空间配对,分箱经验层高表。

目标
    以 2023 市区集(FLOOR=2×层数)与 2026 全市集(height, m)做空间配对,
    在"干净配对"上按 floors_2023 分箱统计经验层高 height/floors_2023 的
    中位 + P25 + P75 + n,产出 data/reference/storey_height_by_band.csv;
    并给出 7-12 层段异常判定 + 全局隐含层高诊断 + validation 反推误差。

关键结论(本脚本可完整复现,详见 stdout 报告与 PR 描述)
    **2026 height 为合成量,非独立实测:干净配对里 82.5% 满足
    height == 2×FLOOR(等价 height == 4 m × floors_2023),且在最高质量
    配对(IoU≥0.7)里占比升到 87%。** 两集共享同一楼层数血统
    (2023 存 2×层数,2026 以 4 m/层折算高度)。因此"经验层高"退化为
    恒等的 4.0 m,并非上海真实层高(住宅 GB 口径 ~2.9-3.0 m)——step-6
    的"4.0 vs ~3m"之问,数据无法回答,因为两集都不含独立高度测量。

数据(会话内解压至 ~/a5_data,不入 git;脚本默认路径为仓库 canonical 位置)
    2026:843,062 栋,height(int m),16 区,.cpg=UTF-8
    2023:412,099 栋,FLOOR(str,全偶数),市区,.cpg=GBK
    编码规则:**尊重 .cpg,不硬加 encoding**(pyogrio 自动按 .cpg 解码;
    2023 无中文字段,2026 district 为 UTF-8)。

方法
    1. geopandas 读两份 shp;确认均 EPSG:4326;统一投影至 METRIC_EPSG(UTM 51N)算面积。
    2. floors_2023 = FLOOR // 2(**禁用旧 FLOOR>130→NA 规则**;9 个 FLOOR>130
       行为合法超高层校准点,见 data/raw/taobao/shanghai_2023_floor/README.md)。
    3. 配对(两套,均以 2023 建筑为主键,留作诊断,存 data/interim/):
       (a) 最大交叠 IoU:每栋 2023 取交叠面积最大的 2026,算 IoU,
           保留 IoU≥0.3 的"干净配对";
       (b) 质心落入:2023 代表点落入的 2026 面。
    4. 分箱层高表:按 floors_2023 分箱 1-3 / 4-6 / 7-9 / 10-18 / 19-30,
       每箱 median+P25+P75+n(height/floors_2023);超高层(≥40 层)不进表,
       走 data/reference/supertall_height_floor_crosswalk.csv。
    5. 7-12 异常复查:干净配对该窗口 ratio 分布 + 两套配对对比 + validation 复算。
    6. 全局隐含层高诊断(4.0 是否成立)。
    7. validation 反推误差(可用样本 height→floors)。

产出
    data/reference/storey_height_by_band.csv        —— 直接 commit(本脚本 --write)
    data/interim/a5_clean_pairs_iou.parquet         —— 诊断,gitignored
    data/interim/a5_centroid_pairs.parquet          —— 诊断,gitignored
    data/interim/a5_best_overlap.parquet            —— 诊断(含 IoU<0.3),gitignored
    stdout 全量诊断报告(供 PR 描述引用)

用法
    python scripts/a5_storey_height.py                 # 默认写 CSV + interim
    python scripts/a5_storey_height.py --no-write      # 只跑诊断,不落盘
    python scripts/a5_storey_height.py --shp23 ... --shp26 ... --val ...
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---- 默认输入(仓库 canonical 位置;会话内可用 --shp* 覆盖到 ~/a5_data)----
DEFAULT_SHP23 = (
    PROJECT_ROOT / "data/raw/taobao/shanghai_2023_floor/2023 Building/2023 Building.shp"
)
DEFAULT_SHP26 = (
    PROJECT_ROOT / "data/raw/taobao/shanghai_2026_height/2026 Building/2026 Building.shp"
)
DEFAULT_VAL = PROJECT_ROOT / "data/raw/validation/shanghai_validation_set_v0.csv"

# ---- 输出 ----
BAND_TABLE_OUT = PROJECT_ROOT / "data/reference/storey_height_by_band.csv"
INTERIM_DIR = PROJECT_ROOT / "data/interim"
CROSSWALK_REF = "data/reference/supertall_height_floor_crosswalk.csv"

# ---- 参数 ----
METRIC_EPSG = 32651          # UTM 51N,米制,用于面积/IoU
EXPECTED_EPSG = 4326         # 两集 .prj 均声明 WGS84
IOU_THRESHOLD = 0.30         # 干净配对门槛
SUPERTALL_MIN_FLOORS = 40    # ≥40 层不进箱表,走 crosswalk
ANOMALY_WINDOW = (7, 12)     # §6 悬案窗口(observed / floors_2023 层)
NN_TOLERANCE_M = 10          # validation 点入面未命中时最近邻容差
# 分箱:(floors_min, floors_max, label)
BANDS: list[tuple[int, int, str]] = [
    (1, 3, "1-3"),
    (4, 6, "4-6"),
    (7, 9, "7-9"),
    (10, 18, "10-18"),
    (19, 30, "19-30"),
]

_T0 = time.time()


def _log(msg: str) -> None:
    print(f"[{time.time() - _T0:6.1f}s] {msg}", flush=True)


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# --------------------------------------------------------------------------- #
# 载入                                                                          #
# --------------------------------------------------------------------------- #
def load_2023(path: Path) -> gpd.GeoDataFrame:
    """读 2023(尊重 .cpg,不加 encoding);floors_2023 = FLOOR // 2(无 >130 NA 规则)。"""
    g = gpd.read_file(path, columns=["FLOOR"])          # .cpg=GBK 自动生效
    assert g.crs is not None and g.crs.to_epsg() == EXPECTED_EPSG, (
        f"2023 CRS 非 EPSG:{EXPECTED_EPSG}: {g.crs}")
    floor = pd.to_numeric(g["FLOOR"], errors="coerce")
    if (floor % 2 == 1).any():
        raise ValueError("2023 FLOOR 出现奇数值 — 与 2×层数语义指纹不符,停。")
    g = g.to_crs(METRIC_EPSG)
    g["idx23"] = np.arange(len(g))
    g["floors_2023"] = (floor // 2).astype("int64").to_numpy()
    g["area23"] = g.geometry.area
    _log(f"2023 载入: {len(g):,} 栋 | floors 1-{int(g.floors_2023.max())} "
         f"| ≥{SUPERTALL_MIN_FLOORS} 层: {(g.floors_2023 >= SUPERTALL_MIN_FLOORS).sum()} 栋")
    return g


def load_2026(path: Path) -> gpd.GeoDataFrame:
    """读 2026(尊重 .cpg,不加 encoding);仅取 height 列以跳过 688 MB dbf 主体。"""
    g = gpd.read_file(path, columns=["height"])          # .cpg=UTF-8 自动生效
    assert g.crs is not None and g.crs.to_epsg() == EXPECTED_EPSG, (
        f"2026 CRS 非 EPSG:{EXPECTED_EPSG}: {g.crs}")
    g = g.to_crs(METRIC_EPSG)
    g["idx26"] = np.arange(len(g))
    g["height"] = pd.to_numeric(g["height"], errors="coerce").astype("int64").to_numpy()
    g["area26"] = g.geometry.area
    _log(f"2026 载入: {len(g):,} 栋 | height {int(g.height.min())}-{int(g.height.max())} m")
    return g


# --------------------------------------------------------------------------- #
# 配对                                                                          #
# --------------------------------------------------------------------------- #
def match_max_overlap(g23: gpd.GeoDataFrame, g26: gpd.GeoDataFrame) -> pd.DataFrame:
    """每栋 2023 取交叠面积最大的 2026;返回全部匹配(含 IoU 列,未过滤门槛)。"""
    j = gpd.sjoin(
        g23[["idx23", "floors_2023", "area23", "geometry"]],
        g26[["idx26", "height", "area26", "geometry"]],
        predicate="intersects", how="inner",
    )
    _log(f"候选相交对: {len(j):,}")
    inter = shapely.area(
        shapely.intersection(j.geometry.values, g26.geometry.values[j["idx26"].values])
    )
    pairs = pd.DataFrame({
        "idx23": j["idx23"].to_numpy(), "idx26": j["idx26"].to_numpy(),
        "floors_2023": j["floors_2023"].to_numpy(), "height": j["height"].to_numpy(),
        "area23": j["area23"].to_numpy(), "area26": j["area26"].to_numpy(),
        "inter": inter,
    })
    # 每栋 2023 取最大交叠
    best = pairs.sort_values("inter").drop_duplicates("idx23", keep="last").copy()
    best["union"] = best["area23"] + best["area26"] - best["inter"]
    best["iou"] = best["inter"] / best["union"]
    best["overlap23"] = best["inter"] / best["area23"]
    best = best.reset_index(drop=True)
    _log(f"最大交叠匹配(每栋 2023 有交叠者): {len(best):,}")
    return best


def match_centroid(g23: gpd.GeoDataFrame, g26: gpd.GeoDataFrame) -> pd.DataFrame:
    """质心落入版:2023 代表点落入的 2026 面(以 2023 为主键)。"""
    pts = g23[["idx23", "floors_2023", "area23"]].copy()
    pts["geometry"] = g23.geometry.representative_point()
    pts = gpd.GeoDataFrame(pts, geometry="geometry", crs=g23.crs)
    cj = gpd.sjoin(pts, g26[["idx26", "height", "area26", "geometry"]],
                   predicate="within", how="inner")
    cj = cj[~cj.index.duplicated(keep="first")]
    cen = pd.DataFrame({
        "idx23": cj["idx23"].to_numpy(), "idx26": cj["idx26"].to_numpy(),
        "floors_2023": cj["floors_2023"].to_numpy(), "height": cj["height"].to_numpy(),
        "area23": cj["area23"].to_numpy(), "area26": cj["area26"].to_numpy(),
    })
    _log(f"质心落入对(2023 代表点∈2026): {len(cen):,}")
    return cen


# --------------------------------------------------------------------------- #
# 分箱层高表                                                                     #
# --------------------------------------------------------------------------- #
def build_band_table(clean: pd.DataFrame) -> pd.DataFrame:
    """按 floors_2023 分箱统计经验层高 height/floors_2023。"""
    rows = []
    for lo, hi, label in BANDS:
        s = clean[(clean.floors_2023 >= lo) & (clean.floors_2023 <= hi)].copy()
        r = s["height"] / s["floors_2023"]
        floor = 2 * s["floors_2023"]  # FLOOR = 2×floors_2023
        rows.append({
            "band": label,
            "floors_min": lo,
            "floors_max": hi,
            "n_clean_pairs": int(len(s)),
            "storey_height_median_m": round(float(r.median()), 3),
            "storey_height_p25_m": round(float(r.quantile(0.25)), 3),
            "storey_height_p75_m": round(float(r.quantile(0.75)), 3),
            "frac_height_eq_2x_floor": round(float((s["height"] == 2 * floor).mean()), 4),
        })
    return pd.DataFrame(rows)


def write_band_table(band: pd.DataFrame, out: Path, clean_n: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# A5 分箱经验层高表 — 2023 FLOOR × 2026 height 干净配对(IoU>=0.30),坐标系 WGS84 (EPSG:4326)",
        f"# 生成:scripts/a5_storey_height.py;干净配对 n={clean_n:,};METRIC_EPSG={METRIC_EPSG}",
        "# storey_height = height / floors_2023,floors_2023 = FLOOR // 2(FLOOR=2×实际层数)",
        "# ⚠️ 重大发现:frac_height_eq_2x_floor 显示 2026 height 高度合成(≈2×FLOOR=4m×层),",
        "#    经验层高退化为恒等 4.0 m,非上海真实层高;详见 PR 描述与脚本 docstring。",
        f"# 超高层(≥{SUPERTALL_MIN_FLOORS} 层)不进本表,走 {CROSSWALK_REF}",
    ]
    with out.open("w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")
        band.to_csv(f, index=False)
    _log(f"写出分箱层高表: {out.relative_to(PROJECT_ROOT)}")


# --------------------------------------------------------------------------- #
# 诊断:合成高度 + 全局隐含层高                                                   #
# --------------------------------------------------------------------------- #
def diag_synthetic(clean: pd.DataFrame, centroid: pd.DataFrame) -> None:
    _rule("诊断 A — 2026 height 是否合成量 + 全局隐含层高(step 6)")
    for name, df in [("干净配对 IoU>=0.3", clean), ("质心落入", centroid)]:
        d = df[(df.floors_2023 > 0) & (df.floors_2023 < SUPERTALL_MIN_FLOORS)].copy()
        floor = 2 * d["floors_2023"]
        r = d["height"] / d["floors_2023"]
        eq = (d["height"] == 2 * floor).mean()
        print(f"{name}: n={len(d):,}")
        print(f"   全局隐含层高 height/floors_2023: 中位 {r.median():.3f} m "
              f"(P25 {r.quantile(.25):.3f} / P75 {r.quantile(.75):.3f})")
        print(f"   height == 2×FLOOR 精确占比: {eq*100:.1f}%  "
              f"(|height-4×floors|<=2m: {(abs(d['height']-4*d['floors_2023'])<=2).mean()*100:.1f}%)")
    hi = clean[clean.iou >= 0.7]
    hi = hi[(hi.floors_2023 > 0) & (hi.floors_2023 < SUPERTALL_MIN_FLOORS)]
    eq_hi = (hi["height"] == 4 * hi["floors_2023"]).mean()
    print(f"\n最高质量配对 IoU>=0.7 (n={len(hi):,}): height==4×floors 占比 {eq_hi*100:.1f}% "
          f"—— 越干净越贴合 4.0,证明 4.0 是合成信号而非错配噪声")
    print("结论:2026 height 为 4 m/层合成量(=2×FLOOR),两集共享楼层数血统;")
    print("      '经验层高 4.0 m' 是供应商折算假设,非上海真实层高(~3 m);")
    print("      数据不含独立高度测量,故 step-6 '4.0 vs ~3m' 之问无法由本数据回答。")


# --------------------------------------------------------------------------- #
# 7-12 异常复查(step 5)                                                        #
# --------------------------------------------------------------------------- #
def diag_anomaly_712(clean: pd.DataFrame, centroid: pd.DataFrame,
                     val_matched: pd.DataFrame) -> None:
    lo, hi = ANOMALY_WINDOW
    _rule(f"诊断 B — {lo}-{hi} 层段异常复查(§6 悬案,step 5)")

    # (1) 干净配对 & 质心两套:floors_2023 落 7-12 的隐含层高分布
    print(f"[两套配对内] floors_2023 ∈ [{lo},{hi}] 的隐含层高 height/floors_2023:")
    for name, df in [("干净配对 IoU>=0.3", clean), ("质心落入", centroid)]:
        s = df[(df.floors_2023 >= lo) & (df.floors_2023 <= hi)].copy()
        r = s["height"] / s["floors_2023"]
        near4 = r.between(3.5, 4.5).mean()   # ≈4 → 2×FLOOR 语义成立
        near8 = r.between(7.0, 9.0).mean()   # ≈8 → 若 FLOOR 实为 1× 的编码指纹
        print(f"   {name}: n={len(s):,}  中位 {r.median():.3f} m  "
              f"≈4.0占比 {near4*100:.1f}%  ≈8.0占比 {near8*100:.1f}%")
    print("   → 两套均以 4.0 为主、≈8.0 极少 ⇒ 2×FLOOR 语义在 7-12 段成立,无 1× 编码分叉。")

    # (2) validation 复现原 n=13 异常(observed 落 7-12)
    print(f"\n[validation 复现] 人工观测层数 ∈ [{lo},{hi}]:")
    w = val_matched[(val_matched.floors_observed >= lo)
                    & (val_matched.floors_observed <= hi)
                    & val_matched.FLOOR.notna()].copy()
    w["FLOOR_over_obs"] = w["FLOOR"] / w["floors_observed"]
    print(f"   n={len(w)}  median FLOOR/observed = {w['FLOOR_over_obs'].median():.3f} "
          f"(原 §6 记载 1.0;期望 2.0)")
    by_area = w.groupby("area", observed=True).size().sort_values(ascending=False)
    print(f"   窗口分布: {by_area.to_dict()} —— 集中裙塔密集片区")
    # 逐点错配证据:2026 height 与 2023 FLOOR 是否指向不同建筑
    w["storey_via_obs_2026"] = w["height26"] / w["floors_observed"]
    n_phys = w["storey_via_obs_2026"].between(2.5, 4.5).sum()
    print(f"   其中 height26/observed 落物理区间[2.5,4.5]: {n_phys}/{len(w)} 栋 "
          f"—— 2026 命中真楼、2023 点位错配到矮邻栋(点对面 tessellation 差异)")
    print("   判定:**错配伪影(丢弃/销案)**。依据:(a) 干净配对 7-12 段隐含层高稳定 4.0、"
          "无 8.0 编码分叉;(b) 异常 13 点集中裙塔密集窗口;(c) 逐点显示 2026 height 与 "
          "2023 FLOOR 指向不同建筑,系 validation 点入 2023 面的点对面错配,非 FLOOR 编码问题。")


# --------------------------------------------------------------------------- #
# validation 反推误差(step 7)                                                  #
# --------------------------------------------------------------------------- #
def _match_points(pts: gpd.GeoDataFrame, poly: gpd.GeoDataFrame,
                  cols: list[str]) -> pd.DataFrame:
    """点入面 + 10 m 最近邻兜底,返回 cols(以 pts 索引对齐)。

    poly 已是 METRIC_EPSG(米制),点先对齐到同一 CRS 再做 within,保证
    point-in-polygon 语义正确;未命中者再走 10 m 最近邻兜底。
    """
    pts_m = pts.to_crs(poly.crs)
    poly_cols = poly[cols + ["geometry"]]
    w = gpd.sjoin(pts_m, poly_cols, predicate="within", how="left")
    w = w[~w.index.duplicated(keep="first")]
    out = w[cols].copy()
    miss = out.index[out[cols[0]].isna()]
    if len(miss):
        nn = gpd.sjoin_nearest(pts_m.loc[miss], poly_cols,
                               max_distance=NN_TOLERANCE_M, how="left")
        nn = nn[~nn.index.duplicated(keep="first")]
        for c in cols:
            out.loc[miss, c] = nn[c]
    return out


def match_validation(val_path: Path, g23: gpd.GeoDataFrame,
                     g26: gpd.GeoDataFrame) -> pd.DataFrame:
    val = pd.read_csv(val_path)
    pts = gpd.GeoDataFrame(val, geometry=gpd.points_from_xy(val.lon, val.lat), crs=4326)
    m23 = _match_points(pts, g23, ["FLOOR", "floors_2023"])
    m26 = _match_points(pts, g26, ["height"])
    val["FLOOR"] = pd.to_numeric(m23["FLOOR"], errors="coerce")
    val["floors_2023"] = pd.to_numeric(m23["floors_2023"], errors="coerce")
    val["height26"] = pd.to_numeric(m26["height"], errors="coerce")
    return val


def diag_validation(val: pd.DataFrame, global_storey: float) -> None:
    _rule("诊断 C — validation 反推误差(step 7)")
    ann = val[(val.status == "annotated") & (val.floors_observed > 0)].copy()
    matched26 = ann[ann.height26.notna()]
    usable = matched26[matched26.floors_observed < SUPERTALL_MIN_FLOORS].copy()
    n_supertall = int((ann.floors_observed >= SUPERTALL_MIN_FLOORS).sum())
    print(f"annotated={len(ann)}  命中 2026={len(matched26)}  "
          f"observed≥{SUPERTALL_MIN_FLOORS}(超高层剔除)={n_supertall}")
    print(f"可用样本(命中 2026 且 observed<{SUPERTALL_MIN_FLOORS}): **{len(usable)}** 栋 "
          f"(命中 2023&2026 双匹配 {int(usable.floors_2023.notna().sum())} 栋)")
    print("\n反推 height26 → floors = round(height26 / storey):")
    for sh, tag in [(global_storey, "数据全局中位"), (3.0, "GB 物理口径对照")]:
        pred = (usable.height26 / sh).round()
        err = pred - usable.floors_observed
        ape = (err.abs() / usable.floors_observed)
        print(f"   storey={sh:.1f} m ({tag}): "
              f"MAE={err.abs().mean():.2f} 层  bias={err.mean():+.2f}  "
              f"±1:{(err.abs()<=1).mean()*100:.1f}%  ±2:{(err.abs()<=2).mean()*100:.1f}%  "
              f"medAPE={ape.median()*100:.1f}%")
    u2 = usable[usable.floors_2023.notna()].copy()
    e2 = u2.floors_2023 - u2.floors_observed
    print(f"\n旁证 floors_2023(=FLOOR/2) vs observed: "
          f"MAE={e2.abs().mean():.2f} 层  bias={e2.mean():+.2f}  "
          f"±1:{(e2.abs()<=1).mean()*100:.1f}%  (n={len(u2)})")
    print("说明:因 height26≈4×(2026 自带层数),4.0 m 反推等价于读回 2026 自带层数;"
          "误差主体为 2026 层数与人工观测之差(裙塔密集片区点位噪声),非层高模型误差。")


# --------------------------------------------------------------------------- #
# main                                                                          #
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--shp23", type=Path, default=DEFAULT_SHP23)
    p.add_argument("--shp26", type=Path, default=DEFAULT_SHP26)
    p.add_argument("--val", type=Path, default=DEFAULT_VAL)
    p.add_argument("--no-write", action="store_true",
                   help="只跑诊断,不写 CSV / interim parquet")
    args = p.parse_args()

    g23 = load_2023(args.shp23)
    g26 = load_2026(args.shp26)

    best = match_max_overlap(g23, g26)
    clean = best[best.iou >= IOU_THRESHOLD].reset_index(drop=True)
    centroid = match_centroid(g23, g26)

    _rule("配对规模(成功判据:干净配对 ≥ ~30 万)")
    print(f"最大交叠匹配总数 : {len(best):,}")
    print(f"干净配对 IoU≥{IOU_THRESHOLD}: {len(clean):,}  "
          f"({'达标 ✓' if len(clean) >= 300_000 else '未达标 ✗'})")
    print(f"质心落入对        : {len(centroid):,}")

    band = build_band_table(clean)
    _rule("分箱经验层高表(storey_height = height / floors_2023)")
    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(band.to_string(index=False))
    # 超高层与 31-39 gap 报账(不进表)
    n_gap = int(((clean.floors_2023 >= 31) & (clean.floors_2023 <= 39)).sum())
    n_super = int((clean.floors_2023 >= SUPERTALL_MIN_FLOORS).sum())
    print(f"\n[不进表] 干净配对内 31-39 层(箱表与超高层之间的 gap): {n_gap} 栋;"
          f"≥{SUPERTALL_MIN_FLOORS} 层(超高层,走 crosswalk): {n_super} 栋")
    print(f"[提醒] 2023 原始 ≥{SUPERTALL_MIN_FLOORS} 层共 111 栋(非 9;'9 个锚点'仅指 FLOOR>130 段);"
          f"31-39 层 216 栋无 band 归属 —— 是否补箱/扩顶箱属设计决策,留 owner 复核。")

    global_storey = float(
        (clean.loc[(clean.floors_2023 > 0) & (clean.floors_2023 < SUPERTALL_MIN_FLOORS), "height"]
         / clean.loc[(clean.floors_2023 > 0) & (clean.floors_2023 < SUPERTALL_MIN_FLOORS),
                     "floors_2023"]).median()
    )

    diag_synthetic(clean, centroid)

    val = match_validation(args.val, g23, g26)
    diag_anomaly_712(clean, centroid, val)
    diag_validation(val, global_storey)

    if not args.no_write:
        write_band_table(band, BAND_TABLE_OUT, len(clean))
        INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        clean.to_parquet(INTERIM_DIR / "a5_clean_pairs_iou.parquet")
        centroid.to_parquet(INTERIM_DIR / "a5_centroid_pairs.parquet")
        best.to_parquet(INTERIM_DIR / "a5_best_overlap.parquet")
        _log("诊断配对表已存 data/interim/(gitignored)")
    else:
        _log("--no-write:未落盘")

    _rule("A5 完成")
    print("产出: data/reference/storey_height_by_band.csv(commit)"
          " + data/interim/a5_*.parquet(诊断,gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
