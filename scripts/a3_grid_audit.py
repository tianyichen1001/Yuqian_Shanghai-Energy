#!/usr/bin/env python3
"""A3 网格归属体检 — 200 验证点落在已扫格/弃格/网格外;V199/V200 专项。零配额。"""
import glob
import pandas as pd, geopandas as gpd

REPO = "/workspaces/Yuqian_Shanghai-Energy"
grid = gpd.read_file(f"{REPO}/data/reference/a3_scan_grid.gpkg", engine="pyogrio")
meta = pd.read_csv(f"{REPO}/data/reference/a3_cell_meta.csv")
done = set(int(x) for x in open(f"{REPO}/data/raw/poi/a3_done_cells.txt").read().split())
poi  = pd.read_csv(f"{REPO}/data/raw/poi/a3_pois_clean.csv")
vf   = [f for f in glob.glob(f"{REPO}/data/**/*.csv", recursive=True) if "valid" in f.lower()][0]
v    = pd.read_csv(vf)
vg   = gpd.GeoDataFrame(v, geometry=gpd.points_from_xy(v["lon"], v["lat"]), crs=4326)

g = grid.merge(meta, on="cell_id", how="left")
j = gpd.sjoin(vg, g[["cell_id", "area_ha", "geometry"]], how="left", predicate="within")

def status(r):
    if pd.isna(r["cell_id"]): return "网格外(EULUC 盲区)"
    if int(r["cell_id"]) in done: return "已扫格"
    return "门槛弃格"
j["st"] = j.apply(status, axis=1)
print("== 200 行归属 =="); print(j["st"].value_counts().to_string())
print("\n== 156 annotated 归属 ==")
print(j[j["status"] == "annotated"]["st"].value_counts().to_string())

mall = j[j["archetype"].astype(str).str.contains("mall", case=False, na=False)]
print("\n== 14 栋 shopping_mall 逐栋 ==")
for _, r in mall.iterrows():
    extra = f" cell={int(r['cell_id'])} ({r['area_ha']:.1f}ha)" if pd.notna(r["cell_id"]) else ""
    print(f"  {r['val_id']} [{r['area']}] {r['st']}{extra}")

pt, G = vg.set_index("val_id").to_crs(32651), g.to_crs(32651)
for vid in ("V199", "V200"):
    p = pt.loc[vid, "geometry"]
    print(f"\n== {vid} 周边 1.2km 格子 ==")
    for _, c in G[G.geometry.distance(p) <= 1200].iterrows():
        cid = int(c["cell_id"]); n = poi[poi["cell_id"] == cid]
        print(f"  cell {cid}: {'已扫' if cid in done else '未扫'} | {c['area_ha']:.1f}ha | 表内 POI {len(n)}"
              f"(mall {int((n['kind']=='mall').sum())}, hotel {int((n['kind']=='hotel').sum())})")