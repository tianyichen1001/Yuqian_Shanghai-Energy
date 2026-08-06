"""ML classification on 315 merged ground-truth buildings.
Two experiments:
  A) Non-residential only (excl residential + education)
  B) Full 11-class (all archetypes, single-stage baseline)
"""
import pandas as pd
import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report,
    confusion_matrix,
)
from xgboost import XGBClassifier
from catboost import CatBoostClassifier
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
ROOT = str(Path(__file__).resolve().parent.parent)
OUTFIG = f"{ROOT}/outputs/figures"
OUTTAB = f"{ROOT}/outputs/tables"

# ═══════════════════════════════════════════════════════════════════
# 1. LOAD AND MERGE ALL THREE SOURCES
# ═══════════════════════════════════════════════════════════════════
print("Loading master.gpkg...")
master = gpd.read_file(f"{ROOT}/data/interim/module_a_master.gpkg")
master_proj = master.to_crs(epsg=4547)
centroids = master_proj.geometry.centroid
tree = cKDTree(np.column_stack([centroids.x.values, centroids.y.values]))

# -- Source 1: v0 validation (156 annotated) --
v0 = pd.read_csv(f"{ROOT}/data/raw/validation/shanghai_validation_set_v0.csv")
v0_ann = v0[v0["status"] == "annotated"].copy()
v0_ann = v0_ann[v0_ann["archetype"] != "unclear"].copy()
print(f"v0: {len(v0_ann)} (after removing unclear)")

# Spatial match v0 to master
v0_gdf = gpd.GeoDataFrame(
    v0_ann,
    geometry=gpd.points_from_xy(v0_ann["lon"], v0_ann["lat"]),
    crs="EPSG:4326",
).to_crs(epsg=4547)
v0_dists, v0_idxs = tree.query(
    np.column_stack([v0_gdf.geometry.x.values, v0_gdf.geometry.y.values]), k=1
)
v0_matched = master_proj.iloc[v0_idxs].copy().reset_index(drop=True)
v0_matched["gt_archetype"] = v0_ann["archetype"].values
v0_matched["master_idx"] = v0_idxs
v0_matched["source"] = "v0"
v0_matched["source_id"] = v0_ann["val_id"].values

# -- Source 2: B2 annotation (119 rows, 101 annotated) --
b2 = pd.read_excel(
    f"{ROOT}/data/raw/validation/UBEM_标注工作簿_B0_B2.xlsx",
    sheet_name="B2标注119栋"
)
b2_col = "建筑类型(填英文)"
b2_ann = b2[b2[b2_col].apply(lambda x: pd.notna(x) and str(x).strip() != "")].copy()
b2_ann = b2_ann[~b2_ann[b2_col].isin(["unclear"])].copy()
# Handle compound labels
b2_ann = b2_ann[~b2_ann[b2_col].str.contains(r"\+", na=False)].copy()
print(f"B2: {len(b2_ann)} (after removing unclear + compound)")

# B2 has bid (master index) — use directly
b2_master_idxs = b2_ann["bid"].values.astype(int)
b2_matched = master_proj.iloc[b2_master_idxs].copy().reset_index(drop=True)
b2_matched["gt_archetype"] = b2_ann[b2_col].values
b2_matched["master_idx"] = b2_master_idxs
b2_matched["source"] = "b2"
b2_matched["source_id"] = b2_ann["序号"].values

# -- Source 3: Smallclass verification (100 rows, 73 annotated) --
sc = pd.read_excel(
    f"{ROOT}/data/raw/validation/smallclass_verification_20260803.xlsx",
    sheet_name="verify"
)
sc_ann = sc[sc["your_archetype"].apply(lambda x: pd.notna(x) and str(x).strip() != "")].copy()
sc_ann = sc_ann[~sc_ann["your_archetype"].isin(["unclear"])].copy()

# Normalize archetype names
archetype_normalize = {
    "government office": "government_office",
    "residential_mid_rise": "residential",
    "residential_high_rise": "residential",
    "mixed-use": "mixed_use",
}
sc_ann["your_archetype"] = sc_ann["your_archetype"].map(
    lambda x: archetype_normalize.get(x, x)
)
print(f"Smallclass: {len(sc_ann)} (after removing unclear)")

# Spatial match smallclass to master
sc_gdf = gpd.GeoDataFrame(
    sc_ann,
    geometry=gpd.points_from_xy(sc_ann["lon"], sc_ann["lat"]),
    crs="EPSG:4326",
).to_crs(epsg=4547)
sc_dists, sc_idxs = tree.query(
    np.column_stack([sc_gdf.geometry.x.values, sc_gdf.geometry.y.values]), k=1
)
sc_matched = master_proj.iloc[sc_idxs].copy().reset_index(drop=True)
sc_matched["gt_archetype"] = sc_ann["your_archetype"].values
sc_matched["master_idx"] = sc_idxs
sc_matched["source"] = "smallclass"
sc_matched["source_id"] = sc_ann["seq"].values

# -- Merge and deduplicate --
keep_cols = list(master_proj.columns) + ["gt_archetype", "master_idx", "source", "source_id"]
all_matched = pd.concat([
    v0_matched[keep_cols],
    b2_matched[keep_cols],
    sc_matched[keep_cols],
], ignore_index=True)

# Deduplicate by master_idx (keep first = v0 priority)
before_dedup = len(all_matched)
all_matched = all_matched.drop_duplicates(subset=["master_idx"], keep="first")
print(f"\nMerged: {before_dedup} → {len(all_matched)} after dedup by master_idx")
print(f"\nArchetype distribution (all {len(all_matched)}):")
print(all_matched["gt_archetype"].value_counts().to_string())

# ═══════════════════════════════════════════════════════════════════
# 2. COMPUTE FEATURES
# ═══════════════════════════════════════════════════════════════════
all_matched["building_footprint"] = all_matched.geometry.area
all_matched["perimeter"] = all_matched.geometry.length
all_matched["gross_floor_area"] = all_matched["building_footprint"] * all_matched["floors"]

mrr = all_matched.geometry.minimum_rotated_rectangle()
def aspect(r):
    b = r.bounds
    dx, dy = b[2]-b[0], b[3]-b[1]
    return max(dx,dy) / max(min(dx,dy), 0.01)
all_matched["aspect_ratio"] = mrr.apply(aspect)
all_matched["compactness_ratio"] = 4 * np.pi * all_matched["building_footprint"] / (all_matched["perimeter"]**2)
all_matched["convexity_ratio"] = all_matched["building_footprint"] / all_matched.geometry.convex_hull.area

# Get ep from raw Taobao
print("\nLoading raw Taobao 2026 for ep field...")
import subprocess, os
taobao_shp = "/tmp/taobao_2026/2026 Building/2026 Building.shp"
if not os.path.exists(taobao_shp):
    data_repo = "/home/user/Yuqian_Shanghai-Energy-data"
    subprocess.run(["unzip", "-o", f"{data_repo}/shanghai_2026_building.zip",
                    "-d", "/tmp/taobao_2026/"], capture_output=True)
taobao = gpd.read_file(taobao_shp)
taobao_proj = taobao.to_crs(epsg=4547)
taobao_centroids = taobao_proj.geometry.centroid
taobao_tree = cKDTree(np.column_stack([taobao_centroids.x.values, taobao_centroids.y.values]))

match_centroids = all_matched.geometry.centroid
ep_dists, ep_idxs = taobao_tree.query(
    np.column_stack([match_centroids.x.values, match_centroids.y.values]), k=1
)
all_matched["ep"] = taobao["ep"].iloc[ep_idxs].values
print(f"ep matched within 50m: {(ep_dists < 50).sum()}/{len(all_matched)}")

# Clean up taobao memory
del taobao, taobao_proj, taobao_centroids, taobao_tree

SHAPE_COLS = [
    "building_footprint", "gross_floor_area", "height", "floors",
    "perimeter", "aspect_ratio", "compactness_ratio", "convexity_ratio",
]
all_matched["euluc_class_enc"] = all_matched["euluc_class"].fillna(-1).astype(int)
FEAT_COLS = SHAPE_COLS + ["euluc_class_enc", "ep"]

feat_all = all_matched.dropna(subset=SHAPE_COLS).copy()
print(f"\nAfter dropping NaN shape features: {len(feat_all)} buildings")
print(f"Source breakdown: {feat_all['source'].value_counts().to_string()}")

# ═══════════════════════════════════════════════════════════════════
# 3. EXPERIMENT A: NON-RESIDENTIAL ONLY
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("EXPERIMENT A: NON-RESIDENTIAL (excl. residential + education)")
print(f"{'='*80}")

EXCLUDE_A = ["residential", "education"]
nonres = feat_all[~feat_all["gt_archetype"].isin(EXCLUDE_A)].copy()
print(f"Non-residential buildings: {len(nonres)}")
print(f"Class distribution:\n{nonres['gt_archetype'].value_counts().to_string()}")

X_a = nonres[FEAT_COLS].values
y_a = nonres["gt_archetype"].values
classes_a = sorted(set(y_a))

X_train_a, X_test_a, y_train_a, y_test_a = train_test_split(
    X_a, y_a, test_size=0.3, random_state=42, stratify=y_a
)

print(f"\nTrain: {len(X_train_a)}, Test: {len(X_test_a)}")
print("\nPer-class distribution:")
train_vc = dict(zip(*np.unique(y_train_a, return_counts=True)))
test_vc = dict(zip(*np.unique(y_test_a, return_counts=True)))
print(f"  {'Class':25s} {'Train':>6s} {'Test':>6s} {'Total':>6s}")
for c in classes_a:
    tr = train_vc.get(c, 0)
    te = test_vc.get(c, 0)
    print(f"  {c:25s} {tr:6d} {te:6d} {tr+te:6d}")


def run_models(X_train, X_test, y_train, y_test, all_classes, label):
    le = LabelEncoder()
    le.fit(y_train)
    y_train_enc = le.transform(y_train)
    y_test_enc = le.transform(y_test)

    models = {
        "RandomForest": RandomForestClassifier(
            n_estimators=300, random_state=42, class_weight="balanced",
            max_depth=None, min_samples_leaf=1
        ),
        "XGBoost": XGBClassifier(
            n_estimators=300, random_state=42, max_depth=6,
            learning_rate=0.1, eval_metric="mlogloss",
            use_label_encoder=False, verbosity=0,
        ),
        "CatBoost": CatBoostClassifier(
            iterations=300, random_seed=42, depth=6,
            learning_rate=0.1, verbose=0, auto_class_weights="Balanced",
        ),
    }

    results = {}
    for name, model in models.items():
        print(f"\n--- {name} ---")
        if name in ("XGBoost", "CatBoost"):
            model.fit(X_train, y_train_enc)
            y_pred_enc = model.predict(X_test)
            if name == "CatBoost":
                y_pred_enc = y_pred_enc.flatten().astype(int)
            y_pred = le.inverse_transform(y_pred_enc)
            y_pred_train_enc = model.predict(X_train)
            if name == "CatBoost":
                y_pred_train_enc = y_pred_train_enc.flatten().astype(int)
            y_pred_train = le.inverse_transform(y_pred_train_enc)
        else:
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            y_pred_train = model.predict(X_train)

        importances = model.feature_importances_
        acc = accuracy_score(y_test, y_pred)
        macro_f1 = f1_score(y_test, y_pred, average="macro", zero_division=0)
        train_acc = accuracy_score(y_train, y_pred_train)

        print(f"  Train accuracy: {train_acc:.3f}")
        print(f"  Test accuracy:  {acc:.3f}")
        print(f"  Macro-F1:       {macro_f1:.3f}")

        print(f"\n  Classification report:")
        report = classification_report(y_test, y_pred, zero_division=0, digits=3)
        for line in report.split("\n"):
            print(f"    {line}")

        cm = confusion_matrix(y_test, y_pred, labels=all_classes)
        print(f"\n  Confusion matrix (rows=true, cols=pred):")
        print(f"    {'':25s} " + " ".join(f"{c[:7]:>7s}" for c in all_classes))
        for i, c in enumerate(all_classes):
            print(f"    {c:25s} " + " ".join(f"{cm[i,j]:7d}" for j in range(len(all_classes))))

        feat_imp = sorted(zip(FEAT_COLS, importances), key=lambda x: -x[1])
        print(f"\n  Feature importance (top 10):")
        for rank, (fname, imp) in enumerate(feat_imp[:10], 1):
            bar = "#" * int(imp * 100)
            print(f"    {rank:2d}. {fname:25s} {imp:.4f}  {bar}")

        results[name] = {
            "accuracy": acc,
            "macro_f1": macro_f1,
            "train_accuracy": train_acc,
            "y_pred": y_pred,
            "importances": importances,
            "confusion_matrix": cm,
        }

    return results


results_a = run_models(X_train_a, X_test_a, y_train_a, y_test_a, classes_a, "non-res")

print(f"\n{'='*60}")
print("EXPERIMENT A SUMMARY")
print(f"{'='*60}")
print(f"  {'Model':15s} {'Train Acc':>10s} {'Test Acc':>10s} {'Macro-F1':>10s}")
for name in results_a:
    r = results_a[name]
    print(f"  {name:15s} {r['train_accuracy']:10.3f} {r['accuracy']:10.3f} {r['macro_f1']:10.3f}")


# ═══════════════════════════════════════════════════════════════════
# 4. EXPERIMENT B: FULL 11-CLASS
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("EXPERIMENT B: FULL (all classes, single-stage baseline)")
print(f"{'='*80}")

X_b = feat_all[FEAT_COLS].values
y_b = feat_all["gt_archetype"].values
classes_b = sorted(set(y_b))
print(f"Total buildings: {len(X_b)}")
print(f"Classes ({len(classes_b)}): {classes_b}")
print(f"Class distribution:\n{feat_all['gt_archetype'].value_counts().to_string()}")

X_train_b, X_test_b, y_train_b, y_test_b = train_test_split(
    X_b, y_b, test_size=0.3, random_state=42, stratify=y_b
)

print(f"\nTrain: {len(X_train_b)}, Test: {len(X_test_b)}")
print("\nPer-class distribution:")
train_vc = dict(zip(*np.unique(y_train_b, return_counts=True)))
test_vc = dict(zip(*np.unique(y_test_b, return_counts=True)))
print(f"  {'Class':25s} {'Train':>6s} {'Test':>6s} {'Total':>6s}")
for c in classes_b:
    tr = train_vc.get(c, 0)
    te = test_vc.get(c, 0)
    print(f"  {c:25s} {tr:6d} {te:6d} {tr+te:6d}")

results_b = run_models(X_train_b, X_test_b, y_train_b, y_test_b, classes_b, "full")

print(f"\n{'='*60}")
print("EXPERIMENT B SUMMARY")
print(f"{'='*60}")
print(f"  {'Model':15s} {'Train Acc':>10s} {'Test Acc':>10s} {'Macro-F1':>10s}")
for name in results_b:
    r = results_b[name]
    print(f"  {name:15s} {r['train_accuracy']:10.3f} {r['accuracy']:10.3f} {r['macro_f1']:10.3f}")


# ═══════════════════════════════════════════════════════════════════
# 5. COMPARISON & FIGURES
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("TWO-STAGE vs SINGLE-STAGE COMPARISON")
print(f"{'='*80}")
print("""
Two-stage approach:
  Stage 1: EULUC rules assign residential + education (100% accuracy assumed)
  Stage 2: ML classifies remaining non-residential buildings

Single-stage: ML classifies all buildings directly
""")

# Estimate two-stage overall accuracy
# residential + education in test set B
n_res_edu_test = sum(1 for y in y_test_b if y in ["residential", "education"])
n_nonres_test = len(y_test_b) - n_res_edu_test
best_a = max(results_a.items(), key=lambda x: x[1]["macro_f1"])
best_b = max(results_b.items(), key=lambda x: x[1]["macro_f1"])

print(f"Best non-res model: {best_a[0]} (acc={best_a[1]['accuracy']:.3f}, F1={best_a[1]['macro_f1']:.3f})")
print(f"Best full model:    {best_b[0]} (acc={best_b[1]['accuracy']:.3f}, F1={best_b[1]['macro_f1']:.3f})")

# Two-stage estimated accuracy on full test set
# res+edu portion: 100% correct by rules
# non-res portion: best_a accuracy
two_stage_correct = n_res_edu_test + int(best_a[1]["accuracy"] * n_nonres_test)
two_stage_acc = two_stage_correct / len(y_test_b)
print(f"\nTwo-stage estimated overall accuracy: {two_stage_acc:.3f}")
print(f"  (residential+education in test: {n_res_edu_test}/{len(y_test_b)} = {n_res_edu_test/len(y_test_b):.1%} correct by rules)")
print(f"  (non-residential in test: {n_nonres_test}/{len(y_test_b)} at {best_a[1]['accuracy']:.3f} accuracy)")
print(f"Single-stage overall accuracy:       {best_b[1]['accuracy']:.3f}")

# ── FIGURES ──
# Confusion matrices for best models
fig, axes = plt.subplots(1, 2, figsize=(20, 8))

for ax, (title, results, classes) in zip(axes, [
    (f"Exp A: Non-Residential ({best_a[0]})", results_a[best_a[0]], classes_a),
    (f"Exp B: Full 11-Class ({best_b[0]})", results_b[best_b[0]], classes_b),
]):
    cm = results["confusion_matrix"]
    im = ax.imshow(cm, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(classes)))
    ax.set_xticklabels(classes, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(classes)))
    ax.set_yticklabels(classes, fontsize=8)
    for i in range(len(classes)):
        for j in range(len(classes)):
            v = cm[i, j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=8,
                    color="white" if v > cm.max()*0.5 else "black")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    r = results
    ax.set_title(f"{title}\nAcc={r['accuracy']:.3f}, F1={r['macro_f1']:.3f}", fontsize=11)
    plt.colorbar(im, ax=ax, shrink=0.8)

fig.suptitle(f"ML Classification on {len(feat_all)} Ground-Truth Buildings\n"
             "10 features, 70/30 stratified split, seed=42",
             fontsize=13, y=1.02)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/ml_315_confusion.png", dpi=150, bbox_inches="tight")
print(f"\nSaved confusion matrices to {OUTFIG}/ml_315_confusion.png")

# All 3 models confusion for experiment A
fig2, axes2 = plt.subplots(1, 3, figsize=(24, 7))
for ax, (name, r) in zip(axes2, results_a.items()):
    cm = r["confusion_matrix"]
    im = ax.imshow(cm, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(classes_a)))
    ax.set_xticklabels(classes_a, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(classes_a)))
    ax.set_yticklabels(classes_a, fontsize=8)
    for i in range(len(classes_a)):
        for j in range(len(classes_a)):
            v = cm[i, j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=8,
                    color="white" if v > cm.max()*0.5 else "black")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(f"{name}\nAcc={r['accuracy']:.3f}, F1={r['macro_f1']:.3f}", fontsize=11)
    plt.colorbar(im, ax=ax, shrink=0.8)
fig2.suptitle(f"Exp A: Non-Residential Classification ({len(nonres)} buildings, {len(classes_a)} classes)\n"
              "10 features, 70/30 split, seed=42", fontsize=13, y=1.02)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/ml_315_nonres_3models.png", dpi=150, bbox_inches="tight")
print(f"Saved non-res 3-model comparison to {OUTFIG}/ml_315_nonres_3models.png")

# Feature importance comparison (Exp A)
fig3, axes3 = plt.subplots(1, 3, figsize=(24, 8))
for ax, (name, r) in zip(axes3, results_a.items()):
    imp = r["importances"]
    sorted_idx = np.argsort(imp)[::-1]
    ax.barh(range(len(FEAT_COLS)), imp[sorted_idx], align="center")
    ax.set_yticks(range(len(FEAT_COLS)))
    ax.set_yticklabels([FEAT_COLS[i] for i in sorted_idx], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Importance")
    ax.set_title(f"{name}", fontsize=11)
fig3.suptitle("Feature Importance (Exp A: Non-Residential)", fontsize=13)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/ml_315_nonres_feat_imp.png", dpi=150, bbox_inches="tight")
print(f"Saved feature importance to {OUTFIG}/ml_315_nonres_feat_imp.png")

# Save merged ground truth table
gt_out = feat_all[["source", "source_id", "gt_archetype", "master_idx"] + FEAT_COLS].copy()
gt_out.to_csv(f"{OUTTAB}/ground_truth_315.csv", index=False)
print(f"\nSaved merged ground truth to {OUTTAB}/ground_truth_315.csv ({len(gt_out)} rows)")
