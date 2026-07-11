#!/usr/bin/env python3
"""A6 Stage 1 — 规则打标(rule-based archetype seeding)→ master + 覆盖率四个数。

七步(全部由 config/a6_rules.yaml 驱动,源码不写魔数):
    1. 底盘:读 2026 全市 843,062 栋(尊重 .cpg,勿硬加 encoding),CRS WGS84;
       floors = round(height/4);height>=160 m 打 supertall flag(该段不走 /4)。
    2. supertall 处置:与 2023 集最大交叠 IoU>=0.3(复用 A5 方法)取 FLOOR//2 作层数;
       无配对者 floors=NA + flag=crosswalk_or_cnbh(不硬算)。
    3. EULUC 先验:建筑质心落入 parcel 取 Class;落不进标 euluc_out(EULUC-scoped 依据)。
    4. POI 播种:A3a POI(clean + valwin,用 WGS84 列)按距离挂最近建筑 ——
       mall 信号 0601<=150 m【A6.2:删 06<=100 m 兜底分支,A3b 后重估】;
       hotel 信号 (1001<=150 m) OR
       (1002<=150 m 且建筑 euluc_class∈{1,2})【A6.1 修订,堵住宅楼过度挂靠】。
       多 typecode 方案 C(1/N 分票);诊断输出多码占比+码数分布 + 方案 A vs C 在
       validation 上的命中差异(计票悬案实证材料)。
    5. mixed_use 候选:EULUC Class 1 + 060000 命中 → mixed_use_candidate。
    6. 规则表打标(优先级 config.priority,首个命中为准):
       ① supertall(横切 flag)② mixed_use 候选 ③ mall ④ hotel
       ⑤ EULUC 直接命中类→archetype(residential 按 10 层切 mid/high;
       Class 9 → sport_culture 捆绑标签带 bundled flag;Class 2 → unknown)【A6.1】
       ⑥ unknown。
    7. 组装:master→GPKG;覆盖率四个数 ×(全市 / EULUC-scoped)双口径
       ×(栋数 / GFA=area×floors)双权重【A6.1】;诊断 a validation 分 archetype
       accuracy(捆绑命中口径);诊断 b 10 层线 ±2 扰动翻转率;
       诊断 d Class 3/10 内建筑画像(层数×面积分位数,村居假说)【A6.1】。

坐标系口径(重要)
    2026 footprints、EULUC、POI wgs 列、validation 均为**真 WGS84**(EPSG:4326):
    2026 footprints 经 validation checkpoint-2 实证真 WGS84;POI 的 wgs_lng/wgs_lat
    系 A3a GCJ→WGS 已转换列;EULUC A4 已定 EPSG:4326。故 A6 内部空间 join **不再**
    做 GCJ→WGS(再转会破坏对齐)。米制运算统一投影至 metric_epsg(UTM 51N)。

产出
    outputs/module_a_master.gpkg              —— 全 master(gitignored;>100MB 走私仓 zip)
    data/reference/a6_coverage_stats.csv      —— 覆盖率四个数 × 双口径 + label_rule 分布(commit)
    data/reference/a6_validation_diagnostics.csv —— 分 archetype accuracy + 翻转率 + A/C(commit)
    data/interim/a6_*.parquet                 —— 诊断中间表(gitignored)
    stdout 全量报告(供 PR 描述)

用法
    python scripts/a6_stage1.py                       # 默认写盘
    python scripts/a6_stage1.py --no-write            # 只跑不写
    python scripts/a6_stage1.py --shp26 ... --euluc ... --poi-clean ... --poi-valwin ...
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()

# ---- 默认输入(会话内 ~/a5_data、~/a6_data;仓库 canonical 由 --* 覆盖)----
DEF_SHP26 = HOME / "a5_data/2026 Building/2026 Building.shp"
DEF_SHP23 = HOME / "a5_data/2023 Building/2023 Building.shp"
DEF_EULUC = HOME / "a6_data/euluc_shanghai_2022.gpkg"
DEF_POI_CLEAN = PROJECT_ROOT / "data/raw/poi/a3_pois_clean.csv"
DEF_POI_VALWIN = PROJECT_ROOT / "data/raw/poi/a3_valwin_shop.jsonl"
DEF_VAL = PROJECT_ROOT / "data/raw/validation/shanghai_validation_set_v0.csv"
DEF_CONFIG = PROJECT_ROOT / "config/a6_rules.yaml"
DEF_POI_MAP = PROJECT_ROOT / "config/poi_mapping.yaml"

# ---- 输出 ----
OUT_MASTER = PROJECT_ROOT / "outputs/module_a_master.gpkg"
OUT_COVERAGE = PROJECT_ROOT / "data/reference/a6_coverage_stats.csv"
OUT_DIAG = PROJECT_ROOT / "data/reference/a6_validation_diagnostics.csv"
OUT_PROFILE = PROJECT_ROOT / "data/reference/a6_class3_10_profile.csv"
INTERIM = PROJECT_ROOT / "data/interim"

EXPECTED_EPSG = 4326
_T0 = time.time()


def _log(m: str) -> None:
    print(f"[{time.time() - _T0:6.1f}s] {m}", flush=True)


def _rule(t: str) -> None:
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


# --------------------------------------------------------------------------- #
# POI typecode helpers（多码感知）                                              #
# --------------------------------------------------------------------------- #
def _codes(typecode: str) -> list[str]:
    """'|' 分隔多码 → 子码列表(去空)。"""
    if not isinstance(typecode, str):
        return []
    return [c for c in typecode.split("|") if c]


def _any_prefix(typecode: str, prefix: str) -> bool:
    return any(c.startswith(prefix) for c in _codes(typecode))


# --------------------------------------------------------------------------- #
# 1. 底盘                                                                       #
# --------------------------------------------------------------------------- #
def load_chassis(shp26: Path, cfg: dict) -> gpd.GeoDataFrame:
    g = gpd.read_file(shp26, columns=["height", "Area"])   # 尊重 .cpg(UTF-8),不加 encoding
    assert g.crs.to_epsg() == EXPECTED_EPSG, f"2026 CRS!={EXPECTED_EPSG}: {g.crs}"
    g = g.rename(columns={"Area": "area_m2"})
    g["height"] = pd.to_numeric(g["height"], errors="coerce").astype("int64")
    mpf = cfg["storey_inference"]["meters_per_floor"]
    thr = cfg["supertall"]["height_threshold_m"]
    g["idx"] = np.arange(len(g))
    g["is_supertall"] = (g["height"] >= thr).to_numpy()
    floors = np.round(g["height"].to_numpy() / mpf)
    floors[g["is_supertall"].to_numpy()] = np.nan          # supertall 不走 /4
    g["floors"] = pd.array(floors, dtype="Int64")
    g["floors_source"] = np.where(g["is_supertall"], "supertall_pending", f"round_h{mpf:g}")
    _log(f"底盘 2026: {len(g):,} 栋 | supertall(height>={thr}): "
         f"{int(g['is_supertall'].sum())} | floors=round(height/{mpf:g})")
    return g


# --------------------------------------------------------------------------- #
# 2. supertall 处置(与 2023 最大交叠 IoU)                                      #
# --------------------------------------------------------------------------- #
def resolve_supertall(g: gpd.GeoDataFrame, shp23: Path, cfg: dict) -> None:
    epsg = cfg["supertall"]["metric_epsg"]
    iou_min = cfg["supertall"]["iou_min"]
    sup = g[g["is_supertall"]].copy()
    if not len(sup):
        return
    g23 = gpd.read_file(shp23, columns=["FLOOR"]).to_crs(epsg)
    g23["floor23"] = pd.to_numeric(g23["FLOOR"], errors="coerce").astype("int64").to_numpy()
    g23["a23"] = g23.geometry.area
    sup_m = sup[["idx", "geometry"]].to_crs(epsg)
    sup_m["a26"] = sup_m.geometry.area
    j = gpd.sjoin(sup_m, g23[["floor23", "a23", "geometry"]], predicate="intersects", how="inner")
    n_matched = 0
    if len(j):
        inter = shapely.area(shapely.intersection(
            j.geometry.values, g23.geometry.values[j["index_right"].values]))
        d = pd.DataFrame({"idx": j["idx"].to_numpy(), "floor23": j["floor23"].to_numpy(),
                          "a26": j["a26"].to_numpy(), "a23": j["a23"].to_numpy(), "inter": inter})
        d = d.sort_values("inter").drop_duplicates("idx", keep="last")
        d["iou"] = d["inter"] / (d["a26"] + d["a23"] - d["inter"])
        ok = d[d["iou"] >= iou_min]
        floors23 = (ok["floor23"] // 2).astype("int64")
        m = dict(zip(ok["idx"].to_numpy(), floors23.to_numpy(), strict=False))
        for i, fl in m.items():
            g.loc[g["idx"] == i, "floors"] = fl
            g.loc[g["idx"] == i, "floors_source"] = "crosswalk_iou2023"
        n_matched = len(ok)
    # 未配对 supertall → floors NA + crosswalk/cnbh flag
    unmatched = g["is_supertall"] & g["floors"].isna()
    g.loc[unmatched, "floors_source"] = "supertall_unmatched_crosswalk_or_cnbh"
    _log(f"supertall 处置: {int(g['is_supertall'].sum())} 栋 → IoU>={iou_min} 配 2023 "
         f"{n_matched} 栋取 FLOOR//2;未配 {int(unmatched.sum())} 栋 floors=NA+flag")


# --------------------------------------------------------------------------- #
# 3. EULUC 先验                                                                 #
# --------------------------------------------------------------------------- #
def join_euluc(g: gpd.GeoDataFrame, euluc: Path) -> None:
    eu = gpd.read_file(euluc)
    assert eu.crs.to_epsg() == EXPECTED_EPSG, f"EULUC CRS!={EXPECTED_EPSG}: {eu.crs}"
    cent = g[["idx"]].copy()
    cent["geometry"] = g.geometry.representative_point()
    cent = gpd.GeoDataFrame(cent, geometry="geometry", crs=g.crs)
    jj = gpd.sjoin(cent, eu[["Class", "geometry"]], predicate="within", how="left")
    jj = jj[~jj.index.duplicated(keep="first")]
    g["euluc_class"] = pd.array(jj["Class"].to_numpy(), dtype="Int64")
    g["euluc_out"] = g["euluc_class"].isna().to_numpy()
    _log(f"EULUC 先验: 命中 parcel {int((~g['euluc_out']).sum()):,} | "
         f"euluc_out {int(g['euluc_out'].sum()):,}")


# --------------------------------------------------------------------------- #
# 4. POI 播种(mall / hotel 信号)                                              #
# --------------------------------------------------------------------------- #
def load_poi(poi_clean: Path, poi_valwin: Path) -> pd.DataFrame:
    clean = pd.read_csv(poi_clean, dtype={"typecode": str})
    vw = pd.DataFrame([json.loads(x) for x in open(poi_valwin, encoding="utf-8")])
    vw["typecode"] = vw["typecode"].astype(str)
    keep = ["id", "name", "typecode", "wgs_lng", "wgs_lat"]
    merged = (pd.concat([clean[keep], vw[keep]], ignore_index=True)
              .drop_duplicates("id").reset_index(drop=True))
    _log(f"POI 合并: clean {len(clean):,} + valwin {len(vw):,} → 去重 {len(merged):,}")
    return merged


def seed_poi(g: gpd.GeoDataFrame, poi: pd.DataFrame, cfg: dict) -> gpd.GeoDataFrame:
    epsg = cfg["supertall"]["metric_epsg"]
    poi_g = gpd.GeoDataFrame(
        poi, geometry=gpd.points_from_xy(poi.wgs_lng, poi.wgs_lat), crs=4326).to_crs(epsg)
    bld_m = g[["idx", "geometry"]].copy()
    bld_m["geometry"] = g.geometry.representative_point()
    bld_m = gpd.GeoDataFrame(bld_m, geometry="geometry", crs=g.crs).to_crs(epsg)

    def attach(sub: gpd.GeoDataFrame, dist: float) -> set[int]:
        """每个 POI 挂到 dist 内最近建筑;返回被挂中的建筑 idx 集合。"""
        if not len(sub):
            return set()
        nn = gpd.sjoin_nearest(sub[["geometry"]], bld_m[["idx", "geometry"]],
                               max_distance=dist, how="inner")
        return set(nn["idx"].dropna().astype(int).tolist())

    def signal_idx(rules: list[dict]) -> set[int]:
        out: set[int] = set()
        for r in rules:
            pref = r["code_prefix"]
            sub = poi_g[poi_g["typecode"].apply(lambda t, p=pref: _any_prefix(t, p))]
            hit = attach(sub, r["max_dist_m"])
            req = r.get("require_euluc_class")   # A6.1:信号仅在指定 EULUC 类 parcel 内生效
            if req is not None:
                allowed = set(g.loc[g["euluc_class"].isin(req), "idx"].tolist())
                hit &= allowed
            out |= hit
        return out

    mall_idx = signal_idx(cfg["poi_signals"]["mall"])
    hotel_idx = signal_idx(cfg["poi_signals"]["hotel"])

    g["mall_signal"] = g["idx"].isin(mall_idx).to_numpy()
    g["hotel_signal"] = g["idx"].isin(hotel_idx).to_numpy()
    _log(f"POI 播种: mall_signal {int(g['mall_signal'].sum()):,} | "
         f"hotel_signal {int(g['hotel_signal'].sum()):,}")
    return poi_g  # metric POI，供诊断复用


# --------------------------------------------------------------------------- #
# 5+6. mixed_use 候选 + 规则表打标                                              #
# --------------------------------------------------------------------------- #
def label_rules(g: gpd.GeoDataFrame, cfg: dict) -> None:
    muc_cls = cfg["mixed_use_candidate"]["euluc_class"]
    ec = g["euluc_class"].to_numpy(dtype="float64", na_value=np.nan)   # NA→nan,避免 pd.NA 布尔
    is_c1 = (ec == muc_cls)
    g["mixed_use_candidate"] = (is_c1 & g["mall_signal"].to_numpy())

    cutoff = cfg["residential_split"]["floor_count_cutoff"]
    cls_map = {int(k): v for k, v in cfg["euluc_class_to_archetype"].items()}

    arche = np.full(len(g), "unknown", dtype=object)
    lrule = np.full(len(g), "unknown", dtype=object)

    floors = g["floors"]
    mall = g["mall_signal"].to_numpy()
    hotel = g["hotel_signal"].to_numpy()
    muc = g["mixed_use_candidate"].to_numpy()

    # euluc_direct archetype 预解析(residential 先占位,后按层数分)
    euluc_arch = np.full(len(g), None, dtype=object)
    for cls, spec in cls_map.items():
        a = spec.get("archetype")
        if a is None:
            continue
        euluc_arch[ec == cls] = a

    # 优先级 ②→⑤(⑥ 默认 unknown;① supertall 为横切 flag,不改 archetype)
    assigned = np.zeros(len(g), dtype=bool)

    def apply(mask, arch_val, rule_name, dynamic=None):
        take = mask & (~assigned)
        if dynamic is None:
            arche[take] = arch_val
        else:
            arche[take] = dynamic[take]
        lrule[take] = rule_name
        assigned[take] = True

    apply(muc, "mixed_use", "mixed_use_candidate")             # ②
    apply(mall, "shopping_mall", "mall")                        # ③
    apply(hotel, "hotel", "hotel")                              # ④
    # ⑤ euluc_direct:residential 按层数分 mid/high
    fl = floors.to_numpy(dtype="float64", na_value=np.nan)
    resi_hi = np.where(fl >= cutoff, "residential_high_rise", "residential_mid_rise")
    euluc_dyn = euluc_arch.copy()
    is_resi = euluc_arch == "residential"
    euluc_dyn[is_resi] = resi_hi[is_resi]
    euluc_hit = np.array([a is not None for a in euluc_arch])
    apply(euluc_hit, None, "euluc_direct", dynamic=euluc_dyn)   # ⑤

    g["archetype"] = arche
    g["label_rule"] = lrule
    # A6.1:捆绑标签 flag(如 sport_culture;计入 rule-labeled,Module C 前需拆分)
    bundled = {v["archetype"] for v in cls_map.values()
               if v.get("confidence") == "bundled_label" and v.get("archetype")}
    g["bundled_label"] = g["archetype"].isin(bundled).to_numpy()
    _log(f"规则表打标完成(②mixed_use ③mall ④hotel ⑤euluc_direct ⑥unknown);"
         f"bundled 标签 {int(g['bundled_label'].sum()):,} 栋")


# --------------------------------------------------------------------------- #
# 覆盖率四个数 × 双口径                                                          #
# --------------------------------------------------------------------------- #
def coverage(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """覆盖率四个数 ×(全市 / EULUC-scoped)×(栋数 / GFA)双权重。

    GFA = area_m2 × floors;floors=NA(28 栋超高层未配)无 GFA → 权重 0,
    故 GFA 口径的 height-complete 改按 footprint 面积加权(否则恒 100% 无意义),
    note 列注明。
    """
    rows = []
    gfa = (g["area_m2"].to_numpy(dtype="float64")
           * g["floors"].to_numpy(dtype="float64", na_value=np.nan))
    area = g["area_m2"].to_numpy(dtype="float64")
    labeled = (g["archetype"] != "unknown").to_numpy()
    unknown = ~labeled
    has_fl = g["floors"].notna().to_numpy()
    for scope, mask in [("citywide", np.ones(len(g), bool)),
                        ("euluc_scoped", (~g["euluc_out"]).to_numpy())]:
        n = int(mask.sum())
        n_na = int((~has_fl & mask).sum())
        for wname in ("count", "gfa"):
            if wname == "count":
                w = mask.astype(float)
                hc = (has_fl & mask).sum() / n * 100
                note = ""
            else:
                w = np.where(mask, np.nan_to_num(gfa, nan=0.0), 0.0)
                aw = np.where(mask, area, 0.0)
                hc = aw[has_fl & mask].sum() / aw.sum() * 100   # 面积加权,见 docstring
                note = "height_complete=面积加权(floors NA 无 GFA)"
            tot = w.sum()
            rows.append({
                "scope": scope, "weight": wname, "n": n,
                "weight_total": round(tot, 0),
                "pct_rule_labeled": round(w[labeled].sum() / tot * 100, 2),
                "pct_ml_predicted": 0.0,   # 本阶段占位
                "pct_unknown": round(w[unknown].sum() / tot * 100, 2),
                "pct_height_complete": round(hc, 4),
                "n_floors_na": n_na,   # supertall 未配对(floors=NA + 明确 flag)
                "note": note,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 诊断 d:Class 3(工业)/ Class 10(公园)内建筑画像(A6.1 新增)                 #
# --------------------------------------------------------------------------- #
def profile_class3_10(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """层数分布 × footprint 面积分布(分位数),验证村居假说。"""
    _rule("诊断 d — Class 3(工业)/ Class 10(公园)内建筑画像(村居假说)")
    qs = [0.10, 0.25, 0.50, 0.75, 0.90]
    rows = []
    for cls, name in [(3, "industrial"), (10, "park_greenspace")]:
        s = g[g["euluc_class"] == cls]
        fl = s["floors"].dropna().to_numpy(dtype="float64")
        ar = s["area_m2"].to_numpy(dtype="float64")
        row = {"euluc_class": cls, "name": name, "n": len(s),
               "pct_floors_le3": round(float((fl <= 3).mean()) * 100, 1)}
        for q, v in zip(qs, np.quantile(fl, qs), strict=True):
            row[f"floors_p{int(q*100)}"] = round(float(v), 1)
        for q, v in zip(qs, np.quantile(ar, qs), strict=True):
            row[f"area_p{int(q*100)}_m2"] = round(float(v), 1)
        rows.append(row)
        print(f"Class {cls} ({name}): n={len(s):,} | floors P10-P90 "
              f"{row['floors_p10']:g}-{row['floors_p90']:g}(中位 {row['floors_p50']:g},"
              f"≤3 层 {row['pct_floors_le3']}%)| area P10-P90 "
              f"{row['area_p10_m2']:g}-{row['area_p90_m2']:g} m²(中位 {row['area_p50_m2']:g})")
    print("判读:低层(≤3)占比高 + 小 footprint → 村居/附属小建筑画像;"
          "大 footprint + 低层 → 厂房/仓储画像。数字如上,定性留 owner。")
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 诊断 a:validation 分 archetype accuracy                                       #
# 诊断 b:10 层线 ±2 扰动翻转率                                                   #
# 诊断 c(计票):方案 A vs C 命中差异                                            #
# --------------------------------------------------------------------------- #
def build_code_mapper(poi_map_path: Path):
    """poi_mapping.yaml → map_code(code)->archetype|None(None=skip/无票)。"""
    m = yaml.safe_load(open(poi_map_path, encoding="utf-8"))
    sub = {}
    for k, v in (m.get("sub_category_overrides") or {}).items():
        if isinstance(v, dict) and v.get("archetype"):
            sub[str(k)] = v["archetype"]
    mid = {}
    for k, v in (m.get("mid_category_overrides") or {}).items():
        if isinstance(v, dict):
            mid[str(k)] = None if v.get("rule") == "skip" else v.get("archetype")
    big = {}
    for k, v in (m.get("big_category_rules") or {}).items():
        if not isinstance(v, dict):
            continue
        r = v.get("rule")
        if r == "skip":
            big[str(k)] = None
        elif r == "archetype":
            big[str(k)] = v.get("archetype")
        elif r == "requires_mid_override":
            d = v.get("default")
            big[str(k)] = None if d == "skip" else d

    def map_code(code: str):
        code = str(code)
        if code in sub:
            return sub[code]
        mk = code[:4] + "00"
        if mk in mid:
            return mid[mk]
        bk = code[:2] + "0000"
        if bk in big:
            return big[bk]
        return None
    return map_code


def poi_votes(poi_g: gpd.GeoDataFrame, bld_m: gpd.GeoDataFrame, map_code,
              max_dist: float) -> pd.DataFrame:
    """每 POI 挂最近建筑(<=max_dist),按方案 A/C 累计 archetype 票 → 每建筑 argmax_A/C。"""
    nn = gpd.sjoin_nearest(poi_g[["typecode", "geometry"]], bld_m[["idx", "geometry"]],
                           max_distance=max_dist, how="inner")
    recs_a, recs_c = {}, {}
    for tc, bidx in zip(nn["typecode"].to_numpy(), nn["idx"].to_numpy(), strict=False):
        cs = _codes(tc)
        if not cs:
            continue
        n = len(cs)
        for c in cs:
            a = map_code(c)
            if a is None:
                continue
            recs_a.setdefault(int(bidx), {}).setdefault(a, 0.0)
            recs_a[int(bidx)][a] += 1.0
            recs_c.setdefault(int(bidx), {}).setdefault(a, 0.0)
            recs_c[int(bidx)][a] += 1.0 / n

    def argmax(d):
        return max(d.items(), key=lambda kv: kv[1])[0] if d else None
    idxs = sorted(set(recs_a) | set(recs_c))
    return pd.DataFrame({
        "idx": idxs,
        "poi_arch_A": [argmax(recs_a.get(i, {})) for i in idxs],
        "poi_arch_C": [argmax(recs_c.get(i, {})) for i in idxs],
    })


def diagnostics(g: gpd.GeoDataFrame, poi_g: gpd.GeoDataFrame, poi: pd.DataFrame,
                val_path: Path, cfg: dict, poi_map_path: Path) -> pd.DataFrame:
    epsg = cfg["supertall"]["metric_epsg"]
    cutoff = cfg["residential_split"]["floor_count_cutoff"]

    def coarse(a):
        return "residential" if isinstance(a, str) and a.startswith("residential") else a

    # ---- match validation → master building(重命名避免 archetype 列冲突)----
    val = pd.read_csv(val_path)
    val = val[val.status == "annotated"].rename(columns={"archetype": "truth_arch"}).copy()
    pts = gpd.GeoDataFrame(val, geometry=gpd.points_from_xy(val.lon, val.lat), crs=4326)
    gm = g[["idx", "archetype", "label_rule", "floors", "euluc_class", "geometry"]].rename(
        columns={"archetype": "pred_arch", "label_rule": "pred_rule", "floors": "pred_floors"})
    w = gpd.sjoin(pts, gm, predicate="within", how="left")
    w = w[~w.index.duplicated(keep="first")]
    miss = w.index[w["idx"].isna()]
    if len(miss):
        nn = gpd.sjoin_nearest(pts.loc[miss].to_crs(epsg), gm.to_crs(epsg),
                               max_distance=10, how="left")
        nn = nn[~nn.index.duplicated(keep="first")]
        for c in ["idx", "pred_arch", "pred_rule", "pred_floors", "euluc_class"]:
            w.loc[miss, c] = nn[c]
    val["idx"] = w["idx"].to_numpy()
    val["pred_arch"] = w["pred_arch"].to_numpy()
    val["pred_floors"] = pd.to_numeric(w["pred_floors"], errors="coerce").to_numpy()
    val["euluc_class"] = pd.to_numeric(w["euluc_class"], errors="coerce").to_numpy()
    val["pred_coarse"] = val["pred_arch"].map(coarse)
    matched = val[val.pred_arch.notna()].copy()

    _rule("诊断 a — validation 规则打标 accuracy(分 archetype,真值 vs 预测粗类对齐)")
    print(f"annotated={len(val)} | 命中 master 建筑={len(matched)}")
    # A6.1:捆绑标签命中口径 —— pred=sport_culture 对 truth∈bundle_of(sports/culture)算命中
    bundle_map = {v["archetype"]: set(v.get("bundle_of") or [])
                  for v in cfg["euluc_class_to_archetype"].values()
                  if v.get("confidence") == "bundled_label" and v.get("archetype")}

    def is_hit(pred, truth):
        return pred == truth or truth in bundle_map.get(pred, ())

    hits = np.array([is_hit(p, t) for p, t in
                     zip(matched["pred_coarse"], matched["truth_arch"], strict=True)])
    rows = []
    for tv in sorted(matched["truth_arch"].dropna().unique()):
        m = (matched["truth_arch"] == tv).to_numpy()
        hit = int(hits[m].sum())
        rows.append({"archetype_truth": tv, "n": int(m.sum()), "rule_hit": hit,
                     "accuracy_pct": round(hit / m.sum() * 100, 1)})
    acc_df = pd.DataFrame(rows).sort_values("n", ascending=False)
    overall = hits.mean() * 100
    print(acc_df.to_string(index=False))
    print(f"整体 accuracy(粗类对齐,含捆绑命中): {overall:.1f}%  (n={len(matched)})")

    # 参照:EULUC-direct-only(忽略 POI mall/hotel/mixed 覆盖)以量化 POI 覆盖的代价
    cls_map = {int(k): v.get("archetype")
               for k, v in cfg["euluc_class_to_archetype"].items()}
    inpar = matched[matched["euluc_class"].notna()].copy()
    eu_pred = inpar["euluc_class"].astype(int).map(cls_map).map(coarse)
    eu_hits = [is_hit(p, t) for p, t in
               zip(eu_pred, inpar["truth_arch"], strict=True)]
    eu_acc = float(np.mean(eu_hits)) * 100
    # 同基准对照(A6.1):全规则 accuracy 限 in-parcel 同一分母,才与 EULUC-only 可比;
    # 全 156 分母含 20 栋 euluc_out(临港/张江 EULUC 时间盲区),规则层面结构性不可标。
    inpar_mask = matched["euluc_class"].notna().to_numpy()
    full_inpar = float(hits[inpar_mask].mean()) * 100
    print(f"参照 EULUC-direct-only accuracy(in-parcel n={len(inpar)},同捆绑口径): {eu_acc:.1f}%")
    print(f"同基准全规则 accuracy(in-parcel 同分母): {full_inpar:.1f}% "
          f"→ POI 覆盖净效应 {full_inpar-eu_acc:+.1f}pp(A6.1 hotel 门槛修订后)")
    n_out = int((~inpar_mask).sum())
    print(f"全分母 {overall:.1f}% 与 in-parcel 差值主因:{n_out} 栋 euluc_out"
          f"(EULUC 2022 时间盲区,规则层面全 miss)")

    # ---- 诊断 b:10 层线 ±2 扰动翻转率 ----
    _rule("诊断 b — 10 层线 ±2 扰动 residential mid/high 翻转率")
    resi = matched[matched["pred_arch"].astype(str).str.startswith("residential")
                   & matched["pred_floors"].notna()].copy()
    f = resi["pred_floors"].to_numpy()
    base = np.where(f >= cutoff, "high", "mid")
    lo = np.where((f - 2) >= cutoff, "high", "mid")
    hi = np.where((f + 2) >= cutoff, "high", "mid")
    flip = (lo != base) | (hi != base)
    fr = flip.mean() * 100 if len(resi) else float("nan")
    print(f"residential 预测样本 n={len(resi)} | ±2 层扰动翻转 {int(flip.sum())} 栋 → 翻转率 {fr:.1f}%")
    print(f"  (翻转 = ±2 层窗口跨越 floors={cutoff} 分界;floors 由 round(height/4) 合成,故临界带敏感)")

    # ---- 诊断 c:计票方案 A vs C ----
    _rule("诊断 c — 多 typecode 计票 方案 A vs C(计票悬案实证)")
    n_multi = poi["typecode"].apply(lambda t: len(_codes(t)) > 1).sum()
    dist = poi["typecode"].apply(lambda t: len(_codes(t))).value_counts().sort_index()
    print(f"POI 多码占比: {n_multi}/{len(poi)} ({n_multi/len(poi)*100:.2f}%);"
          f"码数分布: {dist.to_dict()}")
    map_code = build_code_mapper(poi_map_path)
    bld_m = g[["idx", "geometry"]].copy()
    bld_m["geometry"] = g.geometry.representative_point()
    bld_m = gpd.GeoDataFrame(bld_m, geometry="geometry", crs=g.crs).to_crs(epsg)
    max_d = max(r["max_dist_m"] for r in cfg["poi_signals"]["mall"] + cfg["poi_signals"]["hotel"])
    votes = poi_votes(poi_g, bld_m, map_code, max_d)
    n_flip_city = (votes["poi_arch_A"] != votes["poi_arch_C"]).sum()
    print(f"有 POI 票的建筑 {len(votes):,};A vs C argmax 翻转 {n_flip_city:,} 栋 "
          f"({n_flip_city/len(votes)*100:.2f}%)")
    # validation 上 A/C accuracy
    vm = matched.merge(votes, left_on="idx", right_on="idx", how="left")
    vv = vm[vm["poi_arch_A"].notna()].copy()
    if len(vv):
        vv["arch_A_coarse"] = vv["poi_arch_A"].map(coarse)
        vv["arch_C_coarse"] = vv["poi_arch_C"].map(coarse)
        accA = (vv["arch_A_coarse"] == vv["truth_arch"]).mean() * 100
        accC = (vv["arch_C_coarse"] == vv["truth_arch"]).mean() * 100
        nfv = (vv["poi_arch_A"] != vv["poi_arch_C"]).sum()
        print(f"validation 有 POI 票 n={len(vv)}: 方案A accuracy {accA:.1f}% | "
              f"方案C accuracy {accC:.1f}% | A/C argmax 翻转 {nfv} 栋")
        concl = ("A/C 在 validation 命中无差异,计票方案不影响本阶段结论"
                 if abs(accA - accC) < 1e-9 else
                 f"A/C 命中差 {accC-accA:+.1f}pp(C 保守分票)")
    else:
        accA = accC = nfv = float("nan")
        concl = "validation 无 POI 票样本,无法量化 A/C 差异"
    print(f"结论:{concl}")

    diag = pd.concat([
        acc_df.assign(metric="rule_accuracy_by_archetype"),
        pd.DataFrame([{"metric": "overall_rule_accuracy", "accuracy_pct": round(overall, 1),
                       "n": len(matched)},
                      {"metric": "euluc_direct_only_accuracy", "accuracy_pct": round(eu_acc, 1),
                       "n": len(inpar)},
                      {"metric": "full_rule_accuracy_in_parcel", "accuracy_pct": round(full_inpar, 1),
                       "n": len(inpar)},
                      {"metric": "residential_10floor_flip_rate", "accuracy_pct": round(fr, 1),
                       "n": len(resi)},
                      {"metric": "poi_multicode_pct",
                       "accuracy_pct": round(n_multi / len(poi) * 100, 2), "n": len(poi)},
                      {"metric": "poi_vote_A_vs_C_flip_citywide", "n": int(n_flip_city)},
                      {"metric": "poi_vote_A_accuracy_validation",
                       "accuracy_pct": round(accA, 1) if accA == accA else None, "n": len(vv) if len(vv) else 0},
                      {"metric": "poi_vote_C_accuracy_validation",
                       "accuracy_pct": round(accC, 1) if accC == accC else None, "n": len(vv) if len(vv) else 0}]),
    ], ignore_index=True)
    return diag


# --------------------------------------------------------------------------- #
# main                                                                          #
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--shp26", type=Path, default=DEF_SHP26)
    p.add_argument("--shp23", type=Path, default=DEF_SHP23)
    p.add_argument("--euluc", type=Path, default=DEF_EULUC)
    p.add_argument("--poi-clean", type=Path, default=DEF_POI_CLEAN)
    p.add_argument("--poi-valwin", type=Path, default=DEF_POI_VALWIN)
    p.add_argument("--val", type=Path, default=DEF_VAL)
    p.add_argument("--config", type=Path, default=DEF_CONFIG)
    p.add_argument("--poi-map", type=Path, default=DEF_POI_MAP)
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))

    g = load_chassis(args.shp26, cfg)              # 1
    resolve_supertall(g, args.shp23, cfg)          # 2
    join_euluc(g, args.euluc)                      # 3
    poi = load_poi(args.poi_clean, args.poi_valwin)
    poi_g = seed_poi(g, poi, cfg)                  # 4
    label_rules(g, cfg)                            # 5+6

    _rule("覆盖率四个数 ×(全市 / EULUC-scoped)双口径")
    cov = coverage(g)
    print(cov.to_string(index=False))
    _rule("archetype 分布 + label_rule 分布")
    print(g["archetype"].value_counts().to_string())
    print("\nlabel_rule:")
    print(g["label_rule"].value_counts().to_string())

    diag = diagnostics(g, poi_g, poi, args.val, cfg, args.poi_map)  # 7 诊断 a/b/c
    prof = profile_class3_10(g)                                     # 诊断 d(A6.1)

    if not args.no_write:
        OUT_MASTER.parent.mkdir(parents=True, exist_ok=True)
        INTERIM.mkdir(parents=True, exist_ok=True)
        out = g.drop(columns=["idx"]).copy()
        out.to_file(OUT_MASTER, driver="GPKG", layer="module_a_master")
        cov.to_csv(OUT_COVERAGE, index=False)
        diag.to_csv(OUT_DIAG, index=False)
        prof.to_csv(OUT_PROFILE, index=False)
        _log(f"写出 master: {OUT_MASTER.relative_to(PROJECT_ROOT)} "
             f"({OUT_MASTER.stat().st_size/1e6:.1f} MB)")
        _log(f"写出 {OUT_COVERAGE.relative_to(PROJECT_ROOT)} + {OUT_DIAG.relative_to(PROJECT_ROOT)}"
             f" + {OUT_PROFILE.relative_to(PROJECT_ROOT)}")
    else:
        _log("--no-write:未落盘")

    _rule("A6 Stage 1 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
