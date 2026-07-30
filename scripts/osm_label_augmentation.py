"""OSM 功能标签拉取 + 空间匹配 + 标签合并重训 RF。

目的:从 OSM Overpass API 获取上海范围内有功能标签的建筑/POI,
与 master.gpkg 84 万栋做空间匹配,补充小类别训练样本
(hotel / shopping_mall / sports / culture / government_office 等),
合并所有自动标签后重训 Random Forest。

运行:
  python scripts/osm_label_augmentation.py --data-dir <含 master/euluc/2026 shp 的目录>

产出(全部打印到终端):
  - OSM 拉取统计(各标签类型数量)
  - 空间匹配统计(各 archetype 匹配栋数)
  - 在人工标注集上的准确率验证
  - 新 RF 的准确率和分类别 F1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon, shape

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.ml import features as F

VAL_CSV = PROJECT_ROOT / "data" / "raw" / "validation" / "shanghai_validation_set_v0.csv"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def _log(msg: str) -> None:
    print(f"[osm] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# OSM tag → archetype mapping
# ─────────────────────────────────────────────────────────────────────────────
OSM_TAG_TO_ARCHETYPE: dict[tuple[str, str], str] = {
    # building=* tags (footprint level)
    ("building", "hospital"):     "healthcare",
    ("building", "school"):       "education",
    ("building", "university"):   "education",
    ("building", "college"):      "education",
    ("building", "kindergarten"): "education",
    ("building", "hotel"):        "hotel",
    ("building", "retail"):       "shopping_mall",
    ("building", "commercial"):   "office",
    ("building", "office"):       "office",
    ("building", "government"):   "government_office",
    ("building", "stadium"):      "sports",
    ("building", "sports_hall"):  "sports",
    ("building", "church"):       "other_public",
    ("building", "temple"):       "other_public",
    ("building", "mosque"):       "other_public",
    ("building", "train_station"): "transportation",
    ("building", "transportation"): "transportation",
    # amenity=* tags (POI level)
    ("amenity", "hospital"):        "healthcare",
    ("amenity", "clinic"):          "healthcare",
    ("amenity", "doctors"):         "healthcare",
    ("amenity", "school"):          "education",
    ("amenity", "university"):      "education",
    ("amenity", "college"):         "education",
    ("amenity", "kindergarten"):    "education",
    ("amenity", "theatre"):         "culture",
    ("amenity", "library"):         "culture",
    ("amenity", "cinema"):          "culture",
    ("amenity", "arts_centre"):     "culture",
    ("amenity", "community_centre"): "other_public",
    ("amenity", "place_of_worship"): "other_public",
    ("amenity", "courthouse"):      "government_office",
    ("amenity", "townhall"):        "government_office",
    ("amenity", "bus_station"):     "transportation",
    ("amenity", "ferry_terminal"):  "transportation",
    # tourism=* tags
    ("tourism", "hotel"):   "hotel",
    ("tourism", "motel"):   "hotel",
    ("tourism", "hostel"):  "hotel",
    ("tourism", "museum"):  "culture",
    ("tourism", "gallery"): "culture",
    # leisure=* tags
    ("leisure", "sports_centre"):  "sports",
    ("leisure", "stadium"):        "sports",
    ("leisure", "fitness_centre"): "sports",
    ("leisure", "swimming_pool"):  "sports",
    # shop=* tags
    ("shop", "mall"):             "shopping_mall",
    ("shop", "supermarket"):      "shopping_mall",
    ("shop", "department_store"): "shopping_mall",
    # office=* tags
    ("office", "government"): "government_office",
    # railway=* tags
    ("railway", "station"):   "transportation",
    # aeroway=* tags
    ("aeroway", "terminal"):  "transportation",
}

# Build Overpass query fragments from the mapping
def _build_query_groups() -> dict[str, list[tuple[str, str]]]:
    """Group tags by OSM key for batched Overpass queries."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for (key, val), _ in OSM_TAG_TO_ARCHETYPE.items():
        groups.setdefault(key, []).append((key, val))
    return groups


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Overpass API queries
# ─────────────────────────────────────────────────────────────────────────────
def query_overpass(query: str, endpoints: list[str] = OVERPASS_ENDPOINTS,
                   max_retries: int = 3) -> dict:
    import subprocess
    for endpoint in endpoints:
        for attempt in range(max_retries):
            try:
                _log(f"    querying {endpoint.split('//')[1].split('/')[0]} "
                     f"(attempt {attempt + 1})...")
                result = subprocess.run(
                    ["curl", "-s", "--max-time", "180",
                     "-d", "data=" + query, endpoint],
                    capture_output=True, text=True, timeout=200)
                if result.returncode == 0 and result.stdout.strip().startswith("{"):
                    return json.loads(result.stdout)
                elif "Too Many Requests" in result.stdout or "429" in result.stdout:
                    wait = 2 ** (attempt + 2)
                    _log(f"    rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    _log(f"    curl failed (rc={result.returncode}), retrying...")
                    time.sleep(2 ** attempt)
            except (subprocess.TimeoutExpired, Exception) as e:
                _log(f"    error: {e}, retrying...")
                time.sleep(2 ** (attempt + 1))
        _log(f"    endpoint {endpoint} exhausted, trying next...")
    raise RuntimeError("All Overpass endpoints failed")


def _resolve_archetype(tags: dict) -> tuple[str, str, str] | None:
    """Given an OSM element's tags dict, return (key, value, archetype) or None."""
    for (k, v), arch in OSM_TAG_TO_ARCHETYPE.items():
        if tags.get(k) == v:
            return (k, v, arch)
    return None


def fetch_osm_data() -> gpd.GeoDataFrame:
    """Fetch all tagged buildings and POIs from OSM for Shanghai in batched queries.

    Uses 4 batched queries (building, amenity+tourism+leisure, shop+office, railway+aeroway)
    to minimize Overpass API calls and avoid rate limiting.
    """
    all_rows: list[dict] = []
    seen_ids: set[str] = set()

    # Group tags into 4 batches to keep each query manageable
    batches = [
        ("building tags", [
            ('building', 'hospital'), ('building', 'school'), ('building', 'university'),
            ('building', 'college'), ('building', 'kindergarten'), ('building', 'hotel'),
            ('building', 'retail'), ('building', 'commercial'), ('building', 'office'),
            ('building', 'government'), ('building', 'stadium'), ('building', 'sports_hall'),
            ('building', 'church'), ('building', 'temple'), ('building', 'mosque'),
            ('building', 'train_station'), ('building', 'transportation'),
        ]),
        ("amenity+tourism tags", [
            ('amenity', 'hospital'), ('amenity', 'clinic'), ('amenity', 'doctors'),
            ('amenity', 'school'), ('amenity', 'university'), ('amenity', 'college'),
            ('amenity', 'kindergarten'), ('amenity', 'theatre'), ('amenity', 'library'),
            ('amenity', 'cinema'), ('amenity', 'arts_centre'), ('amenity', 'community_centre'),
            ('amenity', 'place_of_worship'), ('amenity', 'courthouse'), ('amenity', 'townhall'),
            ('amenity', 'bus_station'), ('amenity', 'ferry_terminal'),
            ('tourism', 'hotel'), ('tourism', 'motel'), ('tourism', 'hostel'),
            ('tourism', 'museum'), ('tourism', 'gallery'),
        ]),
        ("leisure+shop tags", [
            ('leisure', 'sports_centre'), ('leisure', 'stadium'),
            ('leisure', 'fitness_centre'), ('leisure', 'swimming_pool'),
            ('shop', 'mall'), ('shop', 'supermarket'), ('shop', 'department_store'),
        ]),
        ("office+transport tags", [
            ('office', 'government'),
            ('railway', 'station'),
            ('aeroway', 'terminal'),
        ]),
    ]

    for batch_name, tag_pairs in batches:
        _log(f"  Batch: {batch_name} ({len(tag_pairs)} tags)...")

        # Build union query
        lines = []
        for key, val in tag_pairs:
            lines.append(f'  node["{key}"="{val}"](area.searchArea);')
            lines.append(f'  way["{key}"="{val}"](area.searchArea);')
        union_body = "\n".join(lines)

        query = f"""[out:json][timeout:300];
area["name"="上海市"]->.searchArea;
(
{union_body}
);
out body;
>;
out skel qt;
"""
        try:
            data = query_overpass(query, max_retries=5)
        except RuntimeError:
            _log(f"    → FAILED batch, trying individual tags...")
            for key, val in tag_pairs:
                q = f'[out:json][timeout:120];area["name"="上海市"]->.searchArea;(node["{key}"="{val}"](area.searchArea);way["{key}"="{val}"](area.searchArea););out body;>;out skel qt;'
                try:
                    data = query_overpass(q, max_retries=3)
                    elements = data.get("elements", [])
                    _process_elements(elements, seen_ids, all_rows)
                    _log(f"      {key}={val}: OK")
                except RuntimeError:
                    _log(f"      {key}={val}: FAILED")
                time.sleep(3)
            time.sleep(5)
            continue

        elements = data.get("elements", [])
        before = len(all_rows)
        _process_elements(elements, seen_ids, all_rows)
        added = len(all_rows) - before
        _log(f"    → {added} features (raw elements: {len(elements)})")
        time.sleep(3)

    if not all_rows:
        raise RuntimeError("No OSM data fetched — check network connectivity")

    gdf = gpd.GeoDataFrame(all_rows, crs=4326)
    _log(f"Total unique OSM features: {len(gdf)}")
    return gdf


def _process_elements(elements: list[dict], seen_ids: set[str],
                      all_rows: list[dict]) -> None:
    """Parse Overpass JSON elements, resolve archetypes, append to all_rows."""
    nodes_map: dict[int, tuple[float, float]] = {}
    ways: list[dict] = []

    for el in elements:
        if el["type"] == "node":
            nodes_map[el["id"]] = (el["lon"], el["lat"])
            if "tags" in el:
                res = _resolve_archetype(el["tags"])
                if res is None:
                    continue
                uid = f"node/{el['id']}"
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                key, val, arch = res
                all_rows.append({
                    "osm_id": uid, "osm_type": "node",
                    "osm_key": key, "osm_value": val,
                    "archetype": arch,
                    "name": el["tags"].get("name", ""),
                    "geometry": Point(el["lon"], el["lat"]),
                })
        elif el["type"] == "way":
            if "tags" in el:
                ways.append(el)
            else:
                if "nodes" in el:
                    ways.append(el)

    # Second pass: resolve way geometries
    tagged_ways = [w for w in ways if "tags" in w]
    skel_ways = {w["id"]: w for w in ways if "tags" not in w and "nodes" in w}

    for el in tagged_ways:
        res = _resolve_archetype(el["tags"])
        if res is None:
            continue
        uid = f"way/{el['id']}"
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        key, val, arch = res
        nds = el.get("nodes", [])
        coords = [nodes_map[n] for n in nds if n in nodes_map]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            geom = Polygon(coords)
            gtype = "way_polygon"
        elif len(coords) >= 1:
            geom = Point(np.mean([c[0] for c in coords]),
                         np.mean([c[1] for c in coords]))
            gtype = "way_point"
        else:
            continue
        all_rows.append({
            "osm_id": uid, "osm_type": gtype,
            "osm_key": key, "osm_value": val,
            "archetype": arch,
            "name": el["tags"].get("name", ""),
            "geometry": geom,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Print OSM fetch statistics
# ─────────────────────────────────────────────────────────────────────────────
def print_osm_stats(osm: gpd.GeoDataFrame) -> None:
    _log("=" * 70)
    _log("OSM 拉取统计")
    _log("=" * 70)

    _log(f"\n按 OSM 标签类型:")
    tag_counts = osm.groupby(["osm_key", "osm_value"]).size().reset_index(name="count")
    tag_counts = tag_counts.sort_values("count", ascending=False)
    for _, row in tag_counts.iterrows():
        _log(f"  {row['osm_key']}={row['osm_value']:25s} {row['count']:5d}")

    _log(f"\n按映射 archetype:")
    arch_counts = osm["archetype"].value_counts()
    for arch, n in arch_counts.items():
        _log(f"  {arch:25s} {n:5d}")

    _log(f"\n按几何类型:")
    type_counts = osm["osm_type"].value_counts()
    for t, n in type_counts.items():
        _log(f"  {t:15s} {n:5d}")
    _log("")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Spatial matching with master.gpkg
# ─────────────────────────────────────────────────────────────────────────────
def spatial_match(osm: gpd.GeoDataFrame, master: gpd.GeoDataFrame,
                  metric_epsg: int = 32651, max_dist_m: float = 150.0
                  ) -> pd.DataFrame:
    """Match OSM features to master buildings.

    - OSM polygons: find master building with largest intersection area
    - OSM points: find nearest master building centroid within max_dist_m
    - Conflicts (one master building matched to multiple archetypes): flagged
    """
    _log("空间匹配: projecting to metric CRS...")
    master_m = master.to_crs(metric_epsg)
    osm_m = osm.to_crs(metric_epsg)

    rp = master_m.geometry.representative_point()
    master_xy = np.column_stack([rp.x.to_numpy(), rp.y.to_numpy()])
    tree = cKDTree(master_xy)

    matches: list[dict] = []

    is_poly = osm_m.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    osm_polys = osm_m[is_poly]
    osm_points = osm_m[~is_poly]

    _log(f"  polygons: {len(osm_polys)}, points: {len(osm_points)}")

    # --- Polygon matching (largest overlap) ---
    if len(osm_polys) > 0:
        _log("  matching polygons via spatial join...")
        sj = gpd.sjoin(master_m.reset_index(), osm_polys[["geometry"]].reset_index(),
                       predicate="intersects", how="inner",
                       lsuffix="master", rsuffix="osm")

        for osm_idx in osm_polys.index:
            hits = sj[sj["index_osm"] == osm_idx]
            if len(hits) == 0:
                osm_pt = osm_m.loc[osm_idx].geometry.representative_point()
                dist, idx = tree.query([osm_pt.x, osm_pt.y])
                if dist <= max_dist_m:
                    matches.append({
                        "osm_idx": osm_idx,
                        "master_row": idx,
                        "match_type": "poly_fallback_nearest",
                        "match_dist_m": float(dist),
                    })
                continue
            osm_geom = osm_polys.loc[osm_idx, "geometry"]
            best_row, best_area = -1, 0.0
            for _, hit in hits.iterrows():
                m_geom = master_m.geometry.iloc[hit["index_master"]]
                inter = osm_geom.intersection(m_geom).area
                if inter > best_area:
                    best_area = inter
                    best_row = hit["index_master"]
            if best_row >= 0:
                matches.append({
                    "osm_idx": osm_idx,
                    "master_row": best_row,
                    "match_type": "polygon_overlap",
                    "match_dist_m": 0.0,
                })

    # --- Point matching (nearest neighbor) ---
    if len(osm_points) > 0:
        _log("  matching points via nearest neighbor...")
        pts = osm_points.geometry
        pt_xy = np.column_stack([pts.x.to_numpy(), pts.y.to_numpy()])
        dists, idxs = tree.query(pt_xy)

        for i, (osm_idx, d, mi) in enumerate(
                zip(osm_points.index, dists, idxs)):
            if d <= max_dist_m:
                matches.append({
                    "osm_idx": osm_idx,
                    "master_row": int(mi),
                    "match_type": "point_nearest",
                    "match_dist_m": float(d),
                })

    mdf = pd.DataFrame(matches)
    if len(mdf) == 0:
        _log("  WARNING: no matches found!")
        return mdf

    mdf["osm_archetype"] = osm.loc[mdf["osm_idx"].to_numpy(), "archetype"].to_numpy()

    # --- Conflict detection ---
    conflict_rows = set()
    for master_row, grp in mdf.groupby("master_row"):
        archs = grp["osm_archetype"].unique()
        if len(archs) > 1:
            conflict_rows.update(grp.index.tolist())

    mdf["conflict"] = mdf.index.isin(conflict_rows)
    n_conflict = int(mdf["conflict"].sum())
    n_unique_master = mdf[~mdf["conflict"]]["master_row"].nunique()

    _log(f"  total matches: {len(mdf)}, conflicts: {n_conflict}, "
         f"clean unique master buildings: {n_unique_master}")

    return mdf


def print_match_stats(mdf: pd.DataFrame, osm: gpd.GeoDataFrame) -> None:
    _log("=" * 70)
    _log("空间匹配统计")
    _log("=" * 70)

    clean = mdf[~mdf["conflict"]]
    deduped = clean.drop_duplicates(subset="master_row", keep="first")

    _log(f"\n各 archetype 匹配栋数(去重去冲突):")
    arch_counts = deduped["osm_archetype"].value_counts()
    for arch, n in arch_counts.items():
        _log(f"  {arch:25s} {n:5d}")
    _log(f"  {'TOTAL':25s} {len(deduped):5d}")

    _log(f"\n匹配类型分布:")
    type_counts = mdf["match_type"].value_counts()
    for t, n in type_counts.items():
        _log(f"  {t:25s} {n:5d}")

    _log(f"\n距离统计(点匹配):")
    pt = mdf[mdf["match_type"] == "point_nearest"]["match_dist_m"]
    if len(pt) > 0:
        _log(f"  mean={pt.mean():.1f}m  median={pt.median():.1f}m  "
             f"p90={pt.quantile(0.9):.1f}m  max={pt.max():.1f}m")

    _log(f"\n冲突数(同一 master 建筑被匹配到多个不同 archetype): {int(mdf['conflict'].sum())}")
    _log("")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Cross-validation against human annotations
# ─────────────────────────────────────────────────────────────────────────────
def cross_validate_with_human(mdf: pd.DataFrame, master: gpd.GeoDataFrame,
                              metric_epsg: int = 32651) -> None:
    """Check OSM labels against the 156 human-annotated validation buildings."""
    _log("=" * 70)
    _log("与人工标注交叉验证")
    _log("=" * 70)

    val = pd.read_csv(VAL_CSV)
    val = val[val.status == "annotated"].copy()

    master_m = master.to_crs(metric_epsg)
    rp = master_m.geometry.representative_point()
    master_xy = np.column_stack([rp.x.to_numpy(), rp.y.to_numpy()])
    tree = cKDTree(master_xy)

    pts = gpd.GeoDataFrame(val, geometry=gpd.points_from_xy(val.lon, val.lat), crs=4326)
    pts_m = pts.to_crs(metric_epsg)
    pt_xy = np.column_stack([pts_m.geometry.x.to_numpy(), pts_m.geometry.y.to_numpy()])
    dists, idxs = tree.query(pt_xy)

    val["master_row"] = idxs
    val["match_dist"] = dists
    val = val[val["match_dist"] <= 15].copy()

    clean = mdf[~mdf["conflict"]].drop_duplicates(subset="master_row", keep="first")
    osm_labels = clean.set_index("master_row")["osm_archetype"]

    val["osm_archetype"] = val["master_row"].map(osm_labels)
    has_osm = val[val["osm_archetype"].notna()].copy()

    _log(f"\n  人工标注总数: {len(val)}")
    _log(f"  有 OSM 标签覆盖: {len(has_osm)}")

    if len(has_osm) == 0:
        _log("  无交叉验证数据")
        return

    correct = (has_osm["archetype"] == has_osm["osm_archetype"]).sum()
    total = len(has_osm)
    acc = correct / total * 100

    _log(f"  OSM vs 人工: {correct}/{total} = {acc:.1f}% 准确率")
    _log(f"\n  逐类对比:")
    for arch in sorted(has_osm["archetype"].unique()):
        sub = has_osm[has_osm["archetype"] == arch]
        c = (sub["archetype"] == sub["osm_archetype"]).sum()
        _log(f"    人工={arch:25s} n={len(sub):3d}  "
             f"OSM正确={c:3d}  OSM给标: {sub['osm_archetype'].value_counts().to_dict()}")

    # Also show cases where OSM and human disagree
    disagree = has_osm[has_osm["archetype"] != has_osm["osm_archetype"]]
    if len(disagree) > 0:
        _log(f"\n  分歧案例 ({len(disagree)} 个):")
        for _, row in disagree.head(20).iterrows():
            _log(f"    {row['val_id']}: 人工={row['archetype']}, OSM={row['osm_archetype']}")
    _log("")


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Merge labels and retrain RF
# ─────────────────────────────────────────────────────────────────────────────
def build_merged_training_set(master: gpd.GeoDataFrame, mdf: pd.DataFrame,
                              cfg: dict, metric_epsg: int = 32651
                              ) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """Build merged training set: human > OSM > EULUC (priority order).

    Returns (train_rows, train_labels, val_rows_for_eval, val_df).
    """
    _log("=" * 70)
    _log("构建合并训练集")
    _log("=" * 70)

    # 1. Human annotations (highest priority)
    val = pd.read_csv(VAL_CSV)
    val = val[val.status == "annotated"].copy()

    master_m = master.to_crs(metric_epsg)
    rp = master_m.geometry.representative_point()
    master_xy = np.column_stack([rp.x.to_numpy(), rp.y.to_numpy()])
    tree = cKDTree(master_xy)

    pts = gpd.GeoDataFrame(val, geometry=gpd.points_from_xy(val.lon, val.lat), crs=4326)
    pts_m = pts.to_crs(metric_epsg)
    pt_xy = np.column_stack([pts_m.geometry.x.to_numpy(), pts_m.geometry.y.to_numpy()])
    dists, idxs = tree.query(pt_xy)
    val["master_row"] = idxs
    val["match_dist"] = dists
    val_matched = val[val["match_dist"] <= 15].copy()

    excl = set(cfg["truth"]["exclude_val_ids"])
    val_train = val_matched[~val_matched["val_id"].isin(excl)].copy()
    val_eval = val_matched.copy()

    # Align residential labels with the mid/high split
    floor_cutoff = 10
    floors_arr = pd.to_numeric(master["floors"], errors="coerce")
    def _align_residential(arch: str, master_row: int) -> str:
        if arch != "residential":
            return arch
        fl = floors_arr.iloc[master_row]
        if pd.isna(fl):
            return "residential_mid_rise"
        return "residential_high_rise" if fl >= floor_cutoff else "residential_mid_rise"

    human_rows = {r: _align_residential(a, r) for r, a in
                  zip(val_train["master_row"], val_train["archetype"])
                  if a != "unclear"}
    # Also align in val_eval for consistent evaluation
    val_eval = val_matched[val_matched["archetype"] != "unclear"].copy()
    val_eval["archetype"] = [_align_residential(a, r) for a, r in
                             zip(val_eval["archetype"], val_eval["master_row"])]
    _log(f"  人工标注: {len(human_rows)} 栋 (剔除 {sorted(excl)} + unclear, residential 已拆分 mid/high)")

    # 2. OSM labels (second priority) — only clean non-conflict matches
    clean = mdf[~mdf["conflict"]].drop_duplicates(subset="master_row", keep="first")
    osm_map = dict(zip(clean["master_row"], clean["osm_archetype"]))
    osm_new = {r: a for r, a in osm_map.items() if r not in human_rows}
    _log(f"  OSM 匹配: {len(osm_map)} 栋, 新增(不与人工重复): {len(osm_new)} 栋")

    # 3. EULUC high-confidence labels (lowest priority)
    # Cap each EULUC archetype at max_per_class to keep training tractable
    max_per_class = 5000
    rng_euluc = np.random.default_rng(cfg["seed"])
    euluc_map = {
        6: "government_office",
        7: "education",
        8: "healthcare",
        0: "residential",  # split by floors below
        4: "transportation",
        5: "transportation",
    }
    floor_cutoff = 10
    eclasses = pd.to_numeric(master["euluc_class"], errors="coerce")
    floors = pd.to_numeric(master["floors"], errors="coerce")

    # Collect all eligible EULUC rows grouped by archetype
    euluc_by_arch: dict[str, list[int]] = {}
    taken = set(human_rows.keys()) | set(osm_new.keys())
    for i in range(len(master)):
        if i in taken:
            continue
        ec = eclasses.iloc[i]
        if pd.isna(ec):
            continue
        ec_int = int(ec)
        if ec_int not in euluc_map:
            continue
        arch = euluc_map[ec_int]
        if arch == "residential":
            fl = floors.iloc[i]
            if pd.isna(fl):
                continue
            arch = "residential_high_rise" if fl >= floor_cutoff else "residential_mid_rise"
        euluc_by_arch.setdefault(arch, []).append(i)

    euluc_rows: dict[int, str] = {}
    for arch, rows in euluc_by_arch.items():
        total = len(rows)
        if total > max_per_class:
            sampled = rng_euluc.choice(rows, size=max_per_class, replace=False).tolist()
            _log(f"    EULUC {arch}: {total} → {max_per_class} (sampled)")
        else:
            sampled = rows
            _log(f"    EULUC {arch}: {total}")
        for r in sampled:
            euluc_rows[r] = arch

    _log(f"  EULUC 高置信(capped {max_per_class}/class): {len(euluc_rows)} 栋")

    # Merge all
    all_labels: dict[int, tuple[str, str]] = {}
    for r, a in human_rows.items():
        all_labels[r] = (a, "human")
    for r, a in osm_new.items():
        all_labels[r] = (a, "osm")
    for r, a in euluc_rows.items():
        all_labels[r] = (a, "euluc")

    train_rows = np.array(sorted(all_labels.keys()))
    train_labels = np.array([all_labels[r][0] for r in train_rows])
    train_sources = np.array([all_labels[r][1] for r in train_rows])

    _log(f"\n  合并训练集总计: {len(train_rows)} 栋")
    _log(f"  来源分布:")
    for src in ["human", "osm", "euluc"]:
        n = int((train_sources == src).sum())
        _log(f"    {src:10s} {n:6d}")
    _log(f"  类别分布:")
    for arch in sorted(set(train_labels)):
        n = int((train_labels == arch).sum())
        src_breakdown = {}
        for src in ["human", "osm", "euluc"]:
            c = int(((train_labels == arch) & (train_sources == src)).sum())
            if c > 0:
                src_breakdown[src] = c
        _log(f"    {arch:25s} {n:6d}  {src_breakdown}")

    # Count what OSM added vs EULUC existing
    _log(f"\n  OSM 新增(不在人工/EULUC 中):")
    osm_only = {r: a for r, a in osm_new.items() if r not in euluc_rows}
    osm_overlap_euluc = {r: a for r, a in osm_new.items() if r in euluc_rows}
    _log(f"    纯新增: {len(osm_only)} 栋")
    _log(f"    与 EULUC 重叠(OSM 优先): {len(osm_overlap_euluc)} 栋")
    if len(osm_only) > 0:
        for arch in sorted(set(osm_only.values())):
            n = sum(1 for a in osm_only.values() if a == arch)
            _log(f"      {arch:25s} {n:5d}")

    return train_rows, train_labels, val_eval["master_row"].to_numpy(), val_eval


def retrain_rf(master: gpd.GeoDataFrame, X: pd.DataFrame,
               train_rows: np.ndarray, train_labels: np.ndarray,
               val_rows: np.ndarray, val_df: pd.DataFrame,
               xy: np.ndarray, cfg: dict) -> None:
    """Retrain RF with merged training set and evaluate on human annotations."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (confusion_matrix, precision_recall_fscore_support,
                                 classification_report)
    from sklearn.model_selection import GroupKFold

    _log("=" * 70)
    _log("重训 Random Forest(合并训练集）")
    _log("=" * 70)

    seed = cfg["seed"]
    rng = np.random.default_rng(seed)
    grid = cfg["cv"]["grid_size_m"]
    n_boot = cfg["evaluation"]["bootstrap_n"]

    X_tr = X.iloc[train_rows].to_numpy()
    y_tr = train_labels

    # Spatial CV groups
    cells = (np.floor(xy[train_rows, 0] / grid).astype(int) * 100000
             + np.floor(xy[train_rows, 1] / grid).astype(int))
    n_groups = len(np.unique(cells))
    n_splits = min(cfg["cv"]["n_splits"], n_groups)
    _log(f"  训练集 {len(train_rows)} 栋, {n_groups} 个空间网格组, {n_splits} 折 GroupKFold")

    rf_kw = dict(n_estimators=200,
                 max_depth=30,
                 min_samples_leaf=cfg["model"]["min_samples_leaf"],
                 class_weight=None,  # no balanced weights per task instruction
                 random_state=seed, n_jobs=-1)

    # OOF predictions (for human-annotated subset only)
    oof_pred = np.empty(len(train_rows), dtype=object)
    oof_pred[:] = ""
    gkf = GroupKFold(n_splits)
    for k, (itr, ite) in enumerate(gkf.split(X_tr, y_tr, cells)):
        m = RandomForestClassifier(**rf_kw).fit(X_tr[itr], y_tr[itr])
        oof_pred[ite] = m.predict(X_tr[ite])

    # Final model
    _log("  训练终模型...")
    model = RandomForestClassifier(**rf_kw).fit(X_tr, y_tr)

    # Evaluate on human annotations using OOF where available, model elsewhere
    excl = set(cfg["truth"]["exclude_val_ids"])
    val_eval = val_df[~val_df["val_id"].isin(excl)].copy()

    # Build row→oof index mapping
    row_to_oof = {r: i for i, r in enumerate(train_rows)}

    pred_on_val = []
    for _, vrow in val_eval.iterrows():
        mr = vrow["master_row"]
        if mr in row_to_oof:
            pred_on_val.append(oof_pred[row_to_oof[mr]])
        else:
            pred_on_val.append(model.predict(X.iloc[[mr]].to_numpy())[0])
    pred_on_val = np.array(pred_on_val)
    truth_val = val_eval["archetype"].to_numpy()

    # Overall accuracy
    correct = (truth_val == pred_on_val)
    acc = float(correct.mean())
    _log(f"\n  人工标注集 OOF 准确率: {acc:.1%} (n={len(truth_val)})")

    # GFA-weighted accuracy
    gfa = master["area_m2"].to_numpy()[val_eval["master_row"].to_numpy()] * \
          pd.to_numeric(master["floors"], errors="coerce").to_numpy()[val_eval["master_row"].to_numpy()]
    gfa = np.nan_to_num(gfa, nan=0.0)
    if gfa.sum() > 0:
        wacc = float((correct * gfa).sum() / gfa.sum())
        _log(f"  GFA 加权准确率: {wacc:.1%}")

    # In-parcel subset
    eclasses = pd.to_numeric(master["euluc_class"], errors="coerce")
    inpar = eclasses.iloc[val_eval["master_row"].to_numpy()].notna().to_numpy()
    if inpar.sum() > 0:
        acc_ip = float(correct[inpar].mean())
        _log(f"  in-parcel 子集准确率: {acc_ip:.1%} (n={int(inpar.sum())})")

    # Per-class metrics
    classes = sorted(set(truth_val) | set(pred_on_val))
    _log(f"\n  分类别 F1:")
    p, r, f1, sup = precision_recall_fscore_support(truth_val, pred_on_val,
                                                     labels=classes, zero_division=0)
    _log(f"  {'class':25s} {'n':>5s} {'prec':>6s} {'rec':>6s} {'f1':>6s}")
    _log(f"  {'-' * 50}")
    for cls, ni, pi, ri, fi in zip(classes, sup, p, r, f1):
        _log(f"  {cls:25s} {ni:5d} {pi:6.3f} {ri:6.3f} {fi:6.3f}")

    macro_f1 = float(f1.mean())
    weighted_f1 = float(np.average(f1, weights=sup) if sup.sum() > 0 else 0)
    _log(f"\n  macro F1: {macro_f1:.3f}")
    _log(f"  weighted F1: {weighted_f1:.3f}")

    # Compare with B1 baseline
    _log(f"\n  对比 B1 基线:")
    rb = cfg["evaluation"]["rule_baselines"]
    _log(f"    B1 in-parcel 同分母: {rb['full_rule_in_parcel_pct']:.1f}% (全规则) / "
         f"{rb['euluc_only_pct']:.1f}% (EULUC-only)")
    _log(f"    本次 in-parcel: {acc_ip:.1%}" if inpar.sum() > 0 else "    (no in-parcel data)")
    _log(f"    本次全量: {acc:.1%}")

    # Feature importance top 10
    imp = pd.DataFrame({"feature": X.columns, "importance": model.feature_importances_})
    imp = imp.sort_values("importance", ascending=False).head(10)
    _log(f"\n  特征重要性 Top 10:")
    for _, row in imp.iterrows():
        _log(f"    {row['feature']:30s} {row['importance']:.5f}")

    # Confusion matrix
    _log(f"\n  混淆矩阵:")
    cm = confusion_matrix(truth_val, pred_on_val, labels=classes)
    header = "  " + f"{'':25s}" + " ".join(f"{c[:6]:>6s}" for c in classes)
    _log(header)
    for cls, row in zip(classes, cm):
        _log(f"  {cls:25s}" + " ".join(f"{v:6d}" for v in row))

    _log("")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True,
                    help="Directory with module_a_master.gpkg, euluc_shanghai_2022.gpkg, "
                         "and '2026 Building/2026 Building.shp'")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "b1_baseline.yaml"))
    epsg = cfg["metric_epsg"]

    # ---- Step 1: Fetch OSM data (cache to disk) ----
    osm_cache = args.data_dir / "osm_shanghai_tags.gpkg"
    if osm_cache.exists():
        _log("Step 1: 从缓存加载 OSM 数据...")
        osm = gpd.read_file(osm_cache)
        _log(f"  loaded {len(osm)} features from cache")
    else:
        _log("Step 1: 从 Overpass API 下载 OSM 功能标签数据...")
        osm = fetch_osm_data()
        osm.to_file(osm_cache, driver="GPKG")
        _log(f"  cached to {osm_cache}")

    # ---- Step 2: Print OSM stats ----
    print_osm_stats(osm)

    # ---- Load master and compute features ----
    _log("载入 master + 计算特征...")
    g = F.load_master(args.data_dir / "module_a_master.gpkg")
    F.attach_vendor_fields(g, args.data_dir / "2026 Building" / "2026 Building.shp")
    gm = F.shape_features(g, epsg)
    F.scale_features(g)
    xy = F.neighborhood_features(g, gm, cfg["features"]["neighborhood_radius_m"],
                                 cfg["features"]["no_neighbor_fill"])
    del gm
    F.parcel_features(g, args.data_dir / "euluc_shanghai_2022.gpkg", epsg)
    X = F.build_feature_matrix(g)
    _log(f"特征矩阵 {X.shape[0]:,} × {X.shape[1]}")

    # ---- Step 3: Spatial matching ----
    _log("Step 3: 空间匹配...")
    mdf = spatial_match(osm, g, metric_epsg=epsg)
    print_match_stats(mdf, osm)

    # ---- Step 4: Cross-validation with human annotations ----
    _log("Step 4: 与人工标注交叉验证...")
    cross_validate_with_human(mdf, g, metric_epsg=epsg)

    # ---- Compare with EULUC+ep auto labels ----
    _log("=" * 70)
    _log("与 EULUC+ep 自动标签对比")
    _log("=" * 70)
    clean = mdf[~mdf["conflict"]].drop_duplicates(subset="master_row", keep="first")
    existing_arch = g["archetype"].iloc[clean["master_row"].to_numpy()].to_numpy()
    osm_arch = clean["osm_archetype"].to_numpy()

    agree = (existing_arch == osm_arch).sum()
    _log(f"  OSM vs A6 规则标签: {agree}/{len(clean)} 一致 ({agree/len(clean)*100:.1f}%)")

    new_labels = clean[g["archetype"].iloc[clean["master_row"].to_numpy()].to_numpy() == "unknown"]
    _log(f"  A6 标为 unknown 的建筑中 OSM 新增标签: {len(new_labels)} 栋")
    if len(new_labels) > 0:
        for arch in sorted(new_labels["osm_archetype"].unique()):
            n = (new_labels["osm_archetype"] == arch).sum()
            _log(f"    {arch:25s} {n:5d}")
    _log("")

    # ---- Step 5: Merge and retrain ----
    _log("Step 5: 合并标签 + 重训 RF...")
    train_rows, train_labels, val_rows, val_df = build_merged_training_set(
        g, mdf, cfg, metric_epsg=epsg)
    retrain_rf(g, X, train_rows, train_labels, val_rows, val_df, xy, cfg)

    _log("全部完成。")


if __name__ == "__main__":
    main()
