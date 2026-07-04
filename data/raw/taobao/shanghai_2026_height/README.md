# Shanghai Building Footprints — 2026, All 16 Districts (with Heights)

## Provenance

- **Source:** Commercial vendor via Taobao（淘宝代购）
- **Acquired:** 2026-06-21
- **License:** Commercial dataset; redistribution not permitted. Held locally only.

## Specification

| Attribute | Value |
|---|---|
| Coverage | Shanghai all 16 districts |
| Reference year | 2026 |
| File format | ESRI Shapefile (.shp + .shx + .dbf + .prj) |
| CRS | WGS84 (EPSG:4326) — verified via .prj |
| Feature count | **843,062** buildings (measured 2026-07-04, DBF header + SHX index + geopandas 三方互证; vendor claimed 843,063 — off by one, 记账笔误) |
| File size | 811 MB (uncompressed) |
| MD5 (.shp) | `ED87E2815EACD525F21E2993DF4C77E2` |
| MD5 (zip, cloud archive) | `81EBFC2BFEC36FD956FE222051B6A9F3` (`shanghai_2026_building.zip`, sha256 与 Release digest 一致) |

## Attributes

| Column | Type | Range | Notes |
|---|---|---|---|
| `height` | int (m) | 4 – 415 m | Building height in meters (integer, 0 nulls; median 8 m). Plausible below ~200 m; **supertall band wholly unreliable** — see QC note (2026-07-04 升级). |
| `Area` | float (m²) | 60 – 2000+ | Footprint area in m². **Bonus** — pre-computed, avoids geometry computation in Module A. |
| `ep` | int | 14 discrete values {1,2,4,6,7,8,9,10,11,12,13,14,18,26} | **分类编码,语义未确认**(疑似高度/体量档位:ep=2 ≈ 约百米以上高楼专属,686 栋,height 中位 112 m)。**不得作为层数使用** — 2026-07-04 三重证据否定层数假设(仅 14 离散值;height/ep 中位 1.33 m,落 2.5–5 m 合理层高区间仅 ~19%;415 m 双塔 ep=2 而非 ≈128/101),复现见 `scripts/ep_investigation.py`。待向供应商核实。 |
| `district` | string (Chinese) | 16 districts | **DBF encoding is UTF-8** (declared in `.cpg`; verified byte-level 2026-07-02). GeoPandas/pyogrio reads it correctly with no `encoding` override — forcing `gbk` garbles it. WPS displays garbled because it ignores `.cpg`. |

## QC Notes

- ✅ CRS confirmed WGS84 (EPSG:4326, re-verified 2026-07-04 via geopandas)
- ✅ Feature count **843,062** (measured 2026-07-04; vendor claimed 843,063, off by one — DBF header 与 SHX 索引互证,采信实测值) — consistent with all-16-districts coverage (vs 2023 central-only 412,100)
- ⚠️ **Height 顶端失真(2026-07-04 升级说明,取代 07-02 旧记载)**:不仅存在 415 m 截断(恰 2 栋 height=415,均浦东、ep=2,具体身份未锁定),且金茂大厦(实际 420.5 m)**未出现在 ≥410 区间**;浦东最高梯队仅 385 / 361 / 351 —— **超高层段高度整体不可信**,不限于个别地标。Module C 前需建立超高层人工核对名单,对名单内建筑逐栋替换实测高度
- ⚠️ 脏点记录:徐汇区 height=388(疑似徐家汇中心 T1)的 **ep=6**,与超高层带 ep=2 的模式不符(top 20 中 19 栋均 ep=2),Module A 清洗时单独标记复核
- ✅ Area field present — no need for separate geometry computation
- ✅ District field present — no need for spatial join to admin boundaries (16 区齐全,无脏值)
- ✅ `district` reads correctly with UTF-8 (per `.cpg`); do **not** pass `encoding='gbk'`
- ⚠️ `ep` 为 14 值分类编码(见 Attributes 表)— preserve in pipeline; **不得作层数**;archetype 推断不得依赖,待供应商核实语义

## Module A Ingestion Rules

- **Read syntax:**
```python
  gdf = gpd.read_file("path/to/2026 Building.shp")  # UTF-8 attributes per .cpg — no encoding override
```
- **Field name to use:** `height` (lowercase)
- **Storey inference:** `floor = round(height / layer_height_by_archetype)`. Use GB 50352-2019 defaults initially, refine using empirical layer-height distribution derived from cross-validation with 2023 dataset
- **Bonus fields:**
  - `Area` → directly use as footprint area
  - `district` → directly group_by, skip admin spatial join

## Storage

- **Repo:** this directory contains only README (per SOP, large binaries gitignored)
- **Cloud archive (正式通道,2026-07-04 定案):** private data repo `Yuqian_Shanghai-Energy-data` git 树 `shanghai_2026_building.zip`(main;另存 Release `data-v1` 附件),会话内 `git pull` 后按 zip MD5 对暗号、解压至本目录
- **Local path:** `E:\Energy\Yuqian_Shanghai_Energy_data\2026 Building\`

## Cross-Reference

- Companion dataset: `data/raw/taobao/shanghai_2023_floor/` — 2023 central, storey-labeled, used for Height→Floor calibration
- **This is the PRIMARY dataset** for Module A → C pipeline
