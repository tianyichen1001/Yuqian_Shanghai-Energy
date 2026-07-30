"""B2 正式 RF 模型训练 + 全量预测。

工作令 2026-07-30:
  1) 训练真值 = B2 人工标注 95 栋 + validation 156 中可用部分
     （剔除弱标签 mall/mixed_use），bid 去重；
  2) 序号 69（bid 597565）"shopping_mall+residential" → mixed_use；
  3) 特征 = 几何 + floors/height/ep + EULUC class（零 POI）；
  4) RF 超参对齐 Yuqian：n_estimators=500, max_depth=20,
     min_samples_split=10, min_samples_leaf=4；
  5) GroupKFold 空间 CV；报告 accuracy / per-class F1 / confusion matrix；
  6) 如准确率显著超过 B1 基线 54.4%，全量预测 unknown 建筑。

运行:
  python scripts/b2_rf_training.py --data-dir ~/b2_data \
      --b2-xlsx <上传的 UBEM 标注工作簿路径>
输入（--data-dir 下，不入 git）:
  module_a_master.gpkg / euluc_shanghai_2022.gpkg / "2026 Building/2026 Building.shp"
产出:
  data/reference/b2_*.csv（汇总，commit）
  <out-dir>/b2_citywide_predictions.parquet + b2_model.joblib（不 commit）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.ml import features as F  # noqa: E402

REF_DIR = PROJECT_ROOT / "data" / "reference"
VAL_DIR = PROJECT_ROOT / "data" / "raw" / "validation"
VAL_CSV = VAL_DIR / "shanghai_validation_set_v0.csv"
CFG_PATH = PROJECT_ROOT / "config" / "b2_rf_training.yaml"

WEAK_LABEL_ARCHETYPES = {"shopping_mall", "mixed_use"}
B1_BASELINE_ACC = 54.4


def _log(msg: str) -> None:
    print(f"[b2] {msg}", flush=True)


def parse_b2_annotations(xlsx_path: Path) -> pd.DataFrame:
    """Extract 95 valid B2 human annotations from the uploaded workbook."""
    df = pd.read_excel(xlsx_path, sheet_name="B2标注119栋")
    actual_col = "建筑类型(填英文)"
    floors_col = "你看到几层"

    valid = df[df[actual_col].notna() & (df[actual_col] != "unclear")].copy()
    valid.loc[valid[actual_col] == "shopping_mall+residential", actual_col] = "mixed_use"

    out = pd.DataFrame({
        "bid": valid["bid"].astype(int).to_numpy(),
        "truth_class": valid[actual_col].to_numpy(),
        "observed_floors": pd.to_numeric(valid[floors_col], errors="coerce").to_numpy(),
        "source": "b2_annotation",
    })
    return out.reset_index(drop=True)


def match_validation_to_master(g: gpd.GeoDataFrame, cfg: dict) -> pd.DataFrame:
    """Match validation set to master buildings, return with bids."""
    val = pd.read_csv(VAL_CSV)
    val = val[val.status == "annotated"].copy()
    pts = gpd.GeoDataFrame(val, geometry=gpd.points_from_xy(val.lon, val.lat), crs=4326)
    gm = gpd.GeoDataFrame({"row": np.arange(len(g))}, geometry=g.geometry, crs=g.crs)

    maxd = cfg["truth"]["match_max_distance_m"]
    w = gpd.sjoin(pts, gm, predicate="within", how="left")
    w = w[~w.index.duplicated(keep="first")]
    miss = w.index[w["row"].isna()]
    if len(miss):
        nn = gpd.sjoin_nearest(pts.loc[miss].to_crs(cfg["metric_epsg"]),
                               gm.to_crs(cfg["metric_epsg"]),
                               max_distance=maxd, how="left")
        nn = nn[~nn.index.duplicated(keep="first")]
        w.loc[miss, "row"] = nn["row"]
    val["row"] = w["row"].to_numpy()
    matched = val[val.row.notna()].copy()
    matched["row"] = matched["row"].astype(int)
    matched["bid"] = g["bid"].iloc[matched["row"]].to_numpy()

    _log(f"Validation → master: {len(matched)}/{len(val)} matched")
    return matched


def build_training_labels(g: gpd.GeoDataFrame, b2: pd.DataFrame,
                          val_matched: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Combine B2 annotations + validation (minus weak labels), dedup by bid."""
    val_clean = val_matched[~val_matched["archetype"].isin(WEAK_LABEL_ARCHETYPES)].copy()
    val_clean = val_clean[val_clean["archetype"] != "unclear"]
    _log(f"Validation after removing weak labels ({', '.join(sorted(WEAK_LABEL_ARCHETYPES))}): "
         f"{len(val_clean)}/{len(val_matched)}")

    val_labels = pd.DataFrame({
        "bid": val_clean["bid"].astype(int).to_numpy(),
        "truth_class": val_clean["archetype"].to_numpy(),
        "observed_floors": pd.to_numeric(val_clean["floors_observed"],
                                         errors="coerce").to_numpy(),
        "source": "validation_v0",
    })

    combined = pd.concat([b2, val_labels], ignore_index=True)
    combined = combined.drop_duplicates(subset="bid", keep="first")

    bid_to_row = dict(zip(g["bid"].to_numpy(), np.arange(len(g))))
    combined["row"] = combined["bid"].map(bid_to_row)
    valid = combined[combined["row"].notna()].copy()
    valid["row"] = valid["row"].astype(int)

    if len(valid) < len(combined):
        _log(f"WARNING: {len(combined) - len(valid)} bids not found in master")

    _log(f"Training label pool: {len(valid)} buildings")
    _log("Class distribution:")
    cls_n = valid["truth_class"].value_counts()
    for c, n in cls_n.items():
        _log(f"  {c:25s} {n:4d}")
    _log(f"Source breakdown: {valid['source'].value_counts().to_dict()}")

    return valid


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--b2-xlsx", type=Path, required=True,
                    help="UBEM_标注工作簿_B0_B2.xlsx path")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    out_dir = args.out_dir or args.data_dir / "b2_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(open(CFG_PATH))
    seed = cfg["seed"]
    rng = np.random.default_rng(seed)
    epsg = cfg["metric_epsg"]

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (classification_report, confusion_matrix,
                                 precision_recall_fscore_support)
    from sklearn.model_selection import GroupKFold

    # ---- 1. Load + features ---------------------------------------------------
    _log("Loading master…")
    g = F.load_master(args.data_dir / "module_a_master.gpkg")
    F.attach_vendor_fields(g, args.data_dir / "2026 Building" / "2026 Building.shp")
    _log(f"Master: {len(g):,} buildings")
    gm = F.shape_features(g, epsg, cfg["features"]["aspect_ratio_min_side_m"])
    F.scale_features(g)
    _log(f"Neighborhood features (r={cfg['features']['neighborhood_radius_m']}m)…")
    xy = F.neighborhood_features(g, gm, cfg["features"]["neighborhood_radius_m"],
                                 cfg["features"]["no_neighbor_fill"])
    del gm
    _log("Parcel features…")
    F.parcel_features(g, args.data_dir / "euluc_shanghai_2022.gpkg", epsg)
    X = F.build_feature_matrix(g)
    _log(f"Feature matrix: {X.shape[0]:,} × {X.shape[1]}")

    # ---- 2. Training labels ----------------------------------------------------
    _log("Parsing B2 annotations…")
    b2 = parse_b2_annotations(args.b2_xlsx)
    _log(f"B2 valid annotations: {len(b2)}")
    _log(f"  B2 class dist: {b2['truth_class'].value_counts().to_dict()}")

    val_matched = match_validation_to_master(g, cfg)
    labels = build_training_labels(g, b2, val_matched, cfg)

    # ---- 3. Spatial CV (GroupKFold) -------------------------------------------
    rows_tr = labels["row"].to_numpy()
    y_tr = labels["truth_class"].to_numpy()
    X_tr = X.iloc[rows_tr].to_numpy()

    grid = cfg["cv"]["grid_size_m"]
    cells = (np.floor(xy[rows_tr, 0] / grid).astype(int) * 100000
             + np.floor(xy[rows_tr, 1] / grid).astype(int))
    n_splits = cfg["cv"]["n_splits"]
    _log(f"Spatial CV: {len(np.unique(cells))} grid cells, "
         f"{n_splits}-fold GroupKFold")

    rf_kw = dict(
        n_estimators=cfg["model"]["n_estimators"],
        max_depth=cfg["model"].get("max_depth"),
        min_samples_leaf=cfg["model"].get("min_samples_leaf", 1),
        random_state=seed,
        n_jobs=-1,
    )
    if cfg["model"].get("min_samples_split"):
        rf_kw["min_samples_split"] = cfg["model"]["min_samples_split"]
    if cfg["model"].get("class_weight"):
        rf_kw["class_weight"] = cfg["model"]["class_weight"]
    oof = np.empty(len(labels), dtype=object)
    fold_accs = []
    for k, (itr, ite) in enumerate(GroupKFold(n_splits).split(X_tr, y_tr, cells)):
        m = RandomForestClassifier(**rf_kw).fit(X_tr[itr], y_tr[itr])
        preds = m.predict(X_tr[ite])
        oof[ite] = preds
        acc_k = float((preds == y_tr[ite]).mean())
        fold_accs.append(acc_k)
        _log(f"  fold {k}: test={len(ite)}, acc={acc_k:.3f}")

    oof_acc = float((oof == y_tr).mean())
    _log(f"\nOOF accuracy: {oof_acc:.1%} (B1 baseline: {B1_BASELINE_ACC}%)")
    _log(f"Mean fold accuracy: {np.mean(fold_accs):.1%}")

    # ---- 4. Per-class metrics + confusion matrix ------------------------------
    classes = sorted(labels["truth_class"].unique())
    p, r, f1, sup = precision_recall_fscore_support(y_tr, oof, labels=classes,
                                                     zero_division=0)
    per_class = pd.DataFrame({
        "class": classes,
        "n_truth": sup.astype(int),
        "precision": p.round(3),
        "recall": r.round(3),
        "f1": f1.round(3),
    })
    _log("\nPer-class metrics (OOF):")
    _log(per_class.to_string(index=False))

    cm = confusion_matrix(y_tr, oof, labels=classes)
    cm_df = pd.DataFrame(cm, index=pd.Index(classes, name="truth"), columns=classes)
    _log("\nConfusion matrix:")
    _log(cm_df.to_string())

    # ---- 5. Final model -------------------------------------------------------
    _log("\nTraining final model on all labeled data…")
    model = RandomForestClassifier(**rf_kw).fit(X_tr, y_tr)
    import joblib
    joblib.dump(model, out_dir / "b2_model.joblib")

    # Feature importance
    imp = pd.DataFrame({"feature": X.columns, "importance": model.feature_importances_})
    imp = imp.sort_values("importance", ascending=False).reset_index(drop=True)
    imp["rank"] = imp.index + 1
    imp["importance"] = imp["importance"].round(5)
    _log("\nTop 15 features:")
    _log(imp.head(15).to_string(index=False))

    # ---- 6. Accuracy gate check -----------------------------------------------
    if oof_acc * 100 <= B1_BASELINE_ACC:
        _log(f"\n⚠ OOF accuracy {oof_acc:.1%} did NOT exceed B1 baseline {B1_BASELINE_ACC}%.")
        _log("Stopping before full prediction. Report to owner.")
        _save_reports(per_class, cm_df, imp, oof_acc, labels, cfg, out_dir)
        return

    _log(f"\n✓ OOF accuracy {oof_acc:.1%} exceeds B1 baseline {B1_BASELINE_ACC}%. "
         f"Proceeding with full prediction.")

    # ---- 7. Full prediction on unknown buildings ------------------------------
    unknown_mask = g["archetype"].to_numpy() == "unknown"
    n_unknown = int(unknown_mask.sum())
    _log(f"\nPredicting {n_unknown:,} unknown buildings…")
    X_unk = X.iloc[np.flatnonzero(unknown_mask)].to_numpy()
    proba = model.predict_proba(X_unk)
    pred_classes = model.classes_[np.argmax(proba, axis=1)]
    pred_conf = proba.max(axis=1)

    g.loc[unknown_mask, "pred_class"] = pred_classes
    g.loc[unknown_mask, "pred_probability"] = pred_conf

    _log("\nPrediction distribution (unknown buildings):")
    pred_dist = pd.Series(pred_classes).value_counts()
    for c, n in pred_dist.items():
        _log(f"  {c:25s} {n:7,d}  ({100 * n / len(pred_classes):.1f}%)")
    _log(f"\nConfidence stats: mean={pred_conf.mean():.3f}, "
         f"median={np.median(pred_conf):.3f}, "
         f"p10={np.percentile(pred_conf, 10):.3f}, "
         f"p90={np.percentile(pred_conf, 90):.3f}")

    pred_out = g.loc[unknown_mask, ["bid"]].copy()
    pred_out["pred_class"] = pred_classes
    pred_out["pred_probability"] = np.round(pred_conf, 4)
    pred_out.to_parquet(out_dir / "b2_citywide_predictions.parquet", index=False)
    _log(f"Predictions saved to {out_dir / 'b2_citywide_predictions.parquet'}")

    # ---- 8. Save reports ------------------------------------------------------
    _save_reports(per_class, cm_df, imp, oof_acc, labels, cfg, out_dir)
    _log("Done.")


def _save_reports(per_class: pd.DataFrame, cm_df: pd.DataFrame,
                  imp: pd.DataFrame, oof_acc: float,
                  labels: pd.DataFrame, cfg: dict, out_dir: Path) -> None:
    REF_DIR.mkdir(parents=True, exist_ok=True)

    metrics = pd.DataFrame([{
        "metric": "oof_accuracy",
        "value": round(oof_acc * 100, 1),
        "n": len(labels),
        "note": f"B1 baseline = {B1_BASELINE_ACC}%",
    }])
    metrics.to_csv(REF_DIR / "b2_metrics.csv", index=False)
    per_class.to_csv(REF_DIR / "b2_per_class_metrics.csv", index=False)
    cm_df.to_csv(REF_DIR / "b2_confusion_matrix.csv")
    imp.to_csv(REF_DIR / "b2_feature_importance.csv", index=False)

    label_summary = labels.groupby("truth_class").agg(
        n=("bid", "count"),
        n_b2=("source", lambda x: (x == "b2_annotation").sum()),
        n_val=("source", lambda x: (x == "validation_v0").sum()),
    ).reset_index()
    label_summary.to_csv(REF_DIR / "b2_training_label_summary.csv", index=False)

    _log(f"Reports saved to {REF_DIR / 'b2_*.csv'}")


if __name__ == "__main__":
    main()
