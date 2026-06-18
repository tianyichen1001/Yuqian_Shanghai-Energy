# Module A — Data Acquisition

Corresponds to the **Data Acquisition** section of the paper.

## Inputs (read from `data/raw/`)

| Subdirectory | Source | Purpose |
|---|---|---|
| `taobao/` | Commercial Taobao building dataset (~80 RMB) | Primary footprints + storey count |
| `osm/` | OpenStreetMap via Overpass API | Fallback footprints |
| `ms_buildings/` | Microsoft Global ML Building Footprints | Fallback footprints |
| `cnbh/` | CNBH-10m or 3D-GloBFP raster / vector | Fallback building height |
| `euluc/` | EULUC-China land-use | Functional context, urban-block boundary |
| `taobao/poi/` or `amap/` | Taobao bulk export or Amap API | POI for archetype seeding |

## Outputs (written to `data/interim/` and `outputs/geojson/`)

| Path | Format | Description |
|---|---|---|
| `data/interim/buildings_unified.geojson` | GeoJSON | All footprints in WGS84 (EPSG:4326) with cleaned geometries |
| `data/interim/poi_unified.geojson` | GeoJSON | POIs in WGS84 with normalized category strings |
| `outputs/geojson/module_a_master.geojson` | GeoJSON | One row per building, seeded archetype label (where available), confidence flag |

## Key sub-modules (to be implemented)

| File | Responsibility |
|---|---|
| `crs.py` | GCJ-02 → WGS84 transformation; EPSG handling |
| `loaders.py` | Per-source loaders (Taobao, OSM, MS, EULUC, CNBH) |
| `clean.py` | Geometry validity, deduplication, multipart resolution |
| `seed.py` | POI → archetype seeding via `poi_mapping.yaml` |

## Hard constraints

- Apply GCJ-02 → WGS84 **before** any spatial join.
- Do not write final archetypes here — Module A only seeds high-confidence
  labels. Module B does the inference for the rest.
- Do not auto-populate `config/poi_mapping.yaml` (see `CLAUDE.md`).
