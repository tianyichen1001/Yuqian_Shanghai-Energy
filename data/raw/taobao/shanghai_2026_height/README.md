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
| Feature count | 843,063 buildings |
| File size | 811 MB (uncompressed) |
| MD5 (.shp) | `ED87E2815EACD525F21E2993DF4C77E2` |

## Attributes

| Column | Type | Range | Notes |
|---|---|---|---|
| `height` | float (m) | 4 – 415 m | Building height in meters. Plausible below ~200 m; **supertall tail unreliable** — see QC note (Jin Mao 420.5→415, Shanghai Tower 632 absent). |
| `Area` | float (m²) | 60 – 2000+ | Footprint area in m². **Bonus** — pre-computed, avoids geometry computation in Module A. |
| `ep` | int | sampled = 6 | **Meaning unconfirmed** — possibly building type code or plot ratio. To be clarified during Module A or via vendor follow-up. |
| `district` | string (Chinese) | 16 districts | **DBF encoding is UTF-8** (declared in `.cpg`; verified byte-level 2026-07-02). GeoPandas/pyogrio reads it correctly with no `encoding` override — forcing `gbk` garbles it. WPS displays garbled because it ignores `.cpg`. |

## QC Notes

- ✅ CRS confirmed WGS84
- ✅ Feature count 843,063 — consistent with all-16-districts coverage (vs 2023 central-only 412,100)
- ⚠️ Height range [4, 415] m — **supertall heights unreliable** (validation-set #9 checkpoint 2, 2026-07-02): dataset max 415 is Jin Mao Tower (actual 420.5 m); Shanghai Tower (632 m) and SWFC (492 m) carry wrong heights < 385 m in Lujiazui. Fine below ~200 m as far as observed; do not trust the tail for storey inference of supertalls
- ✅ Area field present — no need for separate geometry computation
- ✅ District field present — no need for spatial join to admin boundaries
- ✅ `district` reads correctly with default encoding (UTF-8 per `.cpg`); do **not** pass `encoding='gbk'`
- ⚠️ `ep` field meaning unconfirmed — preserve in pipeline but do not depend on for archetype inference

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
- **Local path:** `E:\Energy\Yuqian_Shanghai_Energy_data\2026 Building\`

## Cross-Reference

- Companion dataset: `data/raw/taobao/shanghai_2023_floor/` — 2023 central, storey-labeled, used for Height→Floor calibration
- **This is the PRIMARY dataset** for Module A → C pipeline
