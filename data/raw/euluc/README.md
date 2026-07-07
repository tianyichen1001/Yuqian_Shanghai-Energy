# EULUC-China 2.0 — Shanghai Clip

## Source

**Dataset**: Essential Urban Land Use Categories in China (EULUC-China 2.0), Version v2  
**Reference**: Li, Z. et al. (2025). Enhanced mapping of essential urban land use categories in China (EULUC-China 2.0): integrating multimodal deep learning with multisource geospatial data. *Science Bulletin*, 70(18), 3029-3041. DOI: [10.1016/j.scib.2025.07.006](https://doi.org/10.1016/j.scib.2025.07.006)  
**Data DOI**: [10.5281/zenodo.15180905](https://doi.org/10.5281/zenodo.15180905)  
**License**: CC BY 4.0  
**Original file MD5**: `2bb69e031a8c7829dd94576c93e3408b` (`EULUC_China_20.gpkg`, 3.1 GB)

## This clip

Full national dataset (~2.29 M parcels) clipped to Shanghai official municipal boundary (GADM 4.1, `NAME_1 == "Shanghai"`).

- **Parcels**: 55,124
- **CRS**: EPSG:4326 (WGS84)
- **Schema**: `Class` (int8) + `geometry` (MultiPolygon)
- **Area coverage**: 4,267.8 km² of Shanghai's ~6,340 km² administrative area (67%); remaining 33% = water, roads, and unclassified space not in the EULUC framework
- **File**: `euluc_shanghai_2022.gpkg`, 103 MB
- **File MD5**: `368c95d555fb3ef7ee0372b7b5d82de9`

## Storage

Due to the 100 MB single-file limit on GitHub, the binary GPKG is stored in the private companion repository `Yuqian_Shanghai-Energy-data` (git tree, main branch), following §4.6 cloud data channel. Retrieve via dual-repo Codespaces session and `git pull`.

## Class distribution (Shanghai official boundary)

| Class | Level-II | Parcels | Area (km²) |
|------:|---|-------:|---------:|
| 0 | Residential | 22,577 | 1,093.1 |
| 1 | Business office | 2,869 | 96.0 |
| 2 | Commercial service | 1,468 | 30.5 |
| 3 | Industrial | 4,786 | 812.9 |
| 4 | Transportation station | 987 | 15.3 |
| 5 | Airport facilities | 24 | 26.9 |
| 6 | Administrative | 2,233 | 48.7 |
| 7 | Educational | 2,332 | 91.9 |
| 8 | Medical | 784 | 20.1 |
| 9 | Sport and cultural | 836 | 44.6 |
| 10 | Park and greenspace | 16,228 | 1,987.8 |

Class code definitions: see `data/reference/euluc_class_mapping.csv`.

## Cross-validation with in-house validation set (n=156, §7.12)

Spatial join of 156 manually-annotated Shanghai buildings against EULUC parcels:

- **Match rate**: 136/156 (87%); 20 unmatched cluster in Lingang (post-2022 construction, EULUC vintage is 2022)
- **Single-function agreement** (residential/office/healthcare/education): 60–77% at the archetype level
- **Complex-function disagreement** (mixed_use, shopping_mall): <10% agreement at the archetype level

**Root cause**: EULUC is *parcel-level land use* while our archetypes are *building-level function*. Complex-use buildings (podium+tower) are inherently mis-cast by any parcel-level classifier — the parcel gets tagged by its dominant function (typically the tower's use), and the podium function is lost.

## Downstream use (Module A6)

- **Reliable EULUC prior** for archetypes: `residential` (Class 0), `office` (Class 1), `government_office` (Class 6), `education` (Class 7), `healthcare` (Class 8), `sport/culture` (Class 9)
- **POI seeding required to resolve** (Module A3): `shopping_mall` and `hotel` (both scatter across Classes 0/1/2), `mixed_use` (subset of Class 1)
- Class 3 (Industrial), Class 10 (Park/greenspace) are outside the 14-archetype pipeline

## Ingestion snippet

```python
import geopandas as gpd
euluc = gpd.read_file("data/raw/euluc/euluc_shanghai_2022.gpkg", engine="pyogrio")
# CRS = EPSG:4326; Class dtype = int8; use data/reference/euluc_class_mapping.csv for labels
```
