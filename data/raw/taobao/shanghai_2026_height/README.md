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
| `height` | float (m) | 4 – 415 m | Building height in meters. **Physically plausible** (Shanghai Tower 632m, Jin Mao 421m). |
| `Area` | float (m²) | 60 – 2000+ | Footprint area in m². **Bonus** — pre-computed, avoids geometry computation in Module A. |
| `ep` | int | sampled = 6 | **Meaning unconfirmed** — possibly building type code or plot ratio. To be clarified during Module A or via vendor follow-up. |
| `district` | string (Chinese) | 16 districts | **DBF encoding issue**: read with `encoding='gbk'` (fallback `'gb18030'`). WPS displays garbled by default. |

## QC Notes

- ✅ CRS confirmed WGS84
- ✅ Feature count 843,063 — consistent with all-16-districts coverage (vs 2023 central-only 412,100)
- ✅ Height range [4, 415] m — physically plausible (max < Shanghai Tower 632m)
- ✅ Area field present — no need for separate geometry computation
- ✅ District field present — no need for spatial join to admin boundaries
- ⚠️ `district` requires `encoding='gbk'` when reading (DBF encoding not auto-detected)
- ⚠️ `ep` field meaning unconfirmed — preserve in pipeline but do not depend on for archetype inference

## Module A Ingestion Rules

- **Read syntax:**
```python
  gdf = gpd.read_file("path/to/2026 Building.shp", encoding="gbk")
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
