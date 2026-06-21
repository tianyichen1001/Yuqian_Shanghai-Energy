# Shanghai Building Footprints — 2023, Central Districts (with Storey Counts)

## Provenance

- **Source:** Commercial vendor via Taobao（淘宝代购）
- **Acquired:** 2026-06-21
- **License:** Commercial dataset; redistribution not permitted. Held locally only.

## Specification

| Attribute | Value |
|---|---|
| Coverage | Shanghai central urban area (市区) |
| Reference year | 2023 |
| File format | ESRI Shapefile (.shp + .shx + .dbf + .prj) |
| CRS | WGS84 (EPSG:4326) — verified via .prj |
| Feature count | 412,100 buildings |
| File size | 76 MB (uncompressed) |
| MD5 (.shp) | `674A7662AF9E36992D04F7494D3203BA` |

## Attributes

| Column | Type | Range | Notes |
|---|---|---|---|
| `FLOOR` | int | 2 – 236 | Storey count. **236 is physically implausible** — Shanghai Tower (city's tallest) has 128 floors. See QC Notes. |

## QC Notes

- ✅ CRS confirmed WGS84
- ✅ Feature count 412,100 (~67% of Shanghai all-city 2019 baseline of ~613k, consistent with central-only coverage)
- ✅ FLOOR min=2 (1-storey buildings filtered by vendor)
- ⚠️ **FLOOR max=236 is an outlier** (max physical value = 128 floors / Shanghai Tower). Outlier rate estimated <0.1% (vendor data noise).
- ⚠️ Single-attribute dataset (no building type / use / name). Function will be inferred via POI seeding in Module A.

## Module A Ingestion Rules

- **Field name to use:** `FLOOR` (uppercase)
- **Outlier filter:** `df.loc[df["FLOOR"] > 130, "FLOOR"] = pd.NA` then impute via height (from 2026 dataset) or POI
- **Use case:** **Calibration set** for Height→Floor empirical layer-height distribution derivation, used on the 2026 all-district dataset

## Storage

- **Repo:** this directory contains only README (per SOP, large binaries gitignored)
- **Local path:** `E:\Energy\Yuqian_Shanghai_Energy_data\2023 Building\`

## Cross-Reference

- Companion dataset: `data/raw/taobao/shanghai_2026_height/` — primary (all-district, height-labeled)
- This dataset serves as cross-validation for Height→Floor inference accuracy
