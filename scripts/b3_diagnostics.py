"""B3 诊断脚本 — 混淆矩阵 + 消融实验

运行:
  python scripts/b3_diagnostics.py --data-dir /tmp/b3_data

输出(stdout):
  1. 训练集各类别样本数 (T1/T2/T3/合计)
  2. XGBoost 137测试集混淆矩阵 (真实标签 vs 预测标签)
  3. 消融实验: 仅 T1 174栋金标准 (accuracy + per-class F1)
  4. 若消融 > 当前 26%, 测试 residential_n=500 和 residential_n=170
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report,
)
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier
from sklearn.model_selection import GroupKFold

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.ml import features as F
from buildings_shanghai.ml.train_utils import (
    make_spatial_groups, resample_training_fold,
)

# Re-use all loading helpers from b3_formal_training.py
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from b3_formal_training import (
    load_config, load_ground_truth, split_train_test, match_to_master,
    build_tier2_tier3, compute_all_features, _log,
)

CFG_PATH = PROJECT_ROOT / "config" / "b3_formal_training.yaml"


def print_section(title: str) -> None:
    line = "=" * 70
    print(f"\n{line}")
    print(f"  {title}")
    print(line)


def run_xgb(X_train, y_train, X_test, y_test, classes, cfg,
            lat_train, lon_train, label: str = "XGBoost") -> tuple[float, np.ndarray, np.ndarray]:
    """Train XGB with SMOTE + CV params, evaluate on test. Returns (acc, y_pred, y_test_str)."""
    seed = cfg["seed"]
    smote_cfg = cfg["smote"]

    le = LabelEncoder()
    le.fit(classes)

    # Filter to known classes
    known_mask = np.isin(y_train, classes)
    X_tr = X_train[known_mask]
    y_tr = y_train[known_mask]
    lat_tr = lat_train[known_mask]
    lon_tr = lon_train[known_mask]

    known_test_mask = np.isin(y_test, classes)
    X_te = X_test[known_test_mask]
    y_te = y_test[known_test_mask]

    y_tr_int = le.transform(y_tr)
    X_tr_r, y_tr_r = resample_training_fold(
        X_tr, y_tr_int,
        smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed)

    xgb_params = dict(cfg["models"]["xgb"])
    xgb_params["num_class"] = len(classes)
    xgb_params["objective"] = "multi:softprob"
    xgb_params["random_state"] = seed
    model = XGBClassifier(**xgb_params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(X_tr_r, y_tr_r)

    y_pred_int = model.predict(X_te).astype(int)
    y_pred = le.inverse_transform(y_pred_int)
    y_test_str = np.array([str(t) for t in y_te])
    acc = float((y_test_str == y_pred).mean())
    return acc, y_pred, y_test_str


def confusion_matrix_str(y_true: np.ndarray, y_pred: np.ndarray,
                          classes: list[str]) -> str:
    """Return a readable confusion matrix string (rows=true, cols=pred)."""
    n = len(classes)
    matrix = np.zeros((n, n), dtype=int)
    cls_idx = {c: i for i, c in enumerate(classes)}
    for t, p in zip(y_true, y_pred):
        if t in cls_idx and p in cls_idx:
            matrix[cls_idx[t], cls_idx[p]] += 1

    # Shorten class names for display
    short = [c.replace("residential_", "res_")
              .replace("government_", "gov_")
              .replace("shopping_mall", "mall")
              .replace("other_public", "other_pub")
              for c in classes]

    col_w = max(len(s) for s in short) + 2
    label_w = col_w

    lines = []
    # Header row
    header = " " * label_w + "".join(f"{s:>{col_w}}" for s in short)
    lines.append(header)
    lines.append("-" * len(header))
    for i, cls in enumerate(classes):
        row_total = matrix[i].sum()
        row = f"{short[i]:<{label_w}}" + "".join(f"{matrix[i, j]:>{col_w}}" for j in range(n))
        row += f"  | n={row_total}"
        lines.append(row)
    return "\n".join(lines)


def run_diagnostics(data_dir: Path, cfg: dict) -> None:
    seed = cfg["seed"]
    smote_cfg = cfg["smote"]
    metric_epsg = cfg["metric_epsg"]
    match_dist = cfg["truth"]["match_max_distance_m"]

    # ── Load data ──────────────────────────────────────────────────────────────
    _log("Loading master.gpkg...")
    master_path = data_dir / "module_a_master.gpkg"
    euluc_path = data_dir / "euluc_shanghai_2022.gpkg"
    shp26_path = data_dir / "2026 Building" / "2026 Building.shp"

    master = F.load_master(master_path)   # adds bid column needed by attach_vendor_fields
    _log(f"  master: {len(master):,} buildings")

    # master_attr: attribute-only view + centroid lat/lon (matches main script pattern)
    import pyogrio as _pyogrio
    master_attr = _pyogrio.read_dataframe(master_path, read_geometry=False)
    rep_pts = master.geometry.representative_point()
    master_attr["centroid_lat"] = rep_pts.y.to_numpy()
    master_attr["centroid_lon"] = rep_pts.x.to_numpy()

    # ── Step 0: Ground truth ──────────────────────────────────────────────────
    _log("Loading ground truth...")
    gt = load_ground_truth(cfg)
    train_gt, test_gt = split_train_test(gt, cfg)

    _log("Matching to master...")
    train_gt = match_to_master(train_gt, master, match_dist, metric_epsg)
    test_gt = match_to_master(test_gt, master, match_dist, metric_epsg)

    # ── Step 1: Features ──────────────────────────────────────────────────────
    _log("Computing features (may take 1-2 min)...")
    X_df, feature_names = compute_all_features(master, euluc_path, shp26_path, cfg)

    # ── Build Tier 2+3 ────────────────────────────────────────────────────────
    _log("Building Tier 2+3 labels...")
    tier23 = build_tier2_tier3(master_attr, cfg, seed)

    # Determine classes
    all_labels = set()
    all_labels.update(train_gt["archetype"].dropna().unique())
    all_labels.update(test_gt["archetype"].dropna().unique())
    all_labels.update(tier23["archetype"].dropna().unique())
    all_labels.discard("unclear")
    classes = sorted(all_labels)

    # ── Prepare arrays ─────────────────────────────────────────────────────────
    def make_arrays(t1_df, t23_df):
        """Build train arrays from T1 gold + T23 combined DataFrames."""
        t1 = t1_df[t1_df["master_idx"].notna()].copy()
        t1["master_idx"] = t1["master_idx"].astype(int)
        t1_midx = t1["master_idx"].to_numpy()
        t1_arch = t1["archetype"].to_numpy()
        t1_lat = t1["lat"].to_numpy(dtype=float).copy()
        t1_lon = t1["lon"].to_numpy(dtype=float).copy()
        nan_ll = np.isnan(t1_lat)
        if nan_ll.any():
            fill = master_attr.loc[t1_midx[nan_ll], ["centroid_lat", "centroid_lon"]].to_numpy()
            t1_lat[nan_ll] = fill[:, 0]
            t1_lon[nan_ll] = fill[:, 1]

        t23_valid = t23_df[t23_df["master_idx"].isin(X_df.index)].copy()
        t23_midx = t23_valid["master_idx"].to_numpy()
        t23_arch = t23_valid["archetype"].to_numpy()
        centroids_23 = master_attr.loc[t23_midx, ["centroid_lat", "centroid_lon"]].to_numpy()
        t23_lat = centroids_23[:, 0]
        t23_lon = centroids_23[:, 1]

        all_midx = np.concatenate([t1_midx, t23_midx])
        y_tr = np.concatenate([t1_arch, t23_arch])
        lat_tr = np.concatenate([t1_lat, t23_lat])
        lon_tr = np.concatenate([t1_lon, t23_lon])
        X_tr = X_df.loc[all_midx].to_numpy()
        return X_tr, y_tr, lat_tr, lon_tr

    def make_test_arrays(t_df):
        t = t_df[t_df["master_idx"].notna()].copy()
        t["master_idx"] = t["master_idx"].astype(int)
        t_midx = t["master_idx"].to_numpy()
        X_te = X_df.loc[t_midx].to_numpy()
        y_te = t["archetype"].to_numpy()
        lat_te = t["lat"].to_numpy(dtype=float).copy()
        lon_te = t["lon"].to_numpy(dtype=float).copy()
        nan_ll = np.isnan(lat_te)
        if nan_ll.any():
            fill = master_attr.loc[t_midx[nan_ll], ["centroid_lat", "centroid_lon"]].to_numpy()
            lat_te[nan_ll] = fill[:, 0]
            lon_te[nan_ll] = fill[:, 1]
        return X_te, y_te, lat_te, lon_te

    X_test, y_test, lat_test, lon_test = make_test_arrays(test_gt)

    # ===================================================================
    # DIAGNOSTIC 1: Class distribution table (T1 / T2 / T3 / total)
    # ===================================================================
    print_section("DIAGNOSTIC 1 — Training set class distribution")

    t1_train_counts = train_gt["archetype"].value_counts()
    t1_test_counts = test_gt["archetype"].value_counts()
    t2_counts = tier23[tier23["tier"] == 2]["archetype"].value_counts()
    t3_counts = tier23[tier23["tier"] == 3]["archetype"].value_counts()

    all_arch = sorted(set(classes) | set(t1_train_counts.index) | set(t1_test_counts.index))
    print(f"\n{'Archetype':<25} {'T1-train':>10} {'T1-test':>9} {'T2(EULUC)':>10} {'T3(rule)':>9} {'Total-train':>12}")
    print("-" * 80)
    t1_tr_total = t1_te_total = t2_total = t3_total = 0
    for a in all_arch:
        t1_tr = int(t1_train_counts.get(a, 0))
        t1_te = int(t1_test_counts.get(a, 0))
        t2 = int(t2_counts.get(a, 0))
        t3 = int(t3_counts.get(a, 0))
        total = t1_tr + t2 + t3
        print(f"  {a:<23} {t1_tr:>10} {t1_te:>9} {t2:>10} {t3:>9} {total:>12}")
        t1_tr_total += t1_tr
        t1_te_total += t1_te
        t2_total += t2
        t3_total += t3
    print("-" * 80)
    print(f"  {'TOTAL':<23} {t1_tr_total:>10} {t1_te_total:>9} {t2_total:>10} {t3_total:>9} {t1_tr_total+t2_total+t3_total:>12}")

    # ===================================================================
    # DIAGNOSTIC 2: XGBoost confusion matrix (T1+T2+T3 full training)
    # ===================================================================
    print_section("DIAGNOSTIC 2 — XGBoost confusion matrix (T1+T2+T3, 137 test buildings)")

    _log("Training XGBoost (full T1+T2+T3)...")
    X_train_full, y_train_full, lat_tr_full, lon_tr_full = make_arrays(train_gt, tier23)
    acc_full, y_pred_full, y_test_str = run_xgb(
        X_train_full, y_train_full, X_test, y_test, classes, cfg,
        lat_tr_full, lon_tr_full, label="XGB-full"
    )
    print(f"\nTest accuracy (full): {acc_full:.4f}  ({int(acc_full * len(y_test_str))}/{len(y_test_str)} correct)")
    print(f"\nConfusion matrix  (rows=TRUE, cols=PREDICTED):\n")
    print(confusion_matrix_str(y_test_str, y_pred_full, classes))

    print(f"\nPer-class classification report:")
    print(classification_report(y_test_str, y_pred_full, labels=classes,
                                 zero_division=0, digits=3))

    # ===================================================================
    # DIAGNOSTIC 3: Ablation — T1 only (174 gold-standard buildings)
    # ===================================================================
    print_section("DIAGNOSTIC 3 — Ablation: T1 gold-standard only (no T2/T3)")

    _log("Training XGBoost (T1 only, 174 buildings)...")
    empty_t23 = pd.DataFrame(columns=["master_idx", "archetype", "tier"])
    X_train_t1, y_train_t1, lat_tr_t1, lon_tr_t1 = make_arrays(train_gt, empty_t23)

    # Classes visible in T1-only training
    t1_classes = sorted(set(y_train_t1) - {"unclear"})
    # Still evaluate on full class list so per-class F1 is comparable
    acc_t1, y_pred_t1, _ = run_xgb(
        X_train_t1, y_train_t1, X_test, y_test, t1_classes, cfg,
        lat_tr_t1, lon_tr_t1, label="XGB-T1only"
    )
    n_correct_t1 = int(acc_t1 * len(y_test_str))
    print(f"\nTest accuracy (T1 only): {acc_t1:.4f}  ({n_correct_t1}/{len(y_test_str)} correct)")
    print(f"  vs. full T1+T2+T3:    {acc_full:.4f}  ({int(acc_full * len(y_test_str))}/{len(y_test_str)} correct)")

    known_test_t1 = np.isin(y_test, t1_classes)
    y_te_t1 = y_test[known_test_t1]
    y_pred_t1_filtered = y_pred_t1  # already filtered in run_xgb
    print(f"\nPer-class F1 (T1-only model, {known_test_t1.sum()} testable buildings):")
    print(classification_report(np.array([str(t) for t in y_te_t1]),
                                 y_pred_t1_filtered,
                                 labels=t1_classes, zero_division=0, digits=3))

    # ===================================================================
    # DIAGNOSTIC 4: Downsample experiments (only if T1-only > full)
    # ===================================================================
    delta = acc_t1 - acc_full
    print_section("DIAGNOSTIC 4 — Downsample experiments")
    if delta <= 0:
        print(f"\nT1-only accuracy ({acc_t1:.4f}) ≤ full accuracy ({acc_full:.4f}).")
        print("T2/T3 is helping (or neutral). No downsample experiments needed.")
    else:
        print(f"\nT1-only accuracy ({acc_t1:.4f}) > full ({acc_full:.4f}) by {delta:+.4f}")
        print("T2/T3 is hurting small-class signal. Testing residential downsamples...\n")

        for res_n, label_suffix in [(500, "res=500"), (170, "res=170")]:
            cfg_mod = yaml.safe_load(open(CFG_PATH))
            # Keep total residential proportional: mid 75%, high 25%
            cfg_mod["tier2"]["residential_downsample_n"] = res_n
            # Scale education proportionally (keep ratio)
            orig_res = cfg["tier2"]["residential_downsample_n"]
            orig_edu = cfg["tier2"]["education_downsample_n"]
            cfg_mod["tier2"]["education_downsample_n"] = max(
                int(orig_edu * res_n / orig_res), 10)

            _log(f"Rebuilding Tier2+3 with residential_n={res_n}...")
            tier23_mod = build_tier2_tier3(master_attr, cfg_mod, seed)
            t2_mod_counts = tier23_mod[tier23_mod["tier"] == 2]["archetype"].value_counts()
            print(f"  residential_n={res_n}: mid={t2_mod_counts.get('residential_mid_rise', 0)}, "
                  f"high={t2_mod_counts.get('residential_high_rise', 0)}, "
                  f"edu={t2_mod_counts.get('education', 0)}")

            X_tr_mod, y_tr_mod, lat_mod, lon_mod = make_arrays(train_gt, tier23_mod)
            acc_mod, _, _ = run_xgb(
                X_tr_mod, y_tr_mod, X_test, y_test, classes, cfg,
                lat_mod, lon_mod, label=f"XGB-{label_suffix}"
            )
            print(f"  → test accuracy: {acc_mod:.4f}  ({int(acc_mod * len(y_test_str))}/{len(y_test_str)} correct)")

    print("\n" + "=" * 70)
    print("Diagnostics complete. Awaiting owner decision.")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path,
                        help="Directory with module_a_master.gpkg, euluc_shanghai_2022.gpkg, etc.")
    args = parser.parse_args()

    cfg = load_config()
    run_diagnostics(args.data_dir, cfg)


if __name__ == "__main__":
    main()
