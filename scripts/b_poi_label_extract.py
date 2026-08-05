"""Extract hotel and mall training labels from A3a POI data via spatial matching."""
import pandas as pd
import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 1. Load POI data ──
poi = pd.read_csv(ROOT / "data/raw/poi/a3_pois_clean.csv")
print(f"Total POI rows: {len(poi)}")

# ── 2. Filter: typecode exactly 100100 (star hotel) ──
hotel_poi = poi[poi["typecode"].astype(str) == "100100"].copy()
print(f"\ntypecode=100100 (star hotel) exact match: {len(hotel_poi)}")

# ── 3. Filter: typecode exactly 060100 (shopping mall) ──
mall_poi = poi[poi["typecode"].astype(str) == "060100"].copy()
print(f"typecode=060100 (shopping mall) exact match: {len(mall_poi)}")

# ── 4. Load master.gpkg ──
print("\nLoading master.gpkg (843K buildings)...")
master = gpd.read_file(ROOT / "data/interim/module_a_master.gpkg")
print(f"Master buildings: {len(master)}")

# Project to UTM 51N for meter-based distances
master_utm = master.to_crs(epsg=32651)
centroids = master_utm.geometry.centroid
cx = centroids.x.values
cy = centroids.y.values

# Build KDTree on building centroids
print("Building spatial index...")
tree = cKDTree(np.column_stack([cx, cy]))

THRESHOLD_M = 150.0

def match_pois_to_buildings(poi_df, label_name):
    """Match POI points to nearest buildings within threshold."""
    poi_gdf = gpd.GeoDataFrame(
        poi_df,
        geometry=gpd.points_from_xy(poi_df["wgs_lng"], poi_df["wgs_lat"]),
        crs="EPSG:4326",
    )
    poi_utm = poi_gdf.to_crs(epsg=32651)
    px = poi_utm.geometry.x.values
    py = poi_utm.geometry.y.values

    dists, idxs = tree.query(np.column_stack([px, py]), k=1)

    matched_building_indices = set()
    for d, idx in zip(dists, idxs):
        if d <= THRESHOLD_M:
            matched_building_indices.add(idx)

    print(f"\n{label_name}: {len(poi_df)} POIs → {len(matched_building_indices)} unique buildings (≤{THRESHOLD_M}m)")
    return matched_building_indices

# ── 5. Spatial matching ──
hotel_buildings = match_pois_to_buildings(hotel_poi, "Star hotel (100100)")
mall_buildings = match_pois_to_buildings(mall_poi, "Shopping mall (060100)")

# ── 6. Conflict detection ──
conflict = hotel_buildings & mall_buildings
hotel_only = hotel_buildings - conflict
mall_only = mall_buildings - conflict

print(f"\n{'='*60}")
print(f"RESULTS SUMMARY")
print(f"{'='*60}")
print(f"Star hotel POIs (100100 exact):      {len(hotel_poi)}")
print(f"  → matched buildings (unique):      {len(hotel_buildings)}")
print(f"  → hotel-only (no conflict):        {len(hotel_only)}")
print(f"Shopping mall POIs (060100 exact):    {len(mall_poi)}")
print(f"  → matched buildings (unique):      {len(mall_buildings)}")
print(f"  → mall-only (no conflict):         {len(mall_only)}")
print(f"Conflict buildings (both labels):    {len(conflict)}")
print(f"Total labeled (excl. conflicts):     {len(hotel_only) + len(mall_only)}")

# ── 7. Cross-validate with validation set ──
print(f"\n{'='*60}")
print(f"CROSS-VALIDATION vs ground truth")
print(f"{'='*60}")

val = pd.read_csv(ROOT / "data/raw/validation/shanghai_validation_set_v0.csv")
val_ann = val[val["status"] == "annotated"].copy()
print(f"Annotated validation buildings: {len(val_ann)}")

# Match validation points to master buildings
val_gdf = gpd.GeoDataFrame(
    val_ann,
    geometry=gpd.points_from_xy(val_ann["lon"], val_ann["lat"]),
    crs="EPSG:4326",
)
val_utm = val_gdf.to_crs(epsg=32651)
vx = val_utm.geometry.x.values
vy = val_utm.geometry.y.values
val_dists, val_idxs = tree.query(np.column_stack([vx, vy]), k=1)

# Check each validation building
results = []
for i, (row_idx, row) in enumerate(val_ann.iterrows()):
    d = val_dists[i]
    bldg_idx = val_idxs[i]
    gt = row["archetype"]

    if d > 150:
        pred = "no_match_to_master"
    elif bldg_idx in conflict:
        pred = "conflict"
    elif bldg_idx in hotel_only:
        pred = "hotel"
    elif bldg_idx in mall_only:
        pred = "shopping_mall"
    else:
        pred = "unlabeled"

    results.append({
        "val_id": row["val_id"],
        "gt_archetype": gt,
        "poi_label": pred,
        "dist_m": round(d, 1),
        "bldg_idx": bldg_idx,
    })

rdf = pd.DataFrame(results)

# Buildings where POI assigned a label
labeled = rdf[rdf["poi_label"].isin(["hotel", "shopping_mall", "conflict"])]
print(f"\nValidation buildings receiving a POI label: {len(labeled)}")

# Hotel predictions
hotel_pred = rdf[rdf["poi_label"] == "hotel"]
print(f"\nHotel predictions on validation set: {len(hotel_pred)}")
if len(hotel_pred) > 0:
    # gt_archetype == 'hotel' would be correct, but validation has no hotel class
    print("  Ground truth breakdown:")
    print(hotel_pred["gt_archetype"].value_counts().to_string(header=False))

# Mall predictions
mall_pred = rdf[rdf["poi_label"] == "shopping_mall"]
print(f"\nMall predictions on validation set: {len(mall_pred)}")
if len(mall_pred) > 0:
    correct_mall = (mall_pred["gt_archetype"] == "shopping_mall").sum()
    print(f"  Correct (gt=shopping_mall): {correct_mall}/{len(mall_pred)}")
    print("  Ground truth breakdown:")
    print(mall_pred["gt_archetype"].value_counts().to_string(header=False))

# Conflict predictions
conflict_pred = rdf[rdf["poi_label"] == "conflict"]
print(f"\nConflict predictions on validation set: {len(conflict_pred)}")
if len(conflict_pred) > 0:
    print("  Ground truth breakdown:")
    print(conflict_pred["gt_archetype"].value_counts().to_string(header=False))

# Check: how many gt=hotel in validation?
print(f"\nGround truth hotel buildings in validation: {(val_ann['archetype'] == 'hotel').sum()}")
print(f"Ground truth shopping_mall in validation: {(val_ann['archetype'] == 'shopping_mall').sum()}")

# Overall accuracy for labeled buildings
labeled_non_conflict = rdf[rdf["poi_label"].isin(["hotel", "shopping_mall"])]
if len(labeled_non_conflict) > 0:
    # Map poi_label to archetype names
    label_map = {"hotel": "hotel", "shopping_mall": "shopping_mall"}
    correct = sum(
        1 for _, r in labeled_non_conflict.iterrows()
        if r["gt_archetype"] == label_map[r["poi_label"]]
    )
    print(f"\nOverall accuracy of POI labels on validation: {correct}/{len(labeled_non_conflict)} = {correct/len(labeled_non_conflict)*100:.1f}%")

# Detailed view of all labeled validation buildings
print(f"\n{'='*60}")
print("DETAILED: all validation buildings receiving POI labels")
print(f"{'='*60}")
for _, r in rdf[rdf["poi_label"].isin(["hotel", "shopping_mall", "conflict"])].iterrows():
    print(f"  {r['val_id']}: gt={r['gt_archetype']}, poi={r['poi_label']}, dist={r['dist_m']}m")
