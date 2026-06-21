# EULUC-China 2.0 — Essential Urban Land Use Categories

## Source
- **Dataset:** EULUC-China 2.0: Essential Urban Land Use Categories Map across China for 2022
- **Authors:** Li Ziming, Chen Bin (and others)
- **Publication:** Wang et al. 2025, Science Bulletin
- **DOI:** 10.5281/zenodo.15180905
- **URL:** https://zenodo.org/records/15180905
- **Download link:** https://zenodo.org/records/15180905/files/EULUC_China_20.gpkg?download=1

## File on local disk (gitignored — NOT in this repo)
- **Filename:** `EULUC_China_20.gpkg`
- **Size:** 3.1 GB
- **MD5:** `2bb69e031a8c7829dd94576c93e3408b`
- **Format:** GeoPackage (GPKG) — read with geopandas, GDAL, or QGIS
- **Time coverage:** 2022
- **Spatial coverage:** All cities in China (impervious areas only)
- **Local path on owner's machine:** `E:\Energy\Yuqian_Shanghai_Energy_data\EULUC_China_20.gpkg`

> Note: other contributors will store the file under their own local path. Always re-verify the MD5 above against any local copy before use.

## License
**CC BY 4.0** — commercial use allowed, attribution required.
Cite: Wang Z. et al. 2025, Science Bulletin (EULUC-China 2.0).

## Classification system (Level-II, 11 classes)

| Class value | Level-II name | Maps to project archetype |
|---|---|---|
| 0 | Residential | residential_mid_rise / high_rise (secondary split by floor count) |
| 1 | Business office | office |
| 2 | Commercial service | shopping_mall + hotel (secondary split) |
| 3 | Industrial | other_public |
| 4 | Transportation stations | transportation |
| 5 | Airport facilities | transportation |
| 6 | Administrative | government_office |
| 7 | Educational | education |
| 8 | Medical | healthcare |
| 9 | Sport and cultural | sports + culture (secondary split) |
| 10 | Park and greenspace | (excluded — non-building) |

**Note:** `exhibition` and `mixed_use` archetypes have no direct EULUC equivalent;
they are inferred at Module B from POI + geometry. EULUC serves as a prior signal,
not ground truth.

## Shanghai extraction (deferred to Module A)
Full national GPKG kept local (too large for Git, 3.1 GB > GitHub 100 MB limit).
Shanghai subset to be extracted with geopandas when Module A starts and
committed as `data/raw/euluc/euluc_shanghai_2022.gpkg`.

## Re-download instructions (for future reproducibility)
If the file is lost, re-download from the URL above and verify MD5:

```bash
# Windows PowerShell
Get-FileHash -Algorithm MD5 EULUC_China_20.gpkg

# Mac / Linux
md5 EULUC_China_20.gpkg
```

Expected: `2bb69e031a8c7829dd94576c93e3408b`
