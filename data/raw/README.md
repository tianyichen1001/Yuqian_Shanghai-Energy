# `data/raw/` — Immutable Input Layout

> Everything under `data/` is gitignored. This README is the exception so
> reviewers know what each subdirectory expects.

Each subdirectory below holds raw, never-edited inputs from a single source.
Cleaned / unified outputs live in `data/interim/`; feature tables for ML and
simulation live in `data/processed/`.

## Subdirectories

### `taobao/`
- **Source:** Taobao commercial building dataset (~80 RMB).
- **Contents:** Building footprints (shapefile or GeoJSON) with storey count
  and approximate height. CRS: GCJ-02 — **must be reshifted to WGS84**
  before any spatial join.
- **Acquisition:** Search Taobao for "全国建筑轮廓数据" + "上海"; vendors
  typically ship a `.zip` containing `.shp` / `.dbf` / `.prj`.
- **Expected files:**
  - `shanghai_buildings.shp` (+ companion files)
  - optional `shanghai_buildings_levels.csv` keyed by FID

### `taobao/poi/` or `amap/`
- **Source:** Taobao POI bulk export, or Amap (Gaode) Web Service API.
- **Contents:** Points of Interest with semicolon-delimited `type` strings
  (e.g., `"餐饮服务;中餐厅;综合酒楼"`). CRS: GCJ-02.
- **Expected files:** `shanghai_poi.csv` or `.geojson` with columns
  `name, type, lng, lat`.

### `osm/`
- **Source:** OpenStreetMap via the Overpass API.
- **Contents:** Building footprints used as fallback where Taobao coverage
  is sparse. CRS: WGS84 (EPSG:4326).
- **Acquisition example:**
  ```
  [out:json][bbox:30.65,120.85,31.90,122.20];
  way["building"];
  out body geom;
  ```
- **Expected file:** `osm_shanghai_buildings.geojson`

### `ms_buildings/`
- **Source:** Microsoft Global ML Building Footprints
  (https://github.com/microsoft/GlobalMLBuildingFootprints).
- **Contents:** Building footprints; no height. CRS: WGS84.
- **Expected file:** `ms_buildings_shanghai.geojson`

### `euluc/`
- **Source:** EULUC-China (Essential Urban Land Use Categories of China)
  via Tsinghua / Zenodo.
- **Contents:** Urban-block polygons with land-use codes. CRS: CGCS2000.
- **Expected file:** `euluc_shanghai.geojson`

### `cnbh/`
- **Source:** CNBH-10m building-height raster, or 3D-GloBFP vector.
- **Contents:** 10 m resolution building-height raster, used as fallback
  height when Taobao height is missing.
- **Expected files:** `cnbh10m_shanghai.tif` or `globfp_shanghai.geojson`.

### `epd_oneclick/`
- **Source:** One Click LCA China EPD database (licensed).
- **Contents:** Per-material A1-A3 / A4 / A5 GWP factors with statistics.
- **Expected file:** `oneclick_china_epd.csv`

### `benchmark/`
- **Source:** Wang H. et al., *Green Building*, 2026(1); Tsinghua Building
  Energy Annual Reports; GB/T 51161-2016.
- **Contents:** Reference EUI tables used as calibration ground truth.
- **Expected files:**
  - `wang_2026_public_monthly.csv`
  - `tsinghua_residential_annual.csv`
  - `gbt_51161_thresholds.csv`

## Conventions

- Filenames are lowercase snake_case.
- Each subdirectory may contain a `PROVENANCE.txt` with the exact URL,
  download date, and license, but this is not mandatory.
- No raw data files are committed. Only this README and any
  `PROVENANCE.txt` files are tracked.
