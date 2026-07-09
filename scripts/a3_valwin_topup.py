#!/usr/bin/env python3
"""A3 验证窗口 060000 定向补抓 + mall 门槛重裁。护栏 600,预计 150-400 请求。"""
import os, sys, glob, json, time, math
import requests, pandas as pd, geopandas as gpd

KEY = os.environ.get("AMAP_KEY") or sys.exit("先 export AMAP_KEY")
REPO = "/workspaces/Yuqian_Shanghai-Energy"
URL, OUT = "https://restapi.amap.com/v3/place/polygon", f"{REPO}/data/raw/poi/a3_valwin_shop.jsonl"
BUDGET, PAGE_CAP, NAP = 600, 8, 0.5

_A, _EE = 6378245.0, 0.00669342162296594323
def _tl(x, y, lat=True):
    if lat: r = -100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*math.sqrt(abs(x))
    else:   r = 300+x+2*y+0.1*x*x+0.1*x*y+0.1*math.sqrt(abs(x))
    r += (20*math.sin(6*x*math.pi)+20*math.sin(2*x*math.pi))*2/3
    a, b = (y, y/3) if lat else (x, x/3)
    r += (20*math.sin(a*math.pi)+40*math.sin(b*math.pi))*2/3
    a, b = (y/12, y/30) if lat else (x/12, x/30)
    r += ((160 if lat else 150)*math.sin(a*math.pi)+(320 if lat else 300)*math.sin(b*math.pi))*2/3
    return r
def wgs2gcj(lng, lat):
    dlat, dlng = _tl(lng-105, lat-35, True), _tl(lng-105, lat-35, False)
    rl = lat/180*math.pi; m = 1-_EE*math.sin(rl)**2; s = math.sqrt(m)
    return lng+(dlng*180)/(_A/s*math.cos(rl)*math.pi), lat+(dlat*180)/((_A*(1-_EE))/(m*s)*math.pi)
def gcj2wgs(lng, lat):
    gl, gt = wgs2gcj(lng, lat); return lng-(gl-lng), lat-(gt-lat)

vf = [f for f in glob.glob(f"{REPO}/data/**/*.csv", recursive=True) if "valid" in f.lower()][0]
v = pd.read_csv(vf); va = v[v["status"] == "annotated"]
vg = gpd.GeoDataFrame(va, geometry=gpd.points_from_xy(va["lon"], va["lat"]), crs=4326)
grid = gpd.read_file(f"{REPO}/data/reference/a3_scan_grid.gpkg", engine="pyogrio")
j = gpd.sjoin(vg, grid[["cell_id", "geometry"]], predicate="within", how="inner")
cells = sorted(set(int(c) for c in j["cell_id"]))
print(f"annotated 落格 {len(j)}/{len(va)},去重格子 {len(cells)} 个;补抓 060000(护栏 {BUDGET})")

req = 0
def amap(params):
    global req
    for _ in range(3):
        try: r = requests.get(URL, params=params, timeout=15).json()
        except Exception: time.sleep(1.5); continue
        req += 1
        if r.get("status") == "1": time.sleep(NAP); return r
        if "QPS" in str(r.get("info", "")).upper(): time.sleep(2); continue
        return r
    return None

rows, out = [], open(OUT, "w", encoding="utf-8")
for k, cid in enumerate(cells, 1):
    if req >= BUDGET: print("触护栏,安全停"); break
    geom = grid.loc[grid["cell_id"] == cid, "geometry"].iloc[0]
    x0, y0, x1, y1 = geom.bounds
    pts = [wgs2gcj(x, y) for x, y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0))]
    poly = "|".join(f"{a:.6f},{b:.6f}" for a, b in pts)
    j1 = amap({"key": KEY, "polygon": poly, "types": "060000", "offset": 25, "page": 1, "extensions": "base"})
    if not j1 or j1.get("status") != "1":
        print(f"  cell {cid}: 失败 {j1 and j1.get('info')}"); continue
    got = list(j1.get("pois", []))
    pages = min(max(math.ceil(int(j1.get("count", 0))/25), 1), PAGE_CAP)
    for p in range(2, pages+1):
        jp = amap({"key": KEY, "polygon": poly, "types": "060000", "offset": 25, "page": p, "extensions": "base"})
        if jp and jp.get("status") == "1": got += jp.get("pois", [])
        else: break
    for p in got:
        lg, lt = map(float, p.get("location", "0,0").split(","))
        wx, wy = gcj2wgs(lg, lt)
        rec = {"id": p.get("id"), "name": p.get("name"), "typecode": p.get("typecode"),
               "cell_id": cid, "wgs_lng": round(wx, 6), "wgs_lat": round(wy, 6)}
        rows.append(rec); out.write(json.dumps(rec, ensure_ascii=False)+"\n")
    if k % 10 == 0: print(f"  {k}/{len(cells)} 格 | 请求 {req}")
out.close()
sh = pd.DataFrame(rows).drop_duplicates("id")
print(f"补抓完成:{req} 请求,{len(sh)} 个去重 060000 POI → {OUT}")

main = pd.read_csv(f"{REPO}/data/raw/poi/a3_pois_clean.csv")
mm = main[main["kind"] == "mall"]
mg = gpd.GeoDataFrame(mm, geometry=gpd.points_from_xy(mm["wgs_lng"], mm["wgs_lat"]), crs=4326).to_crs(32651)
sg = gpd.GeoDataFrame(sh, geometry=gpd.points_from_xy(sh["wgs_lng"], sh["wgs_lat"]), crs=4326).to_crs(32651) if len(sh) else None
mp = j[j["archetype"].astype(str).str.contains("mall", case=False, na=False)].to_crs(32651)
print("\n== mall 门槛重裁(A:mall级≤150m 或 B:060000≤100m)==")
ok = 0
for _, r in mp.iterrows():
    dm = mg.distance(r.geometry).min() if len(mg) else 9e9
    ds = sg.distance(r.geometry).min() if sg is not None and len(sg) else 9e9
    hit = dm <= 150 or ds <= 100; ok += hit
    print(f"  {r['val_id']}: mall级 {dm:.0f}m | 060000 {ds:.0f}m → {'✔' if hit else '✘'}")
print(f"\n在格 mall:{ok}/{len(mp)};V199/V200 网格外,记盲区案随 8 月卡处理")