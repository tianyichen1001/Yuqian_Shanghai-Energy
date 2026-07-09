#!/usr/bin/env python3
"""A3 微探针 — 12 个未命中验证点,各 ~220m 小框抓全量 060000。预算 ~12 请求。"""
import os, sys, time, math, glob
import requests, pandas as pd

KEY = os.environ.get("AMAP_KEY") or sys.exit("先 export AMAP_KEY")
URL = "https://restapi.amap.com/v3/place/polygon"
MISSED = ["V009","V029","V042","V083","V084","V087","V088","V096","V097","V141","V199","V200"]

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

REPO = "/workspaces/Yuqian_Shanghai-Energy"
vf = [f for f in glob.glob(f"{REPO}/data/**/*.csv", recursive=True) if "valid" in f.lower()][0]
v = pd.read_csv(vf).set_index("val_id")
req = 0
for vid in MISSED:
    r = v.loc[vid]; lat, lng = float(r["lat"]), float(r["lon"])
    glng, glat = wgs2gcj(lng, lat); d = 0.0011
    poly = f"{glng-d:.6f},{glat-d:.6f}|{glng+d:.6f},{glat-d:.6f}|{glng+d:.6f},{glat+d:.6f}|{glng-d:.6f},{glat+d:.6f}|{glng-d:.6f},{glat-d:.6f}"
    j = requests.get(URL, params={"key": KEY, "polygon": poly, "types": "060000",
                                  "offset": 25, "page": 1, "extensions": "base"}, timeout=15).json()
    req += 1
    if j.get("status") != "1":
        print(f"{vid}: 请求失败 {j.get('info')}"); time.sleep(0.6); continue
    pois = j.get("pois", [])
    tags = ", ".join(f"{p.get('name')}({p.get('typecode')})" for p in pois[:4])
    print(f"{vid} [{r['area']}] 全类060000 count={j.get('count','0')}" + (f" → {tags}" if pois else "  ← 框内无购物类 POI"))
    time.sleep(0.6)
print(f"\n消耗 {req} 请求(计入本月余量)")