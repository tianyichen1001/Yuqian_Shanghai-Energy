#!/usr/bin/env python3
"""A3 QC 分诊 — 14 行逐行:整行字段(查灰行)/ 最近 mall 距离(查阈值)/ 1km 名称模糊匹配(查 typecode 漏)。零配额。"""
import glob, os, re
import pandas as pd, geopandas as gpd

REPO = "/workspaces/Yuqian_Shanghai-Energy"
df = pd.read_csv(f"{REPO}/data/raw/poi/a3_pois_clean.csv")
pg = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.wgs_lng, df.wgs_lat), crs=4326).to_crs(32651)

vf = [f for f in glob.glob(f"{REPO}/data/**/*.csv", recursive=True) if "valid" in f.lower()][0]
v = pd.read_csv(vf)
print(f"验证集: {os.path.basename(vf)},共 {len(v)} 行;列名: {list(v.columns)}\n")

latc = next(c for c in v.columns if c.lower() in ("lat","latitude","纬度","y"))
lngc = next(c for c in v.columns if c.lower() in ("lng","lon","longitude","经度","x"))
ac   = next(c for c in v.columns if v[c].astype(str).str.contains("mall", case=False).any())
sub  = v[v[ac].astype(str).str.contains("mall|商场|购物", case=False, na=False)]
vg   = gpd.GeoDataFrame(sub, geometry=gpd.points_from_xy(sub[lngc], sub[latc]), crs=4326).to_crs(32651)

namecols = [c for c in sub.columns if re.search(r"name|名称|建筑|楼", c, re.I)] or list(sub.columns)
strip = lambda s: re.sub(r"[((].*?[))]|上海市?|广场|购物中心|商场|大厦", "", str(s)).strip()

for idx, b in vg.iterrows():
    print("=" * 72)
    print(f"行 {idx}: " + " | ".join(f"{k}={b[k]}" for k in sub.columns if k not in (latc, lngc, "geometry")))
    malls = pg[pg["kind"] == "mall"]
    dm = malls.distance(b.geometry); j = dm.idxmin()
    print(f"  最近 mall POI: {malls.loc[j,'name']} (typecode={malls.loc[j,'typecode']}) @ {dm.min():.0f} m")
    near = pg[pg.distance(b.geometry) <= 1000]
    toks = [t for t in (strip(b[c]) for c in namecols) if re.search(r"[\u4e00-\u9fff]{2,}", t)]
    hit = near[near["name"].apply(lambda n: any(t in str(n) for t in toks))] if toks else near.iloc[0:0]
    if len(hit):
        for _, m in hit.head(3).iterrows():
            print(f"  1km 名称匹配: {m['name']} | kind={m['kind']} | typecode={m['typecode']} | {b.geometry.distance(m.geometry):.0f} m")
    else:
        print(f"  1km 内无名称匹配(周边共 {len(near)} 个 POI;搜索词={toks[:3]})")