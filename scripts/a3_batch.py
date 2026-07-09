#!/usr/bin/env python3
"""A3 正式抓取器(合并 typecode 版)
  预检: python scripts/a3_batch.py --preflight        (~10 请求,输出 GO/NO-GO)
  正跑: python scripts/a3_batch.py --run --threshold 5 (断点续传/预算护栏/日限自停)
"""
import os, sys, json, time, math, glob, argparse
import requests, pandas as pd, geopandas as gpd
from shapely.geometry import box as sbox

REPO = "/workspaces/Yuqian_Shanghai-Energy"
EULUC, GRID = f"{REPO}/data/raw/euluc/euluc_shanghai_2022.gpkg", f"{REPO}/data/reference/a3_scan_grid.gpkg"
META, OUTD = f"{REPO}/data/reference/a3_cell_meta.csv", f"{REPO}/data/raw/poi"
RAW, DONE, CTR = f"{OUTD}/a3_pois_raw.jsonl", f"{OUTD}/a3_done_cells.txt", f"{OUTD}/a3_req_counter.txt"
URL, TYPES, PAGE_CAP, NAP = "https://restapi.amap.com/v3/place/polygon", "060100|100100|100200", 8, 0.45
KEY = os.environ.get("AMAP_KEY", "") or sys.exit("先 export AMAP_KEY")

class DailyLimit(Exception): pass
REQ = int(open(CTR).read().strip()) if os.path.exists(CTR) else 0
def save_ctr():
    os.makedirs(OUTD, exist_ok=True); open(CTR, "w").write(str(REQ))

# ---- GCJ-02 <-> WGS84 ----
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

def amap(poly, page):
    global REQ
    for _ in range(4):
        try: j = requests.get(URL, params={"key": KEY, "polygon": poly, "types": TYPES,
                              "offset": 25, "page": page, "extensions": "base"}, timeout=15).json()
        except Exception: time.sleep(1.5); continue
        REQ += 1
        if j.get("status") == "1": time.sleep(NAP); return j
        info = (j.get("info") or "") + str(j.get("infocode") or "")
        if "QPS" in info.upper(): time.sleep(2); continue
        if "DAILY" in info.upper() or j.get("infocode") in ("10044", "10003"): raise DailyLimit(info)
        time.sleep(NAP); return j
    return None

def fetch_cell(geom):
    x0, y0, x1, y1 = geom.bounds
    pts = [wgs2gcj(x, y) for x, y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0))]
    poly = "|".join(f"{x:.6f},{y:.6f}" for x, y in pts)
    j = amap(poly, 1)
    if not j or j.get("status") != "1": return None, 1, False
    cnt, pois = int(j.get("count", 0)), list(j.get("pois", []))
    pages = min(max(math.ceil(cnt/25), 1), PAGE_CAP)
    for p in range(2, pages+1):
        j2 = amap(poly, p)
        if j2 and j2.get("status") == "1": pois += j2.get("pois", [])
        else: break
    return pois, pages, cnt > PAGE_CAP*25

def slim(p):
    lg, lt = map(float, p.get("location", "0,0").split(","))
    wx, wy = gcj2wgs(lg, lt)
    return {"id": p.get("id"), "name": p.get("name"), "typecode": p.get("typecode"),
            "addr": p.get("address"), "gcj": f"{lg},{lt}", "wgs": f"{wx:.6f},{wy:.6f}"}

def load_meta():
    if os.path.exists(META): return pd.read_csv(META)
    print("首算每格目标用地面积(1-3 分钟)...")
    tgt = gpd.read_file(EULUC, engine="pyogrio")
    tgt = tgt[tgt["Class"].isin([0,1,2])].to_crs(32651)
    grid = gpd.read_file(GRID, engine="pyogrio").to_crs(32651)
    it = gpd.overlay(grid, tgt[["Class","geometry"]], how="intersection", keep_geom_type=True)
    it["a"] = it.geometry.area/1e4
    m = it.groupby("cell_id").agg(area_ha=("a","sum")).reset_index()
    m["dense"] = m["cell_id"].isin(set(it.loc[it["Class"].isin([1,2]),"cell_id"]))
    m.to_csv(META, index=False); return m

def preflight(remaining):
    print(f"=== 预检(合并 typecode:{TYPES})===\n累计已用 {REQ},本月余额按 {remaining} 算")
    hot = {"徐家汇": (121.432,31.191), "陆家嘴": (121.501,31.238), "南京西路": (121.455,31.230)}
    extras = []
    for name, (lng, lat) in hot.items():
        g = sbox(lng-0.0053, lat-0.0045, lng+0.0053, lat+0.0045)
        pois, pages, cap = fetch_cell(g)
        if pois is None: print(f"[{name}] 请求失败"); continue
        malls = sum(1 for p in pois if str(p.get("typecode","")).startswith("0601"))
        print(f"[{name}] 合并抓到 {len(pois)} POI(商场级 {malls}),{pages} 页{',触顶!' if cap else ''}")
        extras.append(max(pages-1, 0))
    if not extras: print("预检失败,检查 Key/网络"); return
    ex = sum(extras)/len(extras)
    meta = load_meta()
    print(f"\n最热格平均额外翻页 {ex:.1f},全市密集格按其 50% 计:")
    go = None
    for th in (5, 8, 10):
        k = meta[meta.area_ha >= th]; nd = int(k["dense"].sum())
        est = int((len(k) + nd*ex*0.5) * 1.12)
        ok = est <= remaining - REQ - 150
        print(f"  门槛{th:>2}ha:{len(k):,} 格(密集 {nd:,})→ 含缓冲约 {est:,} 请求 {'✔可行' if ok else '✘超'}")
        if ok and go is None: go = (th, est)
    # 验证集反查
    vf = [f for f in glob.glob(f"{REPO}/data/**/*.csv", recursive=True) if "valid" in f.lower()]
    if vf and go:
        try:
            v = pd.read_csv(vf[0])
            latc = next(c for c in v.columns if c.lower() in ("lat","latitude","纬度","y"))
            lngc = next(c for c in v.columns if c.lower() in ("lng","lon","longitude","经度","x"))
            vg = gpd.GeoDataFrame(v, geometry=gpd.points_from_xy(v[lngc], v[latc]), crs=4326)
            grid = gpd.read_file(GRID, engine="pyogrio")
            drop = grid.merge(meta[meta.area_ha < go[0]], on="cell_id")
            hits = gpd.sjoin(vg, drop, predicate="within")
            key = v.astype(str).apply(lambda r: r.str.contains("mall|hotel|商场|酒店|宾馆", case=False)).any(axis=1)
            print(f"\n验证集反查({os.path.basename(vf[0])}):落入弃扫格 {len(hits)} 栋,其中商场/酒店类 {int(key[hits.index].sum())} 栋(须为 0)")
        except Exception as e: print(f"\n验证集反查跳过({e})")
    else: print("\n未找到验证集 csv,反查跳过——不阻塞开跑,事后补验")
    if go: print(f"\n>>> GO:直接运行 python scripts/a3_batch.py --run --threshold {go[0]}")
    else:  print("\n>>> NO-GO:三档全超,把本输出贴回对话")

def run(th, budget):
    meta = load_meta()
    grid = gpd.read_file(GRID, engine="pyogrio").merge(meta[meta.area_ha >= th], on="cell_id")
    grid = grid.sort_values(["dense","area_ha"], ascending=[False,False])
    done = set(int(x) for x in open(DONE).read().split()) if os.path.exists(DONE) else set()
    todo = grid[~grid["cell_id"].isin(done)]
    os.makedirs(OUTD, exist_ok=True)
    print(f"门槛{th}ha:共 {len(grid):,} 格,已完成 {len(done):,},待扫 {len(todo):,};预算护栏 {budget:,}(已用 {REQ:,})")
    t0, n = time.time(), 0
    raw, dn = open(RAW,"a",encoding="utf-8"), open(DONE,"a")
    try:
        for _, r in todo.iterrows():
            if REQ >= budget: print(f"\n触及护栏 {budget:,},安全停车;下次同命令续跑。"); break
            pois, pg, cap = fetch_cell(r.geometry)
            if pois is None: continue
            raw.write(json.dumps({"cell_id": int(r.cell_id), "capped": cap,
                      "pois": [slim(p) for p in pois]}, ensure_ascii=False)+"\n"); raw.flush()
            dn.write(f"{int(r.cell_id)}\n"); dn.flush(); n += 1
            if n % 50 == 0:
                eta = (len(todo)-n)*(time.time()-t0)/n/60
                print(f"  {n}/{len(todo)} 格 | 请求 {REQ:,} | ETA {eta:.0f} 分钟")
    except DailyLimit as e:
        print(f"\n高德日限触发({e}):进度已存,明早重跑同一命令自动续。")
    except KeyboardInterrupt:
        print("\n手动中断:进度已存,同命令续跑。")
    finally:
        raw.close(); dn.close(); save_ctr()
        print(f"本次新增 {n} 格,累计请求 {REQ:,};原始数据 → {RAW}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight", action="store_true"); ap.add_argument("--run", action="store_true")
    ap.add_argument("--threshold", type=float, default=5); ap.add_argument("--budget", type=int, default=4450)
    ap.add_argument("--remaining", type=int, default=4600)
    a = ap.parse_args()
    try:
        if a.preflight: preflight(a.remaining)
        elif a.run: run(a.threshold, a.budget)
        else: print(__doc__)
    finally: save_ctr()