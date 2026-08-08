"""B3 分层降采样实验 D1–D4

D1: T1 + T2/T3 每类上限 200
D2: T1 + T2/T3 每类上限 50
D3: T1 + T2 only (res/edu 各 200, 无 hotel/sports)
D4: T1 + T2 only (res/edu 各 50,  无 hotel/sports)

Usage:
  python scripts/b3_downsample_experiments.py --data-dir /tmp/b3_data
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import yaml
from sklearn.metrics import accuracy_score, f1_score, classification_report
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from buildings_shanghai.ml import features as F
from buildings_shanghai.ml.train_utils import resample_training_fold
from b3_formal_training import (
    load_config, load_ground_truth, split_train_test, match_to_master,
    compute_all_features, _log,
)

CFG_PATH = PROJECT_ROOT / "config" / "b3_formal_training.yaml"


# ── Capped Tier-2/3 builder (replaces config-driven build_tier2_tier3) ──────
def build_capped_tier23(
    master_attr: pd.DataFrame,
    caps: dict[str, int],   # archetype → max_n; missing key = no limit
    include_hotel: bool,
    include_sports: bool,
    seed: int,
) -> pd.DataFrame:
    rows = []

    # Tier 2: EULUC high-confidence residential + education
    for arch in ("residential_mid_rise", "residential_high_rise", "education"):
        mask = (
            (master_attr["archetype"] == arch)
            & (master_attr["label_rule"] == "euluc_direct")
        )
        pool = master_attr[mask]
        n = min(caps.get(arch, len(pool)), len(pool))
        sel = pool.sample(n, random_state=seed)
        for midx in sel.index:
            rows.append({"master_idx": int(midx), "archetype": arch, "tier": 2})

    # Tier 3: rule labels
    if include_hotel:
        cap = caps.get("hotel", 99_999)
        pool = master_attr[master_attr["archetype"] == "hotel"]
        sel = pool.sample(min(cap, len(pool)), random_state=seed)
        for midx in sel.index:
            rows.append({"master_idx": int(midx), "archetype": "hotel", "tier": 3})

    if include_sports:
        cap = caps.get("sports", 99_999)
        pool = master_attr[
            (master_attr["archetype"] == "sport_culture")
            & (master_attr["bundled_label"].fillna(False).astype(bool))
        ]
        sel = pool.sample(min(cap, len(pool)), random_state=seed)
        for midx in sel.index:
            rows.append({"master_idx": int(midx), "archetype": "sports", "tier": 3})

    return pd.DataFrame(rows)


# ── Array builders (from b3_diagnostics pattern) ─────────────────────────────
def make_train_arrays(train_gt, tier23, master_attr, X_df):
    t1 = train_gt[train_gt["master_idx"].notna()].copy()
    t1["master_idx"] = t1["master_idx"].astype(int)
    t1_midx = t1["master_idx"].to_numpy()
    t1_lat = t1["lat"].to_numpy(dtype=float).copy()
    t1_lon = t1["lon"].to_numpy(dtype=float).copy()
    nan_ll = np.isnan(t1_lat)
    if nan_ll.any():
        fill = master_attr.loc[t1_midx[nan_ll], ["centroid_lat", "centroid_lon"]].to_numpy()
        t1_lat[nan_ll] = fill[:, 0]
        t1_lon[nan_ll] = fill[:, 1]

    if len(tier23):
        t23 = tier23[tier23["master_idx"].isin(X_df.index)].copy()
        t23_midx = t23["master_idx"].to_numpy()
        t23_arch = t23["archetype"].to_numpy()
        c23 = master_attr.loc[t23_midx, ["centroid_lat", "centroid_lon"]].to_numpy()
        all_midx = np.concatenate([t1_midx, t23_midx])
        y_tr = np.concatenate([t1["archetype"].to_numpy(), t23_arch])
    else:
        all_midx = t1_midx
        y_tr = t1["archetype"].to_numpy()

    X_tr = X_df.loc[all_midx].to_numpy()
    return X_tr, y_tr


def make_test_arrays(test_gt, master_attr, X_df):
    t = test_gt[test_gt["master_idx"].notna()].copy()
    t["master_idx"] = t["master_idx"].astype(int)
    t_midx = t["master_idx"].to_numpy()
    X_te = X_df.loc[t_midx].to_numpy()
    y_te = t["archetype"].to_numpy()
    lat_te = t["lat"].to_numpy(dtype=float).copy()
    nan_ll = np.isnan(lat_te)
    if nan_ll.any():
        fill = master_attr.loc[t_midx[nan_ll], ["centroid_lat", "centroid_lon"]].to_numpy()
        lat_te[nan_ll] = fill[:, 0]
    return X_te, y_te


# ── XGBoost runner ────────────────────────────────────────────────────────────
def run_xgb(X_train, y_train, X_test, y_test, classes, cfg) -> dict:
    seed = cfg["seed"]
    smote_cfg = cfg["smote"]

    le = LabelEncoder()
    le.fit(classes)

    known_mask = np.isin(y_train, classes)
    X_tr = X_train[known_mask]
    y_tr_int = le.transform(y_train[known_mask])

    known_test = np.isin(y_test, classes)
    X_te = X_test[known_test]
    y_te_str = np.array([str(t) for t in y_test[known_test]])

    X_tr_r, y_tr_r = resample_training_fold(
        X_tr, y_tr_int, smote_cfg["k_neighbors"], smote_cfg["fallback_min_samples"], seed)

    params = dict(cfg["models"]["xgb"])
    params["num_class"] = len(classes)
    params["objective"] = "multi:softprob"
    params["random_state"] = seed
    model = XGBClassifier(**params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(X_tr_r, y_tr_r)

    y_pred_int = model.predict(X_te).astype(int)
    y_pred = le.inverse_transform(y_pred_int)

    acc = float((y_te_str == y_pred).mean())

    # Per-class F1
    f1_dict = {}
    for c in classes:
        tp = ((y_te_str == c) & (y_pred == c)).sum()
        fp = ((y_te_str != c) & (y_pred == c)).sum()
        fn = ((y_te_str == c) & (y_pred != c)).sum()
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_dict[c] = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    macro_f1 = float(np.mean(list(f1_dict.values())))

    # Hotel absorption rate: non-hotel test buildings predicted as hotel
    non_hotel_mask = y_te_str != "hotel"
    hotel_absorbed = int((y_pred[non_hotel_mask] == "hotel").sum())
    hotel_absorption_rate = hotel_absorbed / non_hotel_mask.sum() if non_hotel_mask.sum() else 0.0

    # Hotel recall (true hotel correctly predicted)
    hotel_mask = y_te_str == "hotel"
    hotel_recall = float((y_pred[hotel_mask] == "hotel").sum() / hotel_mask.sum()) if hotel_mask.sum() else np.nan

    return {
        "acc": acc,
        "macro_f1": macro_f1,
        "f1_per_class": f1_dict,
        "hotel_absorbed_n": hotel_absorbed,
        "hotel_absorption_rate": hotel_absorption_rate,
        "hotel_recall": hotel_recall,
        "n_test": len(y_te_str),
        "n_correct": int((y_te_str == y_pred).sum()),
        "y_pred": y_pred,
        "y_te_str": y_te_str,
    }


# ── Experiment definitions ─────────────────────────────────────────────────────
EXPERIMENTS = [
    dict(
        name="D1: T1 + T2/T3 cap=200",
        caps={"residential_mid_rise": 200, "residential_high_rise": 200,
              "education": 200, "hotel": 200, "sports": 200},
        include_hotel=True, include_sports=True,
    ),
    dict(
        name="D2: T1 + T2/T3 cap=50",
        caps={"residential_mid_rise": 50, "residential_high_rise": 50,
              "education": 50, "hotel": 50, "sports": 50},
        include_hotel=True, include_sports=True,
    ),
    dict(
        name="D3: T1 + T2 only (cap=200, no T3)",
        caps={"residential_mid_rise": 200, "residential_high_rise": 200,
              "education": 200},
        include_hotel=False, include_sports=False,
    ),
    dict(
        name="D4: T1 + T2 only (cap=50, no T3)",
        caps={"residential_mid_rise": 50, "residential_high_rise": 50,
              "education": 50},
        include_hotel=False, include_sports=False,
    ),
]


def print_section(title):
    print(f"\n{'='*72}")
    print(f"  {title}")
    print(f"{'='*72}")


def run_all(data_dir: Path, cfg: dict) -> None:
    seed = cfg["seed"]
    metric_epsg = cfg["metric_epsg"]
    match_dist = cfg["truth"]["match_max_distance_m"]

    # ── Load master ────────────────────────────────────────────────────────────
    _log("Loading master.gpkg...")
    master_path = data_dir / "module_a_master.gpkg"
    euluc_path  = data_dir / "euluc_shanghai_2022.gpkg"
    shp26_path  = data_dir / "2026 Building" / "2026 Building.shp"

    master = F.load_master(master_path)
    _log(f"  master: {len(master):,} buildings")

    master_attr = pyogrio.read_dataframe(master_path, read_geometry=False)
    rep_pts = master.geometry.representative_point()
    master_attr["centroid_lat"] = rep_pts.y.to_numpy()
    master_attr["centroid_lon"] = rep_pts.x.to_numpy()

    # ── Ground truth ───────────────────────────────────────────────────────────
    _log("Loading ground truth & splitting...")
    gt = load_ground_truth(cfg)
    train_gt, test_gt = split_train_test(gt, cfg)
    train_gt = match_to_master(train_gt, master, match_dist, metric_epsg)
    test_gt  = match_to_master(test_gt,  master, match_dist, metric_epsg)

    # ── Features (computed once) ───────────────────────────────────────────────
    _log("Computing features (once, ~2 min)...")
    X_df, _ = compute_all_features(master, euluc_path, shp26_path, cfg)

    # ── Test arrays (fixed across all experiments) ────────────────────────────
    X_test, y_test = make_test_arrays(test_gt, master_attr, X_df)

    # Determine full class list from T1 gold
    all_labels = set(train_gt["archetype"].dropna()) | set(test_gt["archetype"].dropna())
    all_labels.discard("unclear")
    classes = sorted(all_labels)

    # ── Run experiments ────────────────────────────────────────────────────────
    results = {}
    for exp in EXPERIMENTS:
        _log(f"\nRunning {exp['name']}...")
        tier23 = build_capped_tier23(
            master_attr, exp["caps"], exp["include_hotel"], exp["include_sports"], seed)

        # Log counts
        t2_counts = tier23[tier23["tier"] == 2]["archetype"].value_counts().to_dict()
        t3_counts = tier23[tier23["tier"] == 3]["archetype"].value_counts().to_dict()
        total_train = len(tier23) + len(train_gt[train_gt["master_idx"].notna()])
        _log(f"  T2: {t2_counts}  T3: {t3_counts}  total_train≈{total_train:,}")

        X_train, y_train = make_train_arrays(train_gt, tier23, master_attr, X_df)
        res = run_xgb(X_train, y_train, X_test, y_test, classes, cfg)
        res["tier23_counts"] = {**t2_counts, **t3_counts}
        results[exp["name"]] = res
        _log(f"  → acc={res['acc']:.4f}  macro_f1={res['macro_f1']:.4f}  "
             f"hotel_absorption={res['hotel_absorption_rate']:.3f}")

    # ── Side-by-side summary ───────────────────────────────────────────────────
    print_section("SUMMARY — D1 through D4 side-by-side")

    exp_names = [e["name"] for e in EXPERIMENTS]
    col_w = 22

    # Header
    print(f"\n{'Metric':<28}" + "".join(f"{n[:col_w]:>{col_w}}" for n in exp_names))
    print("-" * (28 + col_w * len(exp_names)))

    def row(label, vals, fmt=".4f"):
        print(f"  {label:<26}" + "".join(f"{v:>{col_w}{fmt}}" for v in vals))

    acc_vals    = [results[n]["acc"] for n in exp_names]
    f1_vals     = [results[n]["macro_f1"] for n in exp_names]
    hab_vals    = [results[n]["hotel_absorption_rate"] for n in exp_names]
    hrecall     = [results[n]["hotel_recall"] for n in exp_names]
    corr_vals   = [results[n]["n_correct"] for n in exp_names]
    total_tests = results[exp_names[0]]["n_test"]

    row("Test accuracy", acc_vals)
    row("Macro-F1", f1_vals)
    row("Hotel absorption rate*", hab_vals)
    row("Hotel recall", hrecall)
    print(f"  {'Correct / total':<26}" +
          "".join(f"{'%d/%d' % (c, total_tests):>{col_w}}" for c in corr_vals))

    print(f"\n  * hotel absorption = (non-hotel buildings predicted as hotel) / (non-hotel test n={int((np.array([str(t) for t in y_test]) != 'hotel').sum())})")

    # Per-class F1 block
    print_section("Per-class F1 across experiments")
    print(f"\n{'Class':<28}" + "".join(f"{n[:col_w]:>{col_w}}" for n in exp_names))
    print("-" * (28 + col_w * len(exp_names)))
    for cls in classes:
        vals = [results[n]["f1_per_class"].get(cls, 0.0) for n in exp_names]
        print(f"  {cls:<26}" + "".join(f"{v:>{col_w}.3f}" for v in vals))

    # Training set size breakdown
    print_section("Training set composition (T1 + T2 + T3) per experiment")
    print(f"\n{'Archetype':<28}" + "".join(f"{n[:col_w]:>{col_w}}" for n in exp_names))
    print("-" * (28 + col_w * len(exp_names)))
    all_t23_archs = set()
    for n in exp_names:
        all_t23_archs.update(results[n]["tier23_counts"].keys())
    for arch in sorted(all_t23_archs):
        vals = [results[n]["tier23_counts"].get(arch, 0) for n in exp_names]
        print(f"  {arch:<26}" + "".join(f"{v:>{col_w}d}" for v in vals))

    # T1 gold counts (same across all)
    t1_counts = train_gt["archetype"].value_counts().to_dict()
    print(f"\n  T1 gold (same in all experiments):")
    for arch in sorted(t1_counts):
        print(f"    {arch:<30} {t1_counts[arch]:>4}")

    print("\n" + "=" * 72)
    print("  Experiments complete.")
    print("=" * 72 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    cfg = load_config()
    run_all(args.data_dir, cfg)


if __name__ == "__main__":
    main()
