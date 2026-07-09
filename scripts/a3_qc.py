#!/usr/bin/env python3
"""A3 QC — 去重 / 类型统计 / capped 检查 / 坐标抽验 / validation 对表 / 清洗落盘"""
import os, json, glob
import pandas as pd, geopandas as gpd

REPO = "/workspaces/Yuqian_Shanghai-Energy"
RAW = f"{REPO}/data/raw/poi/a3_pois_raw.jsonl"
OUT_CSV, OUT_GPKG = f"{REPO}/data/raw/poi/a3_pois_clean.csv", f"{REPO}/data/raw/poi/a3_pois_clean.gpkg"

rows, capped, n_cells = [], [], 0
with open(RAW, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line); n_cells += 1
        if rec.get("capped"): capped.append(rec["cell_id"])
        for p in rec["pois"]:
            wx, wy = map(float, p["wgs"].split(","))
            rows.append({**p, "cell_id": rec["cell_id"], "wgs_lng": wx, "wgs_lat": wy})

df = pd.DataFrame(rows)
print(f"格子记录: {n_cells:,};原始 POI 行: {len(df):,}")
b4 = len(df); df = df.drop_duplicates("id").reset_index(drop=True)
print(f"按 id 去重: {b4:,} → {len(df):,}(跨格重复 {b4-len(df):,} 条)")

df["kind"] = "other"
df.loc[df.typecode.astype(str).str.startswith("0601"), "kind"] = "mall"
df.loc[df.typecode.astype(str).str.startswith(("1001","1002")), "kind"] = "hotel"
print("\n类型分布:"); print(df["kind"].value_counts().to_string())
print(f"\ncapped(翻页触顶)格子: {len(capped)} 个" + (f" → {capped[:20]}" if capped else ",无需补抓"))

print("\n坐标抽验(坐标粘到 Google Maps 卫星图,应落在对应建筑上):")
for name in ("港汇恒隆", "美罗城", "国金中心", "环球港", "静安嘉里"):
    hit = df[df["name"].str.contains(name, na=False)]
    print(f"  {name}: " + (f"{hit.iloc[0]['wgs_lat']:.6f},{hit.iloc[0]['wgs_lng']:.6f}" if len(hit) else "未匹配到该名称(不一定是漏,可能名称写法不同)"))

vf = [f for f in glob.glob(f"{REPO}/data/**/*.csv", recursive=True) if "valid" in f.lower()]
if vf:
    v = pd.read_csv(vf[0])
    latc = next(c for c in v.columns if c.lower() in ("lat","latitude","纬度","y"))
    lngc = next(c for c in v.columns if c.lower() in ("lng","lon","longitude","经度","x"))
    ac = next((c for c in v.columns if v[c].astype(str).str.contains("mall|hotel", case=False).any()), None)
    vg = gpd.GeoDataFrame(v, geometry=gpd.points_from_xy(v[lngc], v[latc]), crs=4326).to_crs(32651)
    pg = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.wgs_lng, df.wgs_lat), crs=4326).to_crs(32651)
    print(f"\nvalidation 对表({os.path.basename(vf[0])},archetype 列: {ac}):")
    for kind, kw in (("mall", "mall|商场|购物"), ("hotel", "hotel|酒店|宾馆")):
        sub = vg[vg[ac].astype(str).str.contains(kw, case=False, na=False)] if ac else vg.iloc[0:0]
        pois = pg[pg["kind"] == kind]; miss = 0
        for _, bd in sub.iterrows():
            d = pois.distance(bd.geometry).min() if len(pois) else 9e9
            if d > 150:
                miss += 1
                print(f"  ✘ {kind} 未命中(最近 POI {d:.0f} m): 行 {bd.name}")
        print(f"  {kind}: {len(sub)-miss}/{len(sub)} 栋在 150m 内有对应 POI")
else:
    print("\n未找到 validation csv,对表跳过")

df.to_csv(OUT_CSV, index=False)
gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.wgs_lng, df.wgs_lat), crs=4326).to_file(OUT_GPKG, driver="GPKG")
print(f"\n清洗表已落盘:\n  {OUT_CSV}\n  {OUT_GPKG}")