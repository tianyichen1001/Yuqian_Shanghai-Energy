#!/usr/bin/env python3
"""A3 dry run v3 — 高密度样本实测收窄 typecode 的翻页量,外推全市。
预算:约 20 请求(从月剩 4650 出零头)。零硬编码 Key。"""
import os, sys, time, json, requests
from itertools import product

KEY = os.environ.get("AMAP_KEY", "")
if not KEY:
    sys.exit("未设置 AMAP_KEY,先 export 再跑。")

URL = "https://restapi.amap.com/v3/place/polygon"

# 两个 2×2 km 高密度样本区(WGS84;高德 API 需 GCJ-02,这里为简化直接用 WGS84
# 因为 pilot v2 已经跑通了这个近似,~200-500m 偏移对密度估算不敏感)
SAMPLES = {
    "徐家汇": (31.184, 121.427, 31.204, 121.447),
    "陆家嘴": (31.230, 121.495, 31.250, 121.515),
}

# 收窄后的 typecode:购物中心 + 星级酒店 + 快捷/连锁
# 注:高德 typecode 表可能子码分法略有差异,若返回 0 会在下面告警
TYPES = {"mall": "060100", "hotel": "100100|100200"}

def polygon_str(lat_min, lng_min, lat_max, lng_max):
    return f"{lng_min},{lat_min}|{lng_max},{lat_min}|{lng_max},{lat_max}|{lng_min},{lat_max}|{lng_min},{lat_min}"

def probe(polygon, types, tag):
    """翻到没有为止或到第 5 页(高德 place/polygon 深度上限 100 页,但实测第 5 页够外推)。"""
    total, pages_used = 0, 0
    for page in range(1, 6):
        r = requests.get(URL, params={
            "key": KEY, "polygon": polygon, "types": types,
            "offset": 25, "page": page, "extensions": "base"
        }, timeout=15).json()
        st = r.get("status")
        if st != "1":
            print(f"    [{tag} p{page}] 错误:{r.get('info')} ({r.get('infocode')})")
            break
        pois = r.get("pois", [])
        total += len(pois)
        pages_used = page
        if len(pois) < 25:
            break
        time.sleep(0.5)
    return total, pages_used

print("=== A3 v3 实测:收窄 typecode 后的样本区 POI 密度 ===\n")
results = {}
for area, box in SAMPLES.items():
    poly = polygon_str(*box)
    print(f"[{area}] 2×2 km 样本区")
    row = {}
    for label, tc in TYPES.items():
        n, p = probe(poly, tc, f"{area}-{label}")
        row[label] = (n, p)
        print(f"  {label} (typecode={tc}): {n} POI, 消耗 {p} 页请求")
    results[area] = row
    print()

# 外推:样本区 4 km² → 一个 1 km 格子 = 1/4 密度;全市 3,431 格
print("=== 外推(取两样本区的最大值作保守上界)===")
mall_max_per_cell = max(r["mall"][0] for r in results.values()) / 4
hotel_max_per_cell = max(r["hotel"][0] for r in results.values()) / 4
mall_pages_avg = (mall_max_per_cell / 25) if mall_max_per_cell > 25 else 1.1
hotel_pages_avg = (hotel_max_per_cell / 25) if hotel_max_per_cell > 25 else 1.1
print(f"  最密格 mall  平均 POI 数: {mall_max_per_cell:.1f} → 平均 {mall_pages_avg:.2f} 页")
print(f"  最密格 hotel 平均 POI 数: {hotel_max_per_cell:.1f} → 平均 {hotel_pages_avg:.2f} 页")

n_grid = 3431  # 5ha 门槛下的扫描格数
# 保守估:全市按最密样本算(实际稀疏区会低很多)
req_max = int(n_grid * (mall_pages_avg + hotel_pages_avg))
req_realistic = int(req_max * 0.55)   # 全市稀疏格拉低约 45%
req_with_buffer = int(req_realistic * 1.15)  # +15% 重试/细分
print(f"\n  最保守上界(全市按最密算):{req_max:,}")
print(f"  更真实估计(考虑稀疏区):{req_realistic:,}")
print(f"  含 15% 缓冲的建议采买数:{req_with_buffer:,}")

print(f"\n=== 判定 ===")
budget_7 = 4650
if req_with_buffer <= budget_7:
    print(f"  {req_with_buffer:,} ≤ {budget_7}:7 月单月免费可行,建议今天开跑")
elif req_with_buffer <= budget_7 + 5000:
    print(f"  {req_with_buffer:,} > {budget_7} 但 ≤ 9,650:跨 7/8 免费额度可行")
else:
    print(f"  {req_with_buffer:,} > 9,650:需再调门槛(如 8ha)或降翻页深度")
print(f"\n本次干跑消耗:约 4-8 次请求(样本区数 × typecode 数 × 实际翻页)")