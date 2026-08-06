"""Task 3: ML classification experiment on non-residential buildings.
Exclude residential + education (solved by EULUC rules).
Train RF / XGBoost / CatBoost on remaining classes.
"""
import pandas as pd
import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from sklearn.preprocessing import StandardScaler, LabelEncoder
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
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

ROOT = str(Path(__file__).resolve().parent.parent)
OUTFIG = f"{ROOT}/outputs/figures"
OUTTAB = f"{ROOT}/outputs/tables"

# ── 1. Load master.gpkg and build spatial index ──
print("Loading master.gpkg...")
master = gpd.read_file(f"{ROOT}/data/interim/module_a_master.gpkg")
master_proj = master.to_crs(epsg=4547)
centroids = master_proj.geometry.centroid
tree = cKDTree(np.column_stack([centroids.x.values, centroids.y.values]))
print(f"Master: {len(master)} buildings")

# ── 2. Load validation set and spatial match ──
val = pd.read_csv(f"{ROOT}/data/raw/validation/shanghai_validation_set_v0.csv")
val_ann = val[val["status"] == "annotated"].copy()
print(f"Annotated validation: {len(val_ann)}")

val_gdf = gpd.GeoDataFrame(
    val_ann,
    geometry=gpd.points_from_xy(val_ann["lon"], val_ann["lat"]),
    crs="EPSG:4326",
).to_crs(epsg=4547)
dists, idxs = tree.query(
    np.column_stack([val_gdf.geometry.x.values, val_gdf.geometry.y.values]), k=1
)

matched = master_proj.iloc[idxs].copy().reset_index(drop=True)
matched["val_id"] = val_ann["val_id"].values
matched["gt_archetype"] = val_ann["archetype"].values
matched["match_dist_m"] = dists

# ── 3. Compute shape features ──
matched["building_footprint"] = matched.geometry.area
matched["perimeter"] = matched.geometry.length
matched["gross_floor_area"] = matched["building_footprint"] * matched["floors"]

mrr = matched.geometry.minimum_rotated_rectangle()
def aspect(r):
    b = r.bounds
    dx, dy = b[2]-b[0], b[3]-b[1]
    return max(dx,dy) / max(min(dx,dy), 0.01)
matched["aspect_ratio"] = mrr.apply(aspect)
matched["compactness_ratio"] = 4 * np.pi * matched["building_footprint"] / (matched["perimeter"]**2)
matched["convexity_ratio"] = matched["building_footprint"] / matched.geometry.convex_hull.area

# ── 4. Get ep from raw Taobao 2026 shapefile via spatial join ──
print("\nLoading raw Taobao 2026 for ep field...")
TAOBAO_SHP = Path(ROOT) / "data/raw/taobao/shanghai_2026_height/2026 Building/2026 Building.shp"
taobao = gpd.read_file(str(TAOBAO_SHP))
taobao_proj = taobao.to_crs(epsg=4547)
taobao_centroids = taobao_proj.geometry.centroid
taobao_tree = cKDTree(np.column_stack([taobao_centroids.x.values, taobao_centroids.y.values]))

# Match validation building centroids to raw Taobao
val_centroids = matched.geometry.centroid
val_cx = val_centroids.x.values
val_cy = val_centroids.y.values
ep_dists, ep_idxs = taobao_tree.query(np.column_stack([val_cx, val_cy]), k=1)
matched["ep"] = taobao["ep"].iloc[ep_idxs].values
matched["ep_match_dist"] = ep_dists
print(f"ep matched: {(ep_dists < 50).sum()}/{len(matched)} within 50m")
print(f"ep value distribution:\n{matched['ep'].value_counts().sort_index().to_string()}")

# ── 5. Filter: exclude residential, education, unclear ──
EXCLUDE = ["residential", "education", "unclear"]
nonres = matched[~matched["gt_archetype"].isin(EXCLUDE)].copy()
print(f"\nAfter excluding {EXCLUDE}: {len(nonres)} buildings")
print(f"Class distribution:\n{nonres['gt_archetype'].value_counts().to_string()}")

# ── 6. Feature matrix ──
SHAPE_COLS = [
    "building_footprint", "gross_floor_area", "height", "floors",
    "perimeter", "aspect_ratio", "compactness_ratio", "convexity_ratio",
]

# euluc_class is categorical — encode as integer
nonres["euluc_class_enc"] = nonres["euluc_class"].fillna(-1).astype(int)

FEAT_COLS = SHAPE_COLS + ["euluc_class_enc", "ep"]

# Drop rows with NaN in shape features
feat_df = nonres.dropna(subset=SHAPE_COLS).copy()
print(f"After dropping NaN shape features: {len(feat_df)} buildings")

if len(feat_df) < len(nonres):
    dropped = nonres[nonres.index.isin(feat_df.index) == False]
    print(f"  Dropped {len(nonres) - len(feat_df)} buildings with NaN features:")
    for _, r in dropped.iterrows():
        print(f"    {r['val_id']}: gt={r['gt_archetype']}, floors={r.get('floors', 'NA')}")

X = feat_df[FEAT_COLS].values
y = feat_df["gt_archetype"].values

print(f"\nFinal dataset: {len(X)} buildings × {len(FEAT_COLS)} features")
print(f"Features: {FEAT_COLS}")
print(f"Classes: {sorted(set(y))}")
print(f"Class counts: {dict(zip(*np.unique(y, return_counts=True)))}")

# ── 7. Stratified split ──
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, random_state=42, stratify=y
)

print(f"\n{'='*60}")
print("TRAIN / TEST SPLIT (70/30, stratified, seed=42)")
print(f"{'='*60}")
print(f"Train: {len(X_train)}, Test: {len(X_test)}")
print("\nPer-class distribution:")
train_counts = dict(zip(*np.unique(y_train, return_counts=True)))
test_counts = dict(zip(*np.unique(y_test, return_counts=True)))
all_classes = sorted(set(y))
print(f"  {'Class':25s} {'Train':>6s} {'Test':>6s} {'Total':>6s}")
for c in all_classes:
    tr = train_counts.get(c, 0)
    te = test_counts.get(c, 0)
    print(f"  {c:25s} {tr:6d} {te:6d} {tr+te:6d}")

# ── 8. Train models ──
print(f"\n{'='*60}")
print("MODEL TRAINING AND EVALUATION")
print(f"{'='*60}")

le = LabelEncoder()
le.fit(y)
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
    if name == "XGBoost":
        model.fit(X_train, y_train_enc)
        y_pred_enc = model.predict(X_test)
        y_pred = le.inverse_transform(y_pred_enc)
        y_pred_train_enc = model.predict(X_train)
        y_pred_train = le.inverse_transform(y_pred_train_enc)
        importances = model.feature_importances_
    elif name == "CatBoost":
        model.fit(X_train, y_train_enc)
        y_pred_enc = model.predict(X_test).flatten()
        y_pred = le.inverse_transform(y_pred_enc.astype(int))
        y_pred_train_enc = model.predict(X_train).flatten()
        y_pred_train = le.inverse_transform(y_pred_train_enc.astype(int))
        importances = model.feature_importances_
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
    print(f"    {'':25s} " + " ".join(f"{c[:6]:>6s}" for c in all_classes))
    for i, c in enumerate(all_classes):
        print(f"    {c:25s} " + " ".join(f"{cm[i,j]:6d}" for j in range(len(all_classes))))

    # Feature importance
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

# ── 9. Summary comparison ──
print(f"\n{'='*60}")
print("MODEL COMPARISON SUMMARY")
print(f"{'='*60}")
print(f"  {'Model':15s} {'Train Acc':>10s} {'Test Acc':>10s} {'Macro-F1':>10s}")
for name in models:
    r = results[name]
    print(f"  {name:15s} {r['train_accuracy']:10.3f} {r['accuracy']:10.3f} {r['macro_f1']:10.3f}")

# ── 10. Save confusion matrix figure ──
fig, axes = plt.subplots(1, 3, figsize=(24, 7))
for ax, (name, r) in zip(axes, results.items()):
    cm = r["confusion_matrix"]
    im = ax.imshow(cm, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(all_classes)))
    ax.set_xticklabels(all_classes, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(all_classes)))
    ax.set_yticklabels(all_classes, fontsize=8)
    for i in range(len(all_classes)):
        for j in range(len(all_classes)):
            v = cm[i, j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=9,
                    color="white" if v > cm.max()*0.5 else "black")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(f"{name}\nAcc={r['accuracy']:.3f}, F1={r['macro_f1']:.3f}", fontsize=11)
    plt.colorbar(im, ax=ax, shrink=0.8)

fig.suptitle("Non-Residential ML Classification (excl. residential + education)\n"
             f"n={len(feat_df)} buildings, 10 features, 70/30 split, seed=42",
             fontsize=13, y=1.02)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/ml_nonres_confusion.png", dpi=150, bbox_inches="tight")
print(f"\nSaved confusion matrices to {OUTFIG}/ml_nonres_confusion.png")

# ── 11. Feature importance comparison figure ──
fig2, axes2 = plt.subplots(1, 3, figsize=(24, 8))
for ax, (name, r) in zip(axes2, results.items()):
    imp = r["importances"]
    sorted_idx = np.argsort(imp)[::-1]
    ax.barh(range(len(FEAT_COLS)), imp[sorted_idx], align="center")
    ax.set_yticks(range(len(FEAT_COLS)))
    ax.set_yticklabels([FEAT_COLS[i] for i in sorted_idx], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Importance")
    ax.set_title(f"{name}", fontsize=11)
fig2.suptitle("Feature Importance Comparison (non-residential classification)", fontsize=13)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/ml_nonres_feature_importance.png", dpi=150, bbox_inches="tight")
print(f"Saved feature importance to {OUTFIG}/ml_nonres_feature_importance.png")

# ── 12. Data gap warning ──
print(f"\n{'='*60}")
print("DATA GAP WARNING")
print(f"{'='*60}")
print(f"Using {len(feat_df)} buildings (from v0 156 annotated)")
print(f"User expected ~229 (313 - 72 residential - 12 education)")
print(f"Gap: B2 119 rows have ALL EMPTY actual_class")
print(f"Smallest classes: culture={sum(y=='culture')}, healthcare={sum(y=='healthcare')}")
print(f"With 70/30 split, test set has only {len(X_test)} buildings")
print(f"Minority classes may have 0-1 test samples — metrics unreliable")
