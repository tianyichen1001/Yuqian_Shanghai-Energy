#!/usr/bin/env python3
"""A6 Stage 1 — 规则打标(rule-based archetype seeding)→ master + 覆盖率四个数。

七步(全部由 config/a6_rules.yaml 驱动,源码不写魔数):
    1. 底盘:读 2026 全市 843,062 栋(尊重 .cpg,勿硬加 encoding),CRS WGS84;
       floors = round(height/4);height>=160 m 打 supertall flag(该段不走 /4)。
    2. supertall 处置:与 2023 集最大交叠 IoU>=0.3(复用 A5 方法)取 FLOOR//2 作层数;
       无配对者 floors=NA + flag=crosswalk_or_cnbh(不硬算)。
    3. EULUC 先验:建筑质心落入 parcel 取 Class;落不进标 euluc_out(EULUC-scoped 依据)。
    4. POI 播种:A3a POI(clean + valwin,用 WGS84 列)按距离挂最近建筑 ——
       mall 信号 (0601<=150 m) OR (06<=100 m);hotel 信号 (1001|1002<=150 m)。
       多 typecode 方案 C(1/N 分票);诊断输出多码占比+码数分布 + 方案 A vs C 在
       validation 上的命中差异(计票悬案实证材料)。
    5. mixed_use 候选:EULUC Class 1 + 060000 命中 → mixed_use_candidate。
    6. 规则表打标(优先级 config.priority,首个命中为准):
       ① supertall(横切 flag)② mixed_use 候选 ③ mall ④ hotel
       ⑤ EULUC 直接命中类→archetype(residential 按 10 层切 mid/high)⑥ unknown。
    7. 组装:master→GPKG;覆盖率四个数 ×(全市 / EULUC-scoped)双口径;
       诊断 a validation 分 archetype accuracy;诊断 b 10 层线 ±2 扰动翻转率。

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
            out |= attach(sub, r["max_dist_m"])
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
    _log("规则表打标完成(②mixed_use ③mall ④hotel ⑤euluc_direct ⑥unknown)")


# --------------------------------------------------------------------------- #
# 覆盖率四个数 × 双口径                                                          #
# --------------------------------------------------------------------------- #
def coverage(g: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for scope, mask in [("citywide", np.ones(len(g), bool)),
                        ("euluc_scoped", (~g["euluc_out"]).to_numpy())]:
        s = g[mask]
        n = len(s)
        labeled = (s["archetype"] != "unknown").sum()
        n_na = int(s["floors"].isna().sum())
        rows.append({
            "scope": scope, "n": n,
            "pct_rule_labeled": round(labeled / n * 100, 2),
            "pct_ml_predicted": 0.0,   # 本阶段占位
            "pct_unknown": round((s["archetype"] == "unknown").sum() / n * 100, 2),
            "pct_height_complete": round(s["floors"].notna().sum() / n * 100, 4),
            "n_floors_na": n_na,   # supertall 未配对(floors=NA + 明确 flag)
        })
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
    rows = []
    for tv in sorted(matched["truth_arch"].dropna().unique()):
        sub = matched[matched["truth_arch"] == tv]
        hit = int((sub["pred_coarse"] == tv).sum())
        rows.append({"archetype_truth": tv, "n": len(sub), "rule_hit": hit,
                     "accuracy_pct": round(hit / len(sub) * 100, 1)})
    acc_df = pd.DataFrame(rows).sort_values("n", ascending=False)
    overall = (matched["pred_coarse"] == matched["truth_arch"]).mean() * 100
    print(acc_df.to_string(index=False))
    print(f"整体 accuracy(粗类对齐): {overall:.1f}%  (n={len(matched)})")

    # 参照:EULUC-direct-only(忽略 POI mall/hotel/mixed 覆盖)以量化 POI 覆盖的代价
    cls_map = {int(k): (v.get("archetype") if v.get("archetype") != "residential" else "residential")
               for k, v in cfg["euluc_class_to_archetype"].items()}
    inpar = matched[matched["euluc_class"].notna()].copy()
    eu_pred = inpar["euluc_class"].astype(int).map(cls_map)
    eu_acc = (eu_pred.map(coarse) == inpar["truth_arch"]).mean() * 100
    print(f"参照 EULUC-direct-only accuracy(仅在 parcel 内 n={len(inpar)}): {eu_acc:.1f}%")
    print(f"  → POI mall/hotel 覆盖(优先级 ③④>⑤)使命中 {eu_acc:.1f}%→{overall:.1f}%;"
          "主因 hotel 100200(公寓式酒店)在住宅楼过度挂靠,详见 PR 判决书")

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

    diag = diagnostics(g, poi_g, poi, args.val, cfg, args.poi_map)  # 7 诊断

    if not args.no_write:
        OUT_MASTER.parent.mkdir(parents=True, exist_ok=True)
        INTERIM.mkdir(parents=True, exist_ok=True)
        out = g.drop(columns=["idx"]).copy()
        out.to_file(OUT_MASTER, driver="GPKG", layer="module_a_master")
        cov.to_csv(OUT_COVERAGE, index=False)
        diag.to_csv(OUT_DIAG, index=False)
        _log(f"写出 master: {OUT_MASTER.relative_to(PROJECT_ROOT)} "
             f"({OUT_MASTER.stat().st_size/1e6:.1f} MB)")
        _log(f"写出 {OUT_COVERAGE.relative_to(PROJECT_ROOT)} + {OUT_DIAG.relative_to(PROJECT_ROOT)}")
    else:
        _log("--no-write:未落盘")

    _rule("A6 Stage 1 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
