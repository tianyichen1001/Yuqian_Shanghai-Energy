"""B3 正式训练 — Module B ML archetype 推断(三模型对比 + 超参数调优 + 全量预测)

工作令 2026-08-04:
  训练集三层来源:
    第一层(金标准) = validation 156 annotated + b2 actual_class(若填) + smallclass xlsx(若存在)
    第二层(EULUC)  = residential_mid/high + education, label_rule==euluc_direct, 降采样
    第三层(规则)   = hotel 全量 + sport_culture bundled(作 sports)全量
    禁用: mall(1110) / mixed_use(319) 规则弱标签 / culture OSM
  三模型: RF / XGBoost / CatBoost
  CV: GroupKFold K=5(0.01° 空间网格), SMOTE 在每个 fold 内部
  Steps: 0(数据) → 1(特征) → 2(三模型对比,报告后停止) → 3(调优,需 --best-model) → 4(全量预测,需 --predict)

Usage:
  python scripts/b3_formal_training.py --data-dir ~/b3_data [--step 0-4]
    [--best-model rf|xgb|cat]
    [--predict]
    [--residential-n 7500]

Input (in --data-dir):
  module_a_master.gpkg           (从私仓 zip 解压)
  euluc_shanghai_2022.gpkg       (从私仓 zip 解压)
  2026 Building/2026 Building.shp

Output:
  data/reference/b3_*.csv                    (commit)
  outputs/figures/module_b/b3_*.png          (commit)
  <out-dir>/b3_predictions.parquet           (不 commit)
  <out-dir>/b3_best_model.joblib             (不 commit)
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path
from itertools import product as iterproduct

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import pyogrio
import shapely
import yaml
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, log_loss, confusion_matrix,
    classification_report,
)
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier
from catboost import CatBoostClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.ml import features as F           # noqa: E402
from buildings_shanghai.ml.train_utils import (          # noqa: E402
    make_spatial_groups, resample_training_fold, cross_val_evaluate,
    cross_val_evaluate_catboost, get_feature_importance,
    plot_feature_importance_comparison, plot_confusion_matrix,
    plot_probability_gmm, bootstrap_ci,
)

CFG_PATH = PROJECT_ROOT / "config" / "b3_formal_training.yaml"
REF_DIR = PROJECT_ROOT / "data" / "reference"
FIG_DIR = PROJECT_ROOT / "outputs" / "figures" / "module_b"


def _log(msg: str) -> None:
    print(f"[b3] {msg}", flush=True)


def load_config() -> dict:
    with open(CFG_PATH) as f:
        return yaml.safe_load(f)


# =========================================================================== #
# Step 0: 数据准备                                                             #
# =========================================================================== #

def standardise_label(raw: str, floors: float | None, cfg: dict) -> str | None:
    """统一标签格式。返回 None 表示跳过此行。"""
    if pd.isna(raw):
        return None
    raw_str = str(raw).strip().lower()
    label_map = {k.lower(): v for k, v in cfg["truth"]["label_map"].items()}
    if raw_str in label_map:
        mapped = label_map[raw_str]
        if mapped is None:
            # residential → split by floors
            cutoff = cfg["truth"]["floor_cutoff"]
            try:
                f = float(floors)
                return "residential_high_rise" if f >= cutoff else "residential_mid_rise"
            except (TypeError, ValueError):
                return "residential_mid_rise"  # default if floors unknown
        return mapped
    # Pass through if already canonical
    canonical = {
        "government_office", "office", "hotel", "shopping_mall", "healthcare",
        "education", "sports", "culture", "transportation", "exhibition",
        "mixed_use", "other_public", "residential_high_rise", "residential_mid_rise",
        "unclear",
    }
    norm = raw_str.replace(" ", "_").replace("-", "_")
    if norm in canonical:
        return norm
    _log(f"  ⚠ 未知标签 '{raw_str}' → 跳过")
    return None


def load_ground_truth(cfg: dict) -> pd.DataFrame:
    """加载并合并所有人工真值来源,返回含 [lat, lon, archetype, source, floors] 的 DataFrame。"""
    records = []
    missing_files = []

    # --- 1) v0.csv (156 annotated) ---
    v0_path = PROJECT_ROOT / cfg["truth"]["v0_csv"]
    if v0_path.exists():
        v0 = pd.read_csv(v0_path)
        v0 = v0[v0["status"] == "annotated"].copy()
        for _, row in v0.iterrows():
            label = standardise_label(row["archetype"], row.get("floors_observed"), cfg)
            if label:
                records.append({
                    "val_id": row.get("val_id", ""),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "master_idx": None,    # set by spatial matching
                    "archetype": label,
                    "floors_observed": row.get("floors_observed"),
                    "source": "v0",
                })
        _log(f"v0.csv: {len(records)} annotated buildings loaded")
    else:
        missing_files.append(str(v0_path))
        _log(f"  ⛔ 缺失: {v0_path}")

    n_v0 = len(records)

    # --- 2) B2 xlsx (119栋人工标注, 优先于 b2_csv) ---
    b2_xlsx_path = PROJECT_ROOT / cfg["truth"].get("b2_xlsx", "")
    b2_csv_path = PROJECT_ROOT / cfg["truth"].get("b2_csv", "")
    n_b2_loaded = 0

    if b2_xlsx_path and b2_xlsx_path.exists():
        b2 = pd.read_excel(b2_xlsx_path, sheet_name="B2标注119栋")
        arch_col_b2 = "建筑类型(填英文)"
        fl_col_b2 = "你看到几层"
        for _, row in b2.iterrows():
            raw_arch = row.get(arch_col_b2)
            if pd.isna(raw_arch):
                continue
            raw_arch_str = str(raw_arch).strip()
            if raw_arch_str in ("unclear", "shopping_mall+residential"):
                continue
            fl_raw = row.get(fl_col_b2)
            try:
                floors_val = float(fl_raw) if fl_raw not in (None, "unclear") and pd.notna(fl_raw) else None
            except (TypeError, ValueError):
                floors_val = None
            label = standardise_label(raw_arch_str, floors_val, cfg)
            if label:
                master_idx = int(row["bid"]) - 1   # bid is 1-based
                records.append({
                    "val_id": f"B2_{int(row['bid'])}",
                    "lat": np.nan, "lon": np.nan,
                    "master_idx": master_idx,       # pre-set; skip spatial matching
                    "archetype": label,
                    "floors_observed": floors_val,
                    "source": "b2",
                })
                n_b2_loaded += 1
        _log(f"  B2 xlsx (119栋): {n_b2_loaded} 栋有效标注")

    elif b2_csv_path and b2_csv_path.exists():
        with open(b2_csv_path) as fh:
            raw_lines = [l for l in fh.readlines()
                         if not l.lstrip("﻿").startswith("#")]
        b2 = pd.read_csv(pd.io.common.StringIO("".join(raw_lines)))
        b2_filled = b2[b2["actual_class"].notna()].copy()
        for _, row in b2_filled.iterrows():
            label = standardise_label(row["actual_class"], row.get("actual_floors"), cfg)
            if label:
                records.append({
                    "val_id": f"B2_{row['bid']}",
                    "lat": float(row["lat_wgs84"]), "lon": float(row["lon_wgs84"]),
                    "master_idx": None,
                    "archetype": label,
                    "floors_observed": row.get("actual_floors"),
                    "source": "b2",
                })
                n_b2_loaded += 1
        if n_b2_loaded == 0:
            _log("  ⚠ b2_annotation_list_v0.csv: actual_class 全部为空 — B2 补标尚未填写!")
            missing_files.append("b2_annotations_unfilled")
        else:
            _log(f"  b2 csv 补标: {n_b2_loaded} 栋有效")
    else:
        missing_files.append("b2_annotation_file_missing")
        _log("  ⚠ B2 标注文件不存在")

    # --- 3) smallclass_verification_20260803.xlsx (若存在) ---
    sc_path = PROJECT_ROOT / cfg["truth"]["smallclass_xlsx"]
    n_sc_loaded = 0
    if sc_path.exists():
        sc = pd.read_excel(sc_path)
        lat_col = next((c for c in sc.columns if c.lower() == "lat"), None)
        lon_col = next((c for c in sc.columns if c.lower() == "lon"), None)
        arch_col = next((c for c in sc.columns
                         if "archetype" in c.lower() and "your" in c.lower()), None)
        fl_col = next((c for c in sc.columns if "floor" in c.lower() and "your" in c.lower()), None)
        midx_col = next((c for c in sc.columns if c.lower() == "master_idx"), None)
        if arch_col:
            for _, row in sc.iterrows():
                raw_arch = row.get(arch_col)
                if pd.isna(raw_arch):
                    continue
                raw_arch_str = str(raw_arch).strip()
                if raw_arch_str in ("unclear",):
                    continue
                fl_raw = row.get(fl_col) if fl_col else None
                try:
                    floors_val = float(fl_raw) if fl_raw not in (None, "unclear") and pd.notna(fl_raw) else None
                except (TypeError, ValueError):
                    floors_val = None
                label = standardise_label(raw_arch_str, floors_val, cfg)
                if label:
                    midx = int(row[midx_col]) if midx_col and pd.notna(row.get(midx_col)) else None
                    rec = {
                        "val_id": f"SC_{int(row['seq']) if 'seq' in sc.columns else n_sc_loaded}",
                        "lat": float(row[lat_col]) if lat_col else np.nan,
                        "lon": float(row[lon_col]) if lon_col else np.nan,
                        "master_idx": midx,     # pre-set from xlsx
                        "archetype": label,
                        "floors_observed": floors_val,
                        "source": "smallclass",
                    }
                    records.append(rec)
                    n_sc_loaded += 1
            _log(f"  smallclass xlsx: {n_sc_loaded} 栋有效")
        else:
            _log(f"  ⚠ smallclass xlsx: 无法识别列名 (cols={sc.columns.tolist()[:8]})")
    else:
        missing_files.append(str(sc_path))
        _log("  ⚠ smallclass_verification_20260803.xlsx 不存在 — 新小类别验证缺失!")

    _log(f"  合计真值: {len(records)} 栋 (v0={n_v0}, b2={n_b2_loaded}, smallclass={n_sc_loaded})")
    if missing_files:
        _log("  ⚠ 缺失来源:")
        for f in missing_files:
            _log(f"    - {f}")
        _log("")

    df = pd.DataFrame(records)
    return df


def split_train_test(gt: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按类别分层抽 30% 作测试集; 63 栋 smallclass 全部进测试集。"""
    seed = cfg["seed"]
    test_frac = cfg["truth"]["test_fraction"]
    exclude_ids = cfg["truth"]["exclude_val_ids"]

    rng = np.random.default_rng(seed)
    test_rows, train_rows = [], []

    # smallclass → all to test
    sc_mask = gt["source"] == "smallclass"
    test_rows.append(gt[sc_mask])
    remaining = gt[~sc_mask].copy()

    # stratified split by archetype
    for arch, grp in remaining.groupby("archetype"):
        n_test = max(1, int(np.round(len(grp) * test_frac)))
        if len(grp) == 1:
            train_rows.append(grp)
            continue
        perm = rng.permutation(len(grp))
        test_rows.append(grp.iloc[perm[:n_test]])
        train_rows.append(grp.iloc[perm[n_test:]])

    test_df = pd.concat(test_rows, ignore_index=True) if test_rows else pd.DataFrame()
    train_df = pd.concat(train_rows, ignore_index=True) if train_rows else pd.DataFrame()

    # Remove from TRAINING SET (not test) buildings flagged for reassessment
    if len(train_df):
        train_df = train_df[~train_df["val_id"].isin(exclude_ids)].copy()

    _log(f"训练集(金标准层): {len(train_df)} 栋 | 测试集: {len(test_df)} 栋")
    return train_df, test_df


def match_to_master(gt: pd.DataFrame, master: gpd.GeoDataFrame,
                    match_max_dist_m: float, metric_epsg: int) -> pd.DataFrame:
    """将真值坐标匹配到 master.gpkg 行，返回 gt + master_idx 列。
    Records with master_idx already set (B2/smallclass direct match) skip the spatial join.
    """
    if len(gt) == 0:
        return gt.assign(master_idx=pd.array([], dtype="Int64"))

    gt = gt.copy()
    if "master_idx" not in gt.columns:
        gt["master_idx"] = pd.NA

    # Rows needing spatial matching (master_idx not yet set)
    need_mask = gt["master_idx"].isna()
    n_pre = int((~need_mask).sum())
    need_match = gt[need_mask].copy()

    if len(need_match) > 0:
        pts = gpd.GeoDataFrame(
            need_match,
            geometry=gpd.points_from_xy(need_match["lon"], need_match["lat"]),
            crs=4326,
        )
        gm_geom = gpd.GeoDataFrame({"midx": np.arange(len(master))},
                                    geometry=master.geometry, crs=master.crs)

        joined = gpd.sjoin(pts, gm_geom, predicate="within", how="left")
        joined = joined[~joined.index.duplicated(keep="first")]
        miss = joined.index[joined["midx"].isna()]

        if len(miss):
            nn = gpd.sjoin_nearest(
                pts.loc[miss].to_crs(metric_epsg),
                gm_geom.to_crs(metric_epsg),
                max_distance=match_max_dist_m, how="left",
            )
            nn = nn[~nn.index.duplicated(keep="first")]
            joined.loc[miss, "midx"] = nn["midx"]

        for idx, midx_val in joined["midx"].items():
            if idx in gt.index and not pd.isna(midx_val):
                gt.loc[idx, "master_idx"] = midx_val

    n_matched = gt["master_idx"].notna().sum()
    _log(f"  master 匹配: {n_matched}/{len(gt)} 栋 ({n_pre} 直接, {n_matched - n_pre} 空间匹配)")
    return gt


def build_tier2_tier3(master_attr: pd.DataFrame, cfg: dict,
                       seed: int) -> pd.DataFrame:
    """构建 Tier 2 (EULUC) + Tier 3 (规则) 训练标签,返回 [master_idx, archetype, tier]。"""
    rng = np.random.default_rng(seed)
    rows = []

    # ── Tier 2: EULUC high-confidence ──────────────────────────────────────
    t2 = cfg["tier2"]
    res_mask = (
        master_attr["archetype"].isin(["residential_mid_rise", "residential_high_rise"])
        & (master_attr["label_rule"] == "euluc_direct")
    )
    edu_mask = (
        (master_attr["archetype"] == "education")
        & (master_attr["label_rule"] == "euluc_direct")
    )

    # residential downsample
    res_all = master_attr[res_mask].copy()
    n_res = t2["residential_downsample_n"]
    n_mid = int(n_res * t2["residential_mid_fraction"])
    n_high = n_res - n_mid

    mid_pool = res_all[res_all["archetype"] == "residential_mid_rise"]
    high_pool = res_all[res_all["archetype"] == "residential_high_rise"]
    mid_sel = mid_pool.sample(min(n_mid, len(mid_pool)), random_state=seed)
    high_sel = high_pool.sample(min(n_high, len(high_pool)), random_state=seed)

    for df, arch in [(mid_sel, "residential_mid_rise"), (high_sel, "residential_high_rise")]:
        for midx, a in zip(df.index, df["archetype"]):
            rows.append({"master_idx": int(midx), "archetype": a, "tier": 2})
    _log(f"  Tier 2 residential: mid_rise {len(mid_sel):,} + high_rise {len(high_sel):,}")

    # education downsample
    edu_all = master_attr[edu_mask]
    edu_n = t2["education_downsample_n"]
    edu_sel = edu_all.sample(min(edu_n, len(edu_all)), random_state=seed)
    for midx in edu_sel.index:
        rows.append({"master_idx": int(midx), "archetype": "education", "tier": 2})
    _log(f"  Tier 2 education: {len(edu_sel):,}")

    # ── Tier 3: rule labels (noisy) ─────────────────────────────────────────
    t3 = cfg["tier3"]
    if t3["hotel_include"]:
        hotel_pool = master_attr[master_attr["archetype"] == "hotel"]
        for midx in hotel_pool.index:
            rows.append({"master_idx": int(midx), "archetype": "hotel", "tier": 3})
        _log(f"  Tier 3 hotel: {len(hotel_pool):,}")

    if t3["sports_include"]:
        # sport_culture bundled → treat as 'sports' (culture dropped per 37% accuracy)
        sports_pool = master_attr[
            (master_attr["archetype"] == "sport_culture")
            & (master_attr["bundled_label"].fillna(False).astype(bool))
        ]
        for midx in sports_pool.index:
            rows.append({"master_idx": int(midx), "archetype": "sports", "tier": 3})
        _log(f"  Tier 3 sports (from bundled sport_culture): {len(sports_pool):,}")
        _log(f"    ℹ culture 丢弃(准确率仅37%); sports/culture拆分待外部OSM标签")

    _log(f"  Tier 2+3 合计: {len(rows):,} 条")
    return pd.DataFrame(rows)


# =========================================================================== #
# Step 1: 特征工程                                                             #
# =========================================================================== #

def compute_all_features(master: gpd.GeoDataFrame, euluc_gpkg: Path,
                          shp26: Path, cfg: dict) -> tuple[pd.DataFrame, list[str]]:
    """计算 843k 栋全量特征(邻域特征需全量上下文)。
    返回 X_df (index=master rownum) 和 feature_names。
    """
    _log("Step 1: 特征工程开始...")
    metric_epsg = cfg["metric_epsg"]
    feat_cfg = cfg["features"]

    # 形状系
    _log("  形状系...")
    gm = F.shape_features(master, metric_epsg,
                           aspect_min_side_m=feat_cfg["aspect_ratio_min_side_m"])

    # 规模系
    _log("  规模系...")
    F.scale_features(master)

    # 邻域系
    _log("  邻域系(cKDTree, 可能需 1-2 分钟)...")
    _ = F.neighborhood_features(master, gm, radius_m=feat_cfg["neighborhood_radius_m"],
                                  no_neighbor_fill=feat_cfg["no_neighbor_fill"])

    # 供应商 ep 字段
    _log("  供应商 ep 字段...")
    if shp26.exists():
        F.attach_vendor_fields(master, shp26)
    else:
        _log(f"  ⚠ 2026 shp 不存在: {shp26}; ep 特征设 NaN")
        master["ep"] = np.nan

    # parcel 系
    _log("  parcel 系(EULUC join)...")
    F.parcel_features(master, euluc_gpkg, metric_epsg)

    # 构建特征矩阵
    _log("  构建特征矩阵...")
    X_df = F.build_feature_matrix(master)
    feature_names = X_df.columns.tolist()

    # 附加 B3 新增特征(footprint_m2 重命名为 building_footprint)
    # 注: area_m2 已在 NUMERIC_FEATURES 中，即为 building_footprint(EPSG:4547 投影计算)
    # gross_floor_area = gfa_m2 (已计算)
    # height, perimeter_m, aspect_ratio, compactness, convexity 均已计算

    _log(f"  特征矩阵: {X_df.shape[0]:,} 行 × {X_df.shape[1]} 列")
    return X_df, feature_names


# =========================================================================== #
# Step 2: 三模型对比                                                           #
# =========================================================================== #

def prepare_train_test_arrays(
    master_attr: pd.DataFrame,
    X_df: pd.DataFrame,
    train_gt: pd.DataFrame,
    test_gt: pd.DataFrame,
    tier23: pd.DataFrame,
    classes: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray]:
    """将所有训练数据组合为 numpy 数组。
    Returns: X_train, y_train, lat_train, lon_train, X_test, y_test, lat_test, lon_test
    """
    # Tier 1 training (gold, matched to master)
    train_matched = train_gt[train_gt["master_idx"].notna()].copy()
    train_matched["master_idx"] = train_matched["master_idx"].astype(int)
    t1_midx = train_matched["master_idx"].to_numpy()
    t1_arch = train_matched["archetype"].to_numpy()
    t1_lat = train_matched["lat"].to_numpy(dtype=float)
    t1_lon = train_matched["lon"].to_numpy(dtype=float)

    # Fill NaN lat/lon from master centroids (B2 records have no field coordinates)
    nan_ll = np.isnan(t1_lat)
    if nan_ll.any():
        centroid_fill = master_attr.loc[t1_midx[nan_ll], ["centroid_lat", "centroid_lon"]].to_numpy()
        t1_lat[nan_ll] = centroid_fill[:, 0]
        t1_lon[nan_ll] = centroid_fill[:, 1]

    # Tier 2+3 (from master_attr, index=master rownum)
    t23_valid = tier23[tier23["master_idx"].isin(X_df.index)].copy()
    t23_midx = t23_valid["master_idx"].to_numpy()
    t23_arch = t23_valid["archetype"].to_numpy()
    # Get centroids for spatial grouping
    centroids = master_attr.loc[t23_midx, ["centroid_lat", "centroid_lon"]].to_numpy()
    t23_lat = centroids[:, 0]
    t23_lon = centroids[:, 1]

    # Combine training
    all_midx = np.concatenate([t1_midx, t23_midx])
    y_train_raw = np.concatenate([t1_arch, t23_arch])
    lat_train = np.concatenate([t1_lat, t23_lat])
    lon_train = np.concatenate([t1_lon, t23_lon])
    X_train = X_df.loc[all_midx].to_numpy()

    # Test set
    test_matched = test_gt[test_gt["master_idx"].notna()].copy()
    test_matched["master_idx"] = test_matched["master_idx"].astype(int)
    t_midx = test_matched["master_idx"].to_numpy()
    X_test = X_df.loc[t_midx].to_numpy()
    y_test_raw = test_matched["archetype"].to_numpy()
    lat_test = test_matched["lat"].to_numpy(dtype=float)
    lon_test = test_matched["lon"].to_numpy(dtype=float)

    # Fill NaN lat/lon from master centroids (B2 records in test have no field coordinates)
    nan_ll_test = np.isnan(lat_test)
    if nan_ll_test.any():
        centroid_fill_test = master_attr.loc[t_midx[nan_ll_test], ["centroid_lat", "centroid_lon"]].to_numpy()
        lat_test[nan_ll_test] = centroid_fill_test[:, 0]
        lon_test[nan_ll_test] = centroid_fill_test[:, 1]

    _log(f"  训练集: {len(X_train):,} | 测试集: {len(X_test):,}")
    return (X_train, y_train_raw, lat_train, lon_train,
            X_test, y_test_raw, lat_test, lon_test)


def get_classes_and_distributions(
    train_gt: pd.DataFrame, test_gt: pd.DataFrame, tier23: pd.DataFrame,
) -> tuple[list[str], pd.DataFrame]:
    """确定类别列表并生成分布报告表格。"""
    all_labels = set()
    all_labels.update(train_gt["archetype"].dropna().unique())
    all_labels.update(test_gt["archetype"].dropna().unique() if len(test_gt) else [])
    all_labels.update(tier23["archetype"].dropna().unique())
    # Remove unclear from model classes
    all_labels.discard("unclear")
    classes = sorted(all_labels)

    # Build distribution table
    def counts_for(df):
        return df["archetype"].value_counts() if len(df) else pd.Series(dtype=int)

    rows = []
    t1_train_cnts = counts_for(train_gt)
    t1_test_cnts = counts_for(test_gt)
    t23_cnts = tier23["archetype"].value_counts() if len(tier23) else pd.Series(dtype=int)
    all_arch = sorted(set(classes) | set(t1_train_cnts.index) | set(t1_test_cnts.index))
    for a in all_arch:
        rows.append({
            "archetype": a,
            "tier1_train": int(t1_train_cnts.get(a, 0)),
            "tier1_test": int(t1_test_cnts.get(a, 0)),
            "tier23_train": int(t23_cnts.get(a, 0)),
            "total_train": int(t1_train_cnts.get(a, 0)) + int(t23_cnts.get(a, 0)),
        })
    dist_df = pd.DataFrame(rows).sort_values("total_train", ascending=False)
    return classes, dist_df


def evaluate_model_on_test(model, X_test: np.ndarray, y_test: np.ndarray,
                            classes: list[str], cfg: dict) -> dict:
    """测试集单次评估: accuracy + macro-F1 + log_loss + bootstrap CI。"""
    seed = cfg["seed"]
    n_boot = cfg["evaluation"]["bootstrap_n"]
    rng = np.random.default_rng(seed)

    y_pred = model.predict(X_test)
    # Unwrap only true array/list elements (not strings, which also have __len__)
    if len(y_pred) > 0 and isinstance(y_pred[0], (np.ndarray, list)):
        y_pred = np.array([p[0] for p in y_pred])
    # explicit str conversion via list comprehension to avoid numpy dtype truncation
    y_pred = np.array([str(p) for p in y_pred])
    y_test_s = np.array([str(t) for t in y_test])

    correct = (y_test_s == y_pred).astype(float)
    acc = float(correct.mean())
    lo, hi = bootstrap_ci(correct, n_boot, rng)
    f1 = f1_score(y_test_s, y_pred, average="macro", zero_division=0, labels=classes)
    try:
        proba = model.predict_proba(X_test)
        proba_classes = list(model.classes_)
        proba_aligned = np.zeros((len(y_test), len(classes)))
        for ci, cls in enumerate(classes):
            if cls in proba_classes:
                proba_aligned[:, ci] = proba[:, proba_classes.index(cls)]
        proba_aligned = np.clip(proba_aligned, 1e-10, 1)
        proba_aligned /= proba_aligned.sum(axis=1, keepdims=True)
        ll = log_loss(y_test_s, proba_aligned, labels=classes)
    except Exception:
        ll = np.nan
        proba_aligned = None

    return {
        "accuracy": acc, "acc_ci_lo": lo, "acc_ci_hi": hi,
        "macro_f1": f1, "log_loss": ll,
        "proba_aligned": proba_aligned,
        "y_pred": y_pred,
    }


def train_compare_models(
    X_train: np.ndarray, y_train: np.ndarray,
    lat_train: np.ndarray, lon_train: np.ndarray,
    X_test: np.ndarray, y_test: np.ndarray,
    classes: list[str], cfg: dict,
    out_dir: Path,
) -> dict:
    """Step 2: 三模型训练 + CV 评估 + 测试集评估。返回 {model_name: model}。"""
    seed = cfg["seed"]
    cv_cfg = cfg["cv"]
    smote_cfg = cfg["smote"]
    top_n = cfg["evaluation"]["feature_importance_top_n"]

    # Filter training to known classes only (discard 'unclear' etc.)
    known_mask = np.isin(y_train, classes)
    if not known_mask.all():
        n_dropped = int((~known_mask).sum())
        _log(f"  过滤训练集中未知类别样本: {n_dropped} 条 ({np.unique(y_train[~known_mask])})")
        X_train = X_train[known_mask]
        y_train = y_train[known_mask]
        lat_train = lat_train[known_mask]
        lon_train = lon_train[known_mask]

    # Filter test to known classes only
    known_test_mask = np.isin(y_test, classes)
    if not known_test_mask.all():
        X_test = X_test[known_test_mask]
        y_test = y_test[known_test_mask]

    # Spatial groups for CV
    groups = make_spatial_groups(lat_train, lon_train, grid_deg=cv_cfg["grid_deg"])
    n_groups = len(np.unique(groups))
    _log(f"  GroupKFold: {n_groups} 空间网格组, K={cv_cfg['n_splits']}")

    # Label encoding (for XGBoost which needs int labels)
    le = LabelEncoder()
    le.fit(classes)
    y_train_int = le.transform(y_train)
    y_test_int = le.transform(y_test)

    results = []
    imp_dfs = {}
    trained_models = {}

    # ── Random Forest ────────────────────────────────────────────────────────
    _log("  [RF] 训练中...")
    rf_params = dict(cfg["models"]["rf"])
    rf_params.pop("n_jobs", None)
    rf_full = RandomForestClassifier(**cfg["models"]["rf"], random_state=seed)
    # Apply SMOTE on full training set before fitting final model
    X_tr_r, y_tr_r = resample_training_fold(
        X_train, y_train, smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rf_full.fit(X_tr_r, y_tr_r)

    rf_cv = cross_val_evaluate(
        RandomForestClassifier, cfg["models"]["rf"],
        X_train, y_train, groups, classes,
        cv_cfg["n_splits"], smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed,
    )
    rf_test = evaluate_model_on_test(rf_full, X_test, y_test, classes, cfg)
    trained_models["rf"] = rf_full
    imp_dfs["rf"] = get_feature_importance(rf_full, None, "rf")  # feature_names attached below

    _log(f"  [RF] test_acc={rf_test['accuracy']:.3f} macro_f1={rf_test['macro_f1']:.3f} "
         f"logloss={rf_test['log_loss']:.3f}")
    _log(f"  [RF] CV acc={rf_cv['cv_accuracy'].mean():.3f}±{rf_cv['cv_accuracy'].std():.3f}")

    # ── XGBoost ─────────────────────────────────────────────────────────────
    _log("  [XGB] 训练中...")
    xgb_params = dict(cfg["models"]["xgb"])
    xgb_params["num_class"] = len(classes)
    xgb_params["objective"] = "multi:softprob"
    xgb_params["random_state"] = seed
    xgb_full = XGBClassifier(**xgb_params)
    X_tr_r2, y_tr_r2 = resample_training_fold(
        X_train, y_train_int, smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xgb_full.fit(X_tr_r2, y_tr_r2)

    # XGBoost CV — per-fold remapping to handle folds with missing classes
    def xgb_cv_wrapper(cls, params, X, y, groups, classes, n_splits, k, fb, seed):
        le_inner = LabelEncoder()
        le_inner.fit(classes)
        y_int_full = le_inner.transform(y)   # global 0..K-1
        n_classes = len(classes)
        gkf = GroupKFold(n_splits=n_splits)
        accs, f1s, lls = [], [], []
        for fi, (tr_idx, va_idx) in enumerate(gkf.split(X, y_int_full, groups)):
            X_tr, y_tr = X[tr_idx], y_int_full[tr_idx]
            X_va, y_va_int = X[va_idx], y_int_full[va_idx]
            X_tr_r, y_tr_r = resample_training_fold(X_tr, y_tr, k, fb, seed + fi)
            # Remap to consecutive 0..K_fold-1 (handles absent classes in this fold)
            present = sorted(np.unique(y_tr_r.astype(int)).tolist())
            remap = {old: new for new, old in enumerate(present)}
            revmap = {new: old for new, old in enumerate(present)}
            y_tr_remap = np.array([remap[int(c)] for c in y_tr_r], dtype=int)
            p_xgb = dict(params)
            p_xgb["random_state"] = seed + fi
            p_xgb["num_class"] = len(present)
            p_xgb["objective"] = "multi:softprob"
            model = XGBClassifier(**p_xgb)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model.fit(X_tr_r, y_tr_remap)
            y_pred_local = model.predict(X_va).astype(int)
            y_pred_global = np.array([revmap.get(p, present[0]) for p in y_pred_local])
            y_pred = le_inner.inverse_transform(y_pred_global)
            y_va = le_inner.inverse_transform(y_va_int)
            accs.append(accuracy_score(y_va, y_pred))
            f1s.append(f1_score(y_va, y_pred, average="macro", zero_division=0, labels=classes))
            prob_local = model.predict_proba(X_va)
            prob_full = np.zeros((len(y_va), n_classes))
            for local_ci, global_ci in enumerate(present):
                prob_full[:, global_ci] = prob_local[:, local_ci]
            prob_full = np.clip(prob_full, 1e-10, 1)
            prob_full /= prob_full.sum(axis=1, keepdims=True)
            lls.append(log_loss(y_va_int, prob_full, labels=list(range(n_classes))))
        return {"cv_accuracy": np.array(accs), "cv_f1": np.array(f1s), "cv_logloss": np.array(lls)}

    xgb_cv = xgb_cv_wrapper(
        XGBClassifier, cfg["models"]["xgb"],
        X_train, y_train, groups, classes,
        cv_cfg["n_splits"], smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed,
    )
    xgb_test = evaluate_model_on_test(xgb_full, X_test, y_test_int, classes, cfg)
    # Map int predictions back to class labels
    xgb_test["y_pred"] = le.inverse_transform(
        np.array(xgb_test["y_pred"], dtype=float).astype(int))
    y_test_str = np.array([str(t) for t in y_test])
    xgb_test["accuracy"] = float((y_test_str == xgb_test["y_pred"]).mean())
    xgb_test["macro_f1"] = f1_score(y_test_str, xgb_test["y_pred"], average="macro",
                                     zero_division=0, labels=classes)
    # Recompute XGB log_loss with properly aligned probabilities
    try:
        xgb_proba = xgb_full.predict_proba(X_test)
        xgb_proba_classes = [le.inverse_transform([i])[0] for i in range(len(le.classes_))]
        xgb_proba_aligned = np.zeros((len(y_test), len(classes)))
        for ci, cls in enumerate(classes):
            if cls in xgb_proba_classes:
                xgb_proba_aligned[:, ci] = xgb_proba[:, xgb_proba_classes.index(cls)]
        xgb_proba_aligned = np.clip(xgb_proba_aligned, 1e-10, 1)
        xgb_proba_aligned /= xgb_proba_aligned.sum(axis=1, keepdims=True)
        xgb_test["log_loss"] = log_loss(y_test_str, xgb_proba_aligned, labels=classes)
    except Exception:
        pass
    trained_models["xgb"] = xgb_full
    imp_dfs["xgb"] = get_feature_importance(xgb_full, None, "xgb")
    _log(f"  [XGB] test_acc={xgb_test['accuracy']:.3f} macro_f1={xgb_test['macro_f1']:.3f} "
         f"logloss={xgb_test['log_loss']:.3f}")
    _log(f"  [XGB] CV acc={xgb_cv['cv_accuracy'].mean():.3f}±{xgb_cv['cv_accuracy'].std():.3f}")

    # ── CatBoost ────────────────────────────────────────────────────────────
    _log("  [CatBoost] 训练中...")
    cat_params = dict(cfg["models"]["cat"])
    cat_full = CatBoostClassifier(**cat_params)
    X_tr_r3, y_tr_r3 = resample_training_fold(
        X_train, y_train, smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cat_full.fit(X_tr_r3, y_tr_r3, verbose=False)

    cat_cv = cross_val_evaluate_catboost(
        CatBoostClassifier, cfg["models"]["cat"],
        X_train, y_train, groups, classes,
        cv_cfg["n_splits"], smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed,
    )
    cat_test_raw = evaluate_model_on_test(cat_full, X_test, y_test, classes, cfg)
    trained_models["cat"] = cat_full
    imp_dfs["cat"] = get_feature_importance(cat_full, None, "catboost")
    _log(f"  [CatBoost] test_acc={cat_test_raw['accuracy']:.3f} "
         f"macro_f1={cat_test_raw['macro_f1']:.3f} logloss={cat_test_raw['log_loss']:.3f}")
    _log(f"  [CatBoost] CV acc={cat_cv['cv_accuracy'].mean():.3f}±{cat_cv['cv_accuracy'].std():.3f}")

    # ── Comparison table ─────────────────────────────────────────────────────
    comparison = pd.DataFrame([
        {
            "model": "RandomForest",
            "test_accuracy": rf_test["accuracy"],
            "test_macro_f1": rf_test["macro_f1"],
            "test_log_loss": rf_test["log_loss"],
            "cv_acc_mean": rf_cv["cv_accuracy"].mean(),
            "cv_acc_std": rf_cv["cv_accuracy"].std(),
            "cv_f1_mean": rf_cv["cv_f1"].mean(),
            "cv_f1_std": rf_cv["cv_f1"].std(),
            "cv_logloss_mean": rf_cv["cv_logloss"].mean(),
            "cv_logloss_std": rf_cv["cv_logloss"].std(),
        },
        {
            "model": "XGBoost",
            "test_accuracy": xgb_test["accuracy"],
            "test_macro_f1": xgb_test["macro_f1"],
            "test_log_loss": xgb_test["log_loss"],
            "cv_acc_mean": xgb_cv["cv_accuracy"].mean(),
            "cv_acc_std": xgb_cv["cv_accuracy"].std(),
            "cv_f1_mean": xgb_cv["cv_f1"].mean(),
            "cv_f1_std": xgb_cv["cv_f1"].std(),
            "cv_logloss_mean": xgb_cv["cv_logloss"].mean(),
            "cv_logloss_std": xgb_cv["cv_logloss"].std(),
        },
        {
            "model": "CatBoost",
            "test_accuracy": cat_test_raw["accuracy"],
            "test_macro_f1": cat_test_raw["macro_f1"],
            "test_log_loss": cat_test_raw["log_loss"],
            "cv_acc_mean": cat_cv["cv_accuracy"].mean(),
            "cv_acc_std": cat_cv["cv_accuracy"].std(),
            "cv_f1_mean": cat_cv["cv_f1"].mean(),
            "cv_f1_std": cat_cv["cv_f1"].std(),
            "cv_logloss_mean": cat_cv["cv_logloss"].mean(),
            "cv_logloss_std": cat_cv["cv_logloss"].std(),
        },
    ])

    return {
        "comparison": comparison,
        "models": trained_models,
        "imp_dfs": imp_dfs,
        "test_results": {
            "rf": rf_test, "xgb": xgb_test, "cat": cat_test_raw,
        },
        "cv_results": {
            "rf": rf_cv, "xgb": xgb_cv, "cat": cat_cv,
        },
        "le": le,
    }


# =========================================================================== #
# Step 3: 超参数调优                                                           #
# =========================================================================== #

def hyperparameter_tuning(
    model_name: str,
    X_train: np.ndarray, y_train: np.ndarray,
    lat_train: np.ndarray, lon_train: np.ndarray,
    classes: list[str], cfg: dict,
    le: LabelEncoder | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Grid search on the selected model. 选择 CV 方差最小的组合(Yuqian Table 3)。"""
    seed = cfg["seed"]
    cv_cfg = cfg["cv"]
    smote_cfg = cfg["smote"]
    tune_cfg = cfg["tuning"][model_name]
    groups = make_spatial_groups(lat_train, lon_train, grid_deg=cv_cfg["grid_deg"])

    _log(f"  超参数搜索: {model_name} — 枚举参数网格...")
    param_keys = [k for k in tune_cfg if k != "random_state"]
    param_vals = [tune_cfg[k] for k in param_keys]
    grid = list(iterproduct(*param_vals))
    _log(f"  网格大小: {len(grid)} 组 × {cv_cfg['n_splits']} folds")

    records = []
    for combo in grid:
        params = dict(zip(param_keys, combo))
        if model_name == "rf":
            full_params = dict(cfg["models"]["rf"])
            full_params.update(params)
            cv_res = cross_val_evaluate(
                RandomForestClassifier, full_params,
                X_train, y_train, groups, classes,
                cv_cfg["n_splits"], smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed,
            )
        elif model_name == "xgb":
            full_params = dict(cfg["models"]["xgb"])
            full_params.update(params)
            y_int = le.transform(y_train)
            def xgb_cv_fn(cls, p, X, y, gr, cls_list, ns, k, fb, s):
                gkf = GroupKFold(n_splits=ns)
                accs, f1s, lls = [], [], []
                for fi, (ti, vi) in enumerate(gkf.split(X, y, gr)):
                    X_r, y_r = resample_training_fold(X[ti], y[ti], k, fb, s + fi)
                    m = cls(**p, random_state=s)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        m.fit(X_r, y_r)
                    yp = m.predict(X[vi])
                    accs.append(accuracy_score(y[vi], yp))
                    f1s.append(f1_score(le.inverse_transform(y[vi]),
                                        le.inverse_transform(yp.astype(int)),
                                        average="macro", zero_division=0, labels=cls_list))
                    prob = m.predict_proba(X[vi])
                    lls.append(log_loss(y[vi], prob))
                return {"cv_accuracy": np.array(accs), "cv_f1": np.array(f1s),
                        "cv_logloss": np.array(lls)}
            cv_res = xgb_cv_fn(
                XGBClassifier, full_params, X_train, y_int, groups, classes,
                cv_cfg["n_splits"], smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed,
            )
        else:  # cat
            full_params = dict(cfg["models"]["cat"])
            full_params.update(params)
            cv_res = cross_val_evaluate_catboost(
                CatBoostClassifier, full_params,
                X_train, y_train, groups, classes,
                cv_cfg["n_splits"], smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed,
            )

        row = dict(params)
        row.update({
            "cv_acc_mean": cv_res["cv_accuracy"].mean(),
            "cv_acc_std": cv_res["cv_accuracy"].std(),
            "cv_f1_mean": cv_res["cv_f1"].mean(),
            "cv_f1_std": cv_res["cv_f1"].std(),
        })
        records.append(row)

    tune_df = pd.DataFrame(records)
    # 选择方差最小的组合(Yuqian 选择标准)
    best_row = tune_df.loc[tune_df["cv_f1_std"].idxmin()]
    best_params = {k: best_row[k] for k in param_keys}
    _log(f"  最优参数(方差最小): {best_params}")
    _log(f"  最优 CV F1: {best_row['cv_f1_mean']:.3f}±{best_row['cv_f1_std']:.3f}")
    return best_params, tune_df


# =========================================================================== #
# Step 4: 全量预测                                                             #
# =========================================================================== #

def predict_all_buildings(
    model, X_df: pd.DataFrame, master_attr: pd.DataFrame,
    classes: list[str], cfg: dict, out_dir: Path,
    le: LabelEncoder | None = None,
) -> pd.DataFrame:
    """对所有 unknown 建筑进行预测,输出预测结果 parquet。"""
    _log(f"Step 4: 全量预测...")
    unknown_mask = master_attr["archetype"] == "unknown"
    unknown_idx = master_attr.index[unknown_mask]
    _log(f"  unknown 建筑: {len(unknown_idx):,} 栋")

    X_unk = X_df.loc[unknown_idx].to_numpy()
    preds = model.predict(X_unk)
    if hasattr(preds[0], "__len__"):
        preds = np.array([p[0] for p in preds])
    if le is not None:
        preds = le.inverse_transform(preds.astype(int))
    preds = np.array(preds, dtype=str)

    proba = model.predict_proba(X_unk)
    proba_classes = list(model.classes_)
    max_prob = proba.max(axis=1)

    out = pd.DataFrame({
        "master_idx": unknown_idx,
        "predicted_archetype": preds,
        "ml_probability": max_prob,
    })

    # Archetype distribution
    dist = out.groupby("predicted_archetype").agg(
        n_buildings=("master_idx", "count"),
    ).reset_index()
    dist["gfa_m2"] = [
        master_attr.loc[out[out["predicted_archetype"] == a, "master_idx"], "gfa_m2"].sum()
        if "gfa_m2" in master_attr.columns else np.nan
        for a in dist["predicted_archetype"]
    ]
    _log(f"\n  全市预测分布:")
    for _, row in dist.sort_values("n_buildings", ascending=False).iterrows():
        _log(f"    {row['predicted_archetype']:30s}: {int(row['n_buildings']):7,} 栋")

    # Save
    out_path = out_dir / cfg["prediction"]["output_parquet"]
    out.to_parquet(out_path, index=False)
    _log(f"  预测结果写入: {out_path}")

    # GMM probability analysis
    gmm_path = str(FIG_DIR / "b3_probability_gmm.png")
    os.makedirs(FIG_DIR, exist_ok=True)
    gmm_res = plot_probability_gmm(max_prob, gmm_path, model.__class__.__name__)
    _log(f"  GMM AIC: {[f'{v:.0f}' for v in gmm_res['aic']]}")
    _log(f"  GMM BIC: {[f'{v:.0f}' for v in gmm_res['bic']]}")

    return out, dist


# =========================================================================== #
# Main                                                                          #
# =========================================================================== #

def main() -> None:
    parser = argparse.ArgumentParser(description="B3 正式训练")
    parser.add_argument("--data-dir", required=True, type=Path,
                        help="解压后的 gpkg 文件目录")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="大文件输出目录(parquet/joblib, 不 commit)")
    parser.add_argument("--best-model", choices=["rf", "xgb", "cat"], default=None,
                        help="Step 3 超参数调优: 选哪个模型")
    parser.add_argument("--predict", action="store_true",
                        help="Step 4: 全量预测(需 --best-model)")
    parser.add_argument("--residential-n", type=int, default=None,
                        help="覆盖 Tier 2 residential 降采样数量")
    args = parser.parse_args()

    data_dir = args.data_dir
    out_dir = args.out_dir or data_dir
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(REF_DIR, exist_ok=True)
    os.makedirs(FIG_DIR, exist_ok=True)

    cfg = load_config()
    if args.residential_n:
        cfg["tier2"]["residential_downsample_n"] = args.residential_n

    master_gpkg = data_dir / "module_a_master.gpkg"
    euluc_gpkg = data_dir / "euluc_shanghai_2022.gpkg"
    shp26 = data_dir / "2026 Building" / "2026 Building.shp"

    _log("=" * 65)
    _log("B3 正式训练 — Module B archetype 推断")
    _log("=" * 65)

    # ── Step 0: 数据准备 ──────────────────────────────────────────────────
    _log("\n[Step 0] 数据准备")
    gt_all = load_ground_truth(cfg)
    train_gt_raw, test_gt_raw = split_train_test(gt_all, cfg)

    _log("\n  加载 master.gpkg...")
    master = F.load_master(master_gpkg)   # adds bid column needed by attach_vendor_fields
    master_attr = pyogrio.read_dataframe(master_gpkg, read_geometry=False)
    # Centroids for spatial grouping (needed before feature computation)
    _log("  计算楼栋质心(spatial grouping 用)...")
    centroids_m = master.geometry.representative_point()
    master_attr["centroid_lat"] = centroids_m.y.to_numpy()
    master_attr["centroid_lon"] = centroids_m.x.to_numpy()

    # Match ground truth to master
    _log("\n  匹配人工真值到 master.gpkg...")
    train_gt = match_to_master(train_gt_raw, master, cfg["truth"]["match_max_distance_m"],
                                cfg["metric_epsg"])
    test_gt = match_to_master(test_gt_raw, master, cfg["truth"]["match_max_distance_m"],
                               cfg["metric_epsg"])

    # Build Tier 2+3
    _log("\n  构建 Tier 2 (EULUC) + Tier 3 (规则) 训练标签...")
    tier23 = build_tier2_tier3(master_attr, cfg, cfg["seed"])

    # Classes and distribution
    classes, dist_df = get_classes_and_distributions(train_gt, test_gt, tier23)

    _log("\n  ── 训练/测试集类别分布 ──")
    _log(f"  {'Archetype':25s} {'T1-train':>8} {'T1-test':>8} {'T2+3-train':>10} {'Total-train':>11}")
    _log(f"  {'-'*65}")
    for _, row in dist_df.iterrows():
        _log(f"  {row['archetype']:25s} {row['tier1_train']:8d} {row['tier1_test']:8d} "
             f"{row['tier23_train']:10d} {row['total_train']:11d}")
    _log(f"  {'-'*65}")
    _log(f"  {'TOTAL':25s} {dist_df['tier1_train'].sum():8d} {dist_df['tier1_test'].sum():8d} "
         f"{dist_df['tier23_train'].sum():10d} {dist_df['total_train'].sum():11d}")
    _log(f"\n  测试集建筑数: {len(test_gt)} | 可参与预测评估: {test_gt['master_idx'].notna().sum()}")

    # Save Step 0 outputs
    dist_df.to_csv(REF_DIR / "b3_class_distribution.csv", index=False)
    _log(f"\n  → 分布表写入 {REF_DIR}/b3_class_distribution.csv")

    # ── Step 1: 特征工程 ──────────────────────────────────────────────────
    _log("\n[Step 1] 特征工程")
    # Unzip EULUC if needed
    if not euluc_gpkg.exists():
        import zipfile
        euluc_zip = Path("/home/user/Yuqian_Shanghai-Energy-data/euluc_shanghai_2022.gpkg.zip")
        if euluc_zip.exists():
            _log(f"  解压 EULUC gpkg...")
            with zipfile.ZipFile(euluc_zip) as zf:
                zf.extractall(data_dir)
    X_df, feature_names = compute_all_features(master, euluc_gpkg, shp26, cfg)
    # Attach gfa_m2 to master_attr for prediction output
    if "gfa_m2" in master.columns:
        master_attr["gfa_m2"] = master["gfa_m2"].to_numpy()

    # Attach feature names to imp_dfs later
    _log(f"  特征维度: {len(feature_names)}")

    # ── Step 2: 三模型对比 ────────────────────────────────────────────────
    _log("\n[Step 2] 三模型对比")
    _log(f"  类别列表 ({len(classes)}): {classes}")

    # Prepare arrays
    (X_train, y_train, lat_train, lon_train,
     X_test, y_test, lat_test, lon_test) = prepare_train_test_arrays(
        master_attr, X_df, train_gt, test_gt, tier23, classes,
    )

    if len(X_train) == 0 or len(X_test) == 0:
        _log("  ⛔ 训练集或测试集为空 — 停止")
        return

    step2_results = train_compare_models(
        X_train, y_train, lat_train, lon_train,
        X_test, y_test, classes, cfg, out_dir,
    )
    comparison = step2_results["comparison"]
    imp_dfs = step2_results["imp_dfs"]

    # Attach feature names to importance dfs
    for name, df in imp_dfs.items():
        df["feature"] = feature_names[:len(df)]

    # Save comparison table
    comparison_path = REF_DIR / "b3_model_comparison.csv"
    comparison.to_csv(comparison_path, index=False)

    # Save per-class metrics for best model (preliminary)
    best_acc_model = comparison.loc[comparison["test_accuracy"].idxmax(), "model"]
    _log(f"\n  ── Step 2 结果汇总 ──")
    _log(f"  {'Model':15s} {'TestAcc':>8} {'MacroF1':>8} {'LogLoss':>9} "
         f"{'CV_acc_mean':>12} {'CV_acc_std':>10}")
    _log(f"  {'-'*67}")
    for _, row in comparison.iterrows():
        _log(f"  {row['model']:15s} {row['test_accuracy']:8.4f} {row['test_macro_f1']:8.4f} "
             f"{row['test_log_loss']:9.4f} {row['cv_acc_mean']:12.4f} {row['cv_acc_std']:10.4f}")

    # Feature importance comparison figure
    fi_path = str(FIG_DIR / "b3_feature_importance_comparison.png")
    feat_len = len(feature_names)
    for name, df in imp_dfs.items():
        df["feature"] = (feature_names + ["unknown"] * max(0, len(df) - feat_len))[:len(df)]
    plot_feature_importance_comparison(
        imp_dfs["rf"], imp_dfs["xgb"], imp_dfs["cat"],
        cfg["evaluation"]["feature_importance_top_n"], fi_path,
    )
    _log(f"  → 特征重要性图: {fi_path}")
    _log(f"  → 对比表: {comparison_path}")

    # Save per-model feature importance
    for name, df in imp_dfs.items():
        df.head(20).to_csv(REF_DIR / f"b3_feature_importance_{name}.csv", index=False)

    _log("\n  ═══════════════════════════════════════════════════════════")
    _log(f"  Step 2 完成. 最佳模型(测试集准确率): {best_acc_model}")
    _log("  请根据以上结果选择最优模型, 然后运行 Step 3:")
    _log("  python scripts/b3_formal_training.py --data-dir <dir> --best-model <rf|xgb|cat>")
    _log("  ═══════════════════════════════════════════════════════════")

    # ── Step 3: 超参数调优 ────────────────────────────────────────────────
    if not args.best_model:
        return

    best_model_name = args.best_model
    _log(f"\n[Step 3] 超参数调优: {best_model_name}")
    le_obj = step2_results.get("le")

    # Per-class F1 + confusion matrix for baseline model
    baseline_model = step2_results["models"][best_model_name]
    baseline_test = step2_results["test_results"][best_model_name]
    y_pred_baseline = baseline_test["y_pred"]
    _log("\n  调优前 per-class F1:")
    report_str = classification_report(
        y_test, y_pred_baseline, labels=classes, zero_division=0, digits=3,
    )
    _log(report_str)

    cm_before = confusion_matrix(y_test, y_pred_baseline, labels=classes)
    plot_confusion_matrix(cm_before, classes,
                          str(FIG_DIR / f"b3_confusion_before_tuning_{best_model_name}.png"),
                          title=f"B3 {best_model_name} (before tuning)")

    # Grid search
    best_params, tune_df = hyperparameter_tuning(
        best_model_name, X_train, y_train, lat_train, lon_train, classes, cfg,
        le=le_obj,
    )
    tune_df.to_csv(REF_DIR / f"b3_tuning_grid_{best_model_name}.csv", index=False)

    # Train final tuned model
    _log("\n  训练调优后模型...")
    if best_model_name == "rf":
        tuned_cfg = dict(cfg["models"]["rf"])
        tuned_cfg.update(best_params)
        tuned_model = RandomForestClassifier(**tuned_cfg, random_state=cfg["seed"])
    elif best_model_name == "xgb":
        tuned_cfg = dict(cfg["models"]["xgb"])
        tuned_cfg.update(best_params)
        tuned_model = XGBClassifier(**tuned_cfg, random_state=cfg["seed"])
    else:
        tuned_cfg = dict(cfg["models"]["cat"])
        tuned_cfg.update(best_params)
        tuned_model = CatBoostClassifier(**tuned_cfg)

    X_tr_r_final, y_tr_r_final = resample_training_fold(
        X_train,
        le_obj.transform(y_train) if best_model_name == "xgb" else y_train,
        cfg["smote"]["k_neighbors"], cfg["smote"]["fallback_min_samples"], cfg["seed"],
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tuned_model.fit(X_tr_r_final, y_tr_r_final)

    test_y_eval = (le_obj.transform(y_test) if best_model_name == "xgb"
                   and le_obj is not None else y_test)
    tuned_test = evaluate_model_on_test(tuned_model, X_test, test_y_eval, classes, cfg)
    if best_model_name == "xgb" and le_obj is not None:
        tuned_test["y_pred"] = le_obj.inverse_transform(tuned_test["y_pred"].astype(int))
    y_pred_tuned = tuned_test["y_pred"]

    _log("\n  ── 调优前 vs 调优后对比 ──")
    _log(f"  {'Metric':12s} {'Before':>10} {'After':>10}")
    _log(f"  {'-'*35}")
    for metric_name in ["accuracy", "macro_f1", "log_loss"]:
        before_val = baseline_test[metric_name]
        after_val = tuned_test[metric_name]
        _log(f"  {metric_name:12s} {before_val:10.4f} {after_val:10.4f}")

    _log("\n  调优后 per-class F1:")
    report_after = classification_report(
        y_test, y_pred_tuned, labels=classes, zero_division=0, digits=3,
    )
    _log(report_after)

    cm_after = confusion_matrix(y_test, y_pred_tuned, labels=classes)
    plot_confusion_matrix(cm_after, classes,
                          str(FIG_DIR / f"b3_confusion_after_tuning_{best_model_name}.png"),
                          title=f"B3 {best_model_name} (tuned: {best_params})")

    # Save tuned model
    model_path = out_dir / cfg["prediction"]["output_model"]
    joblib.dump({"model": tuned_model, "classes": classes, "feature_names": feature_names,
                 "le": le_obj, "best_params": best_params}, model_path)
    _log(f"\n  → 模型写入: {model_path}")

    # Save step 3 summary
    step3_df = pd.DataFrame([{
        "model": best_model_name,
        **best_params,
        "before_accuracy": baseline_test["accuracy"],
        "after_accuracy": tuned_test["accuracy"],
        "before_macro_f1": baseline_test["macro_f1"],
        "after_macro_f1": tuned_test["macro_f1"],
        "before_log_loss": baseline_test["log_loss"],
        "after_log_loss": tuned_test["log_loss"],
    }])
    step3_df.to_csv(REF_DIR / "b3_tuning_summary.csv", index=False)

    _log("\n  ═══════════════════════════════════════════════════════════")
    _log(f"  Step 3 完成. 调优参数已保存.")
    _log("  如确认结果, 运行 Step 4 全量预测:")
    _log("  python scripts/b3_formal_training.py --data-dir <dir> "
         f"--best-model {best_model_name} --predict")
    _log("  ═══════════════════════════════════════════════════════════")

    # ── Step 4: 全量预测 ──────────────────────────────────────────────────
    if not args.predict:
        return

    _log("\n[Step 4] 全量预测")
    out_preds, arch_dist = predict_all_buildings(
        tuned_model, X_df, master_attr, classes, cfg, out_dir,
        le=le_obj if best_model_name == "xgb" else None,
    )
    arch_dist.to_csv(REF_DIR / "b3_citywide_archetype_distribution.csv", index=False)
    _log(f"  → 全市分布表写入 {REF_DIR}/b3_citywide_archetype_distribution.csv")
    _log("\nB3 完成!")


if __name__ == "__main__":
    main()
