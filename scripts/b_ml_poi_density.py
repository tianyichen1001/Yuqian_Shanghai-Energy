"""Experiment A + POI density features (14 features total).
Adds hotel_poi_150m, mall_poi_150m, retail_poi_150m, retail_poi_100m
to the 10-feature baseline (8 shape + euluc_class + ep).
"""
import pandas as pd
import geopandas as gpd
import numpy as np
from pathlib import Path
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
import math
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
OUTFIG = ROOT / "outputs" / "figures"
OUTTAB = ROOT / "outputs" / "tables"

# ═══════════════════════════════════════════════════════════════════
# 0. GCJ-02 → WGS84 CONVERSION
# ═══════════════════════════════════════════════════════════════════
def gcj02_to_wgs84(lng, lat):
    """Convert GCJ-02 coordinates to WGS84 (iterative method)."""
    a = 6378245.0
    ee = 0.00669342162296594323

    def _transform_lat(x, y):
        ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
        ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
        ret += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
        ret += (160.0*math.sin(y/12.0*math.pi) + 320*math.sin(y*math.pi/30.0)) * 2.0/3.0
        return ret

    def _transform_lng(x, y):
        ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
        ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
        ret += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
        ret += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
        return ret

    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng * 2 - (lng + dlng), lat * 2 - (lat + dlat)

def gcj02_to_wgs84_batch(lngs, lats):
    """Vectorized GCJ-02 → WGS84."""
    wgs_lngs = np.empty(len(lngs))
    wgs_lats = np.empty(len(lats))
    for i in range(len(lngs)):
        wgs_lngs[i], wgs_lats[i] = gcj02_to_wgs84(lngs[i], lats[i])
    return wgs_lngs, wgs_lats


# ═══════════════════════════════════════════════════════════════════
# 1. LOAD AND MERGE GROUND TRUTH (same as previous experiment)
# ═══════════════════════════════════════════════════════════════════
print("Loading master.gpkg...")
master = gpd.read_file(ROOT / "data" / "interim" / "module_a_master.gpkg")
master_proj = master.to_crs(epsg=4547)
centroids = master_proj.geometry.centroid
tree = cKDTree(np.column_stack([centroids.x.values, centroids.y.values]))

# -- Source 1: v0 --
v0 = pd.read_csv(ROOT / "data" / "raw" / "validation" / "shanghai_validation_set_v0.csv")
v0_ann = v0[(v0["status"] == "annotated") & (v0["archetype"] != "unclear")].copy()

v0_gdf = gpd.GeoDataFrame(
    v0_ann, geometry=gpd.points_from_xy(v0_ann["lon"], v0_ann["lat"]), crs="EPSG:4326",
).to_crs(epsg=4547)
v0_dists, v0_idxs = tree.query(
    np.column_stack([v0_gdf.geometry.x.values, v0_gdf.geometry.y.values]), k=1
)
v0_matched = master_proj.iloc[v0_idxs].copy().reset_index(drop=True)
v0_matched["gt_archetype"] = v0_ann["archetype"].values
v0_matched["master_idx"] = v0_idxs
v0_matched["source"] = "v0"

# -- Source 2: B2 --
b2 = pd.read_excel(ROOT / "data" / "raw" / "validation" / "UBEM_标注工作簿_B0_B2.xlsx", sheet_name="B2标注119栋")
b2_col = "建筑类型(填英文)"
b2_ann = b2[b2[b2_col].apply(lambda x: pd.notna(x) and str(x).strip() != "")].copy()
b2_ann = b2_ann[~b2_ann[b2_col].isin(["unclear"])].copy()
b2_ann = b2_ann[~b2_ann[b2_col].str.contains(r"\+", na=False)].copy()
b2_master_idxs = b2_ann["bid"].values.astype(int)
b2_matched = master_proj.iloc[b2_master_idxs].copy().reset_index(drop=True)
b2_matched["gt_archetype"] = b2_ann[b2_col].values
b2_matched["master_idx"] = b2_master_idxs
b2_matched["source"] = "b2"

# -- Source 3: Smallclass --
sc = pd.read_excel(ROOT / "data" / "raw" / "validation" / "smallclass_verification_20260803.xlsx", sheet_name="verify")
sc_ann = sc[sc["your_archetype"].apply(lambda x: pd.notna(x) and str(x).strip() != "")].copy()
sc_ann = sc_ann[~sc_ann["your_archetype"].isin(["unclear"])].copy()
archetype_normalize = {
    "government office": "government_office",
    "residential_mid_rise": "residential",
    "residential_high_rise": "residential",
    "mixed-use": "mixed_use",
}
sc_ann["your_archetype"] = sc_ann["your_archetype"].map(lambda x: archetype_normalize.get(x, x))
sc_gdf = gpd.GeoDataFrame(
    sc_ann, geometry=gpd.points_from_xy(sc_ann["lon"], sc_ann["lat"]), crs="EPSG:4326",
).to_crs(epsg=4547)
sc_dists, sc_idxs = tree.query(
    np.column_stack([sc_gdf.geometry.x.values, sc_gdf.geometry.y.values]), k=1
)
sc_matched = master_proj.iloc[sc_idxs].copy().reset_index(drop=True)
sc_matched["gt_archetype"] = sc_ann["your_archetype"].values
sc_matched["master_idx"] = sc_idxs
sc_matched["source"] = "smallclass"

# Merge + dedup
keep_cols = list(master_proj.columns) + ["gt_archetype", "master_idx", "source"]
all_matched = pd.concat([v0_matched[keep_cols], b2_matched[keep_cols], sc_matched[keep_cols]], ignore_index=True)
all_matched = all_matched.drop_duplicates(subset=["master_idx"], keep="first")
print(f"Merged ground truth: {len(all_matched)} buildings")

# ═══════════════════════════════════════════════════════════════════
# 2. COMPUTE SHAPE FEATURES
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

# ep from raw Taobao
import subprocess, os
data_repo = ROOT.parent / "Yuqian_Shanghai-Energy-data"
taobao_zip = data_repo / "shanghai_2026_building.zip"
taobao_tmp = Path("/tmp/taobao_2026")
taobao_shp = taobao_tmp / "2026 Building" / "2026 Building.shp"
if not taobao_shp.exists():
    subprocess.run(["unzip", "-o", str(taobao_zip), "-d", str(taobao_tmp)], capture_output=True)
print("Loading Taobao for ep...")
taobao = gpd.read_file(taobao_shp)
taobao_proj = taobao.to_crs(epsg=4547)
taobao_centroids = taobao_proj.geometry.centroid
taobao_tree = cKDTree(np.column_stack([taobao_centroids.x.values, taobao_centroids.y.values]))
match_centroids = all_matched.geometry.centroid
ep_dists, ep_idxs = taobao_tree.query(
    np.column_stack([match_centroids.x.values, match_centroids.y.values]), k=1
)
all_matched["ep"] = taobao["ep"].iloc[ep_idxs].values
del taobao, taobao_proj, taobao_centroids, taobao_tree

all_matched["euluc_class_enc"] = all_matched["euluc_class"].fillna(-1).astype(int)

# ═══════════════════════════════════════════════════════════════════
# 3. COMPUTE POI DENSITY FEATURES
# ═══════════════════════════════════════════════════════════════════
print("\n--- Computing POI density features ---")

bldg_cx = match_centroids.x.values
bldg_cy = match_centroids.y.values

# -- A3a: hotel + mall POI (already in WGS84) --
a3a = pd.read_csv(ROOT / "data" / "raw" / "poi" / "a3_pois_clean.csv")
a3a["typecode_str"] = a3a["typecode"].astype(str)

hotel_poi = a3a[a3a["typecode_str"].str.startswith("1001")].copy()
hotel_gdf = gpd.GeoDataFrame(
    hotel_poi, geometry=gpd.points_from_xy(hotel_poi["wgs_lng"], hotel_poi["wgs_lat"]), crs="EPSG:4326"
).to_crs(epsg=4547)
hotel_tree = cKDTree(np.column_stack([hotel_gdf.geometry.x.values, hotel_gdf.geometry.y.values]))
print(f"A3a hotel POI (1001*): {len(hotel_poi)}")

mall_poi = a3a[a3a["typecode_str"].str.startswith("0601")].copy()
mall_gdf = gpd.GeoDataFrame(
    mall_poi, geometry=gpd.points_from_xy(mall_poi["wgs_lng"], mall_poi["wgs_lat"]), crs="EPSG:4326"
).to_crs(epsg=4547)
mall_tree = cKDTree(np.column_stack([mall_gdf.geometry.x.values, mall_gdf.geometry.y.values]))
print(f"A3a mall POI (0601*): {len(mall_poi)}")

hotel_counts_150 = hotel_tree.query_ball_point(np.column_stack([bldg_cx, bldg_cy]), r=150.0)
all_matched["hotel_poi_150m"] = [len(x) for x in hotel_counts_150]

mall_counts_150 = mall_tree.query_ball_point(np.column_stack([bldg_cx, bldg_cy]), r=150.0)
all_matched["mall_poi_150m"] = [len(x) for x in mall_counts_150]

print(f"hotel_poi_150m: mean={all_matched['hotel_poi_150m'].mean():.1f}, max={all_matched['hotel_poi_150m'].max()}")
print(f"mall_poi_150m: mean={all_matched['mall_poi_150m'].mean():.1f}, max={all_matched['mall_poi_150m'].max()}")

# -- A3b: retail POI (GCJ-02 → WGS84 conversion needed) --
print("\nLoading A3b retail POI and converting GCJ-02 → WGS84...")
a3b = pd.read_csv(ROOT / "data" / "raw" / "poi" / "a3b_pois_clean.csv")
print(f"A3b total POI: {len(a3b)}")

wgs_lngs, wgs_lats = gcj02_to_wgs84_batch(a3b["lon_gcj02"].values, a3b["lat_gcj02"].values)
a3b_gdf = gpd.GeoDataFrame(
    a3b, geometry=gpd.points_from_xy(wgs_lngs, wgs_lats), crs="EPSG:4326"
).to_crs(epsg=4547)
retail_tree = cKDTree(np.column_stack([a3b_gdf.geometry.x.values, a3b_gdf.geometry.y.values]))
print(f"A3b retail POI (WGS84 converted): {len(a3b_gdf)}")

retail_counts_150 = retail_tree.query_ball_point(np.column_stack([bldg_cx, bldg_cy]), r=150.0)
all_matched["retail_poi_150m"] = [len(x) for x in retail_counts_150]

retail_counts_100 = retail_tree.query_ball_point(np.column_stack([bldg_cx, bldg_cy]), r=100.0)
all_matched["retail_poi_100m"] = [len(x) for x in retail_counts_100]

print(f"retail_poi_150m: mean={all_matched['retail_poi_150m'].mean():.1f}, max={all_matched['retail_poi_150m'].max()}")
print(f"retail_poi_100m: mean={all_matched['retail_poi_100m'].mean():.1f}, max={all_matched['retail_poi_100m'].max()}")

del a3b_gdf, retail_tree, hotel_gdf, hotel_tree, mall_gdf, mall_tree

# ═══════════════════════════════════════════════════════════════════
# 4. FILTER NON-RESIDENTIAL + PREPARE FEATURES
# ═══════════════════════════════════════════════════════════════════
SHAPE_COLS = [
    "building_footprint", "gross_floor_area", "height", "floors",
    "perimeter", "aspect_ratio", "compactness_ratio", "convexity_ratio",
]
POI_COLS = ["hotel_poi_150m", "mall_poi_150m", "retail_poi_150m", "retail_poi_100m"]
FEAT_COLS_BASE = SHAPE_COLS + ["euluc_class_enc", "ep"]
FEAT_COLS_POI = FEAT_COLS_BASE + POI_COLS

EXCLUDE = ["residential", "education"]
feat_all = all_matched.dropna(subset=SHAPE_COLS).copy()
nonres = feat_all[~feat_all["gt_archetype"].isin(EXCLUDE)].copy()

print(f"\n{'='*80}")
print(f"NON-RESIDENTIAL BUILDINGS: {len(nonres)} (9 classes)")
print(f"{'='*80}")
print(nonres["gt_archetype"].value_counts().to_string())

print(f"\n--- POI density by archetype ---")
print(f"{'Archetype':25s} {'hotel_150':>10s} {'mall_150':>10s} {'retail_150':>11s} {'retail_100':>11s}")
for arch in sorted(nonres["gt_archetype"].unique()):
    sub = nonres[nonres["gt_archetype"] == arch]
    print(f"{arch:25s} {sub['hotel_poi_150m'].mean():10.1f} {sub['mall_poi_150m'].mean():10.1f} "
          f"{sub['retail_poi_150m'].mean():11.1f} {sub['retail_poi_100m'].mean():11.1f}")

X_base = nonres[FEAT_COLS_BASE].values
X_poi = nonres[FEAT_COLS_POI].values
y = nonres["gt_archetype"].values
classes = sorted(set(y))

X_train_base, X_test_base, y_train, y_test = train_test_split(
    X_base, y, test_size=0.3, random_state=42, stratify=y
)
X_train_poi, X_test_poi, _, _ = train_test_split(
    X_poi, y, test_size=0.3, random_state=42, stratify=y
)

print(f"\nTrain: {len(X_train_base)}, Test: {len(X_test_base)}")
print("\nPer-class distribution:")
train_vc = dict(zip(*np.unique(y_train, return_counts=True)))
test_vc = dict(zip(*np.unique(y_test, return_counts=True)))
print(f"  {'Class':25s} {'Train':>6s} {'Test':>6s}")
for c in classes:
    print(f"  {c:25s} {train_vc.get(c,0):6d} {test_vc.get(c,0):6d}")


# ═══════════════════════════════════════════════════════════════════
# 5. RUN MODELS — BASELINE (10 features) vs POI (14 features)
# ═══════════════════════════════════════════════════════════════════

def run_models(X_train, X_test, y_train, y_test, all_classes, feat_names, label):
    le = LabelEncoder()
    le.fit(np.concatenate([y_train, y_test]))
    y_train_enc = le.transform(y_train)
    y_test_enc = le.transform(y_test)

    models = {
        "RandomForest": RandomForestClassifier(
            n_estimators=300, random_state=42, class_weight="balanced",
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
        print(f"\n--- {name} ({label}) ---")
        if name in ("XGBoost", "CatBoost"):
            model.fit(X_train, y_train_enc)
            y_pred_enc = model.predict(X_test)
            if name == "CatBoost":
                y_pred_enc = y_pred_enc.flatten().astype(int)
            y_pred = le.inverse_transform(y_pred_enc)
            y_pred_train = le.inverse_transform(
                model.predict(X_train).flatten().astype(int) if name == "CatBoost"
                else model.predict(X_train)
            )
        else:
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            y_pred_train = model.predict(X_train)

        importances = model.feature_importances_
        acc = accuracy_score(y_test, y_pred)
        macro_f1 = f1_score(y_test, y_pred, average="macro", zero_division=0)
        train_acc = accuracy_score(y_train, y_pred_train)

        print(f"  Train acc: {train_acc:.3f}  Test acc: {acc:.3f}  Macro-F1: {macro_f1:.3f}")
        print(f"\n  Classification report:")
        report = classification_report(y_test, y_pred, zero_division=0, digits=3)
        for line in report.split("\n"):
            print(f"    {line}")

        cm = confusion_matrix(y_test, y_pred, labels=all_classes)
        print(f"\n  Confusion matrix:")
        print(f"    {'':25s} " + " ".join(f"{c[:7]:>7s}" for c in all_classes))
        for i, c in enumerate(all_classes):
            print(f"    {c:25s} " + " ".join(f"{cm[i,j]:7d}" for j in range(len(all_classes))))

        feat_imp = sorted(zip(feat_names, importances), key=lambda x: -x[1])
        print(f"\n  Feature importance (top 14):")
        for rank, (fname, imp) in enumerate(feat_imp[:14], 1):
            bar = "#" * int(imp * 80)
            print(f"    {rank:2d}. {fname:25s} {imp:.4f}  {bar}")

        results[name] = {
            "accuracy": acc, "macro_f1": macro_f1, "train_accuracy": train_acc,
            "y_pred": y_pred, "importances": importances, "confusion_matrix": cm,
        }
    return results


print(f"\n\n{'='*80}")
print("BASELINE: 10 features (8 shape + euluc_class + ep)")
print(f"{'='*80}")
results_base = run_models(X_train_base, X_test_base, y_train, y_test, classes, FEAT_COLS_BASE, "baseline")

print(f"\n\n{'='*80}")
print("WITH POI: 14 features (8 shape + euluc_class + ep + 4 POI density)")
print(f"{'='*80}")
results_poi = run_models(X_train_poi, X_test_poi, y_train, y_test, classes, FEAT_COLS_POI, "+POI")


# ═══════════════════════════════════════════════════════════════════
# 6. COMPARISON
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("BASELINE vs +POI COMPARISON")
print(f"{'='*80}")
print(f"\n  {'Model':15s} │ {'Base Acc':>8s} {'Base F1':>8s} │ {'POI Acc':>8s} {'POI F1':>8s} │ {'Δ Acc':>7s} {'Δ F1':>7s}")
print(f"  {'─'*15}─┼─{'─'*8}─{'─'*8}─┼─{'─'*8}─{'─'*8}─┼─{'─'*7}─{'─'*7}")
for name in results_base:
    rb = results_base[name]
    rp = results_poi[name]
    d_acc = rp["accuracy"] - rb["accuracy"]
    d_f1 = rp["macro_f1"] - rb["macro_f1"]
    sign_a = "+" if d_acc >= 0 else ""
    sign_f = "+" if d_f1 >= 0 else ""
    print(f"  {name:15s} │ {rb['accuracy']:8.3f} {rb['macro_f1']:8.3f} │ "
          f"{rp['accuracy']:8.3f} {rp['macro_f1']:8.3f} │ "
          f"{sign_a}{d_acc:6.3f} {sign_f}{d_f1:6.3f}")

print(f"\n\nPer-class F1 comparison (best baseline vs best +POI):")
best_base = max(results_base.items(), key=lambda x: x[1]["macro_f1"])
best_poi = max(results_poi.items(), key=lambda x: x[1]["macro_f1"])
print(f"Best baseline: {best_base[0]}, Best +POI: {best_poi[0]}")

from sklearn.metrics import f1_score as f1s
f1_base = dict(zip(classes, f1s(y_test, best_base[1]["y_pred"], labels=classes, average=None, zero_division=0)))
f1_poi = dict(zip(classes, f1s(y_test, best_poi[1]["y_pred"], labels=classes, average=None, zero_division=0)))

print(f"\n  {'Class':25s} {'n_test':>6s} {'Base F1':>8s} {'POI F1':>8s} {'Δ F1':>7s}")
for c in classes:
    n = test_vc.get(c, 0)
    fb = f1_base[c]
    fp = f1_poi[c]
    d = fp - fb
    sign = "+" if d >= 0 else ""
    print(f"  {c:25s} {n:6d} {fb:8.3f} {fp:8.3f} {sign}{d:6.3f}")


# ═══════════════════════════════════════════════════════════════════
# 7. FIGURES
# ═══════════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(20, 8))
for ax, (title, res) in zip(axes, [
    (f"Baseline ({best_base[0]})\nAcc={best_base[1]['accuracy']:.3f}, F1={best_base[1]['macro_f1']:.3f}",
     best_base[1]),
    (f"+POI ({best_poi[0]})\nAcc={best_poi[1]['accuracy']:.3f}, F1={best_poi[1]['macro_f1']:.3f}",
     best_poi[1]),
]):
    cm = res["confusion_matrix"]
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
    ax.set_title(title, fontsize=11)
    plt.colorbar(im, ax=ax, shrink=0.8)
fig.suptitle("Non-Residential Classification: Baseline vs +POI Density\n"
             f"{len(nonres)} buildings, 70/30 split, seed=42", fontsize=13, y=1.02)
plt.tight_layout()
plt.savefig(OUTFIG / "ml_poi_density_confusion.png", dpi=150, bbox_inches="tight")
print(f"\nSaved confusion matrices to {OUTFIG}/ml_poi_density_confusion.png")

# Feature importance for +POI models
fig2, axes2 = plt.subplots(1, 3, figsize=(24, 8))
for ax, (name, r) in zip(axes2, results_poi.items()):
    imp = r["importances"]
    sorted_idx = np.argsort(imp)[::-1]
    colors = ["#d62728" if FEAT_COLS_POI[i] in POI_COLS else "#1f77b4" for i in sorted_idx]
    ax.barh(range(len(FEAT_COLS_POI)), imp[sorted_idx], align="center", color=colors)
    ax.set_yticks(range(len(FEAT_COLS_POI)))
    ax.set_yticklabels([FEAT_COLS_POI[i] for i in sorted_idx], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Importance")
    ax.set_title(f"{name}\nAcc={r['accuracy']:.3f}, F1={r['macro_f1']:.3f}", fontsize=11)
from matplotlib.patches import Patch
axes2[0].legend(handles=[Patch(facecolor="#d62728", label="POI density"),
                          Patch(facecolor="#1f77b4", label="Shape/EULUC/ep")],
                loc="lower right", fontsize=9)
fig2.suptitle("Feature Importance with POI Density (red = POI features)", fontsize=13)
plt.tight_layout()
plt.savefig(OUTFIG / "ml_poi_density_feat_imp.png", dpi=150, bbox_inches="tight")
print(f"Saved feature importance to {OUTFIG}/ml_poi_density_feat_imp.png")
