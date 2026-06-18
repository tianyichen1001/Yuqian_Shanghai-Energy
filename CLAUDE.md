# CLAUDE.md — Project Guidance for Claude Code

> Read this first when entering the repository. It captures the non-obvious
> constraints that are not visible from the directory tree alone.

---

## 1. Project Goal

This repository extends the **Buildings.city** framework (Lyu et al.,
*Computers, Environment and Urban Systems*, 2026) — originally developed by
Yuqian Ang's group for North American cities — to a Chinese
hot-summer / cold-winter megacity (Shanghai). The end goal is a fully
reproducible, monthly-calibrated UBEM that produces:

1. Per-building operational energy use intensity (EUI) and end-use breakdown.
2. Per-archetype embodied-carbon distributions (A1–A5).
3. Calibration evidence against the **Wang H. et al., 2026** Shanghai
   monitoring-platform dataset (144-point monthly matrix for public buildings)
   and Tsinghua / GB/T 51161-2016 residential benchmarks.

---

## 2. The Five Modules

| Module | Source dir | What it does |
|---|---|---|
| **A. Data acquisition** | `src/buildings_shanghai/data/` | Reads raw Taobao / OSM / Microsoft / EULUC / CNBH inputs; unifies CRS; cleans geometries; seeds functional labels by POI point-in-polygon. |
| **B. ML archetype inference** | `src/buildings_shanghai/ml/` | Trains a Random Forest (with SMOTE rebalancing) on high-confidence seeded labels using shape features; predicts archetype for every building. |
| **C. EnergyPlus simulation** | `src/buildings_shanghai/simulation/` | Generates per-archetype IDFs via `eppy` / `geomeppy` / `honeybee-energy`; runs batched simulations; parses ESO / SQL output to monthly EUI. |
| **D. Embodied-carbon Monte Carlo** | `src/buildings_shanghai/embodied/` | Samples five-material PDFs (concrete, steel, glass, aluminum, brick) from the One Click LCA China EPD database; 5,000 samples per archetype. |
| **E. Calibration + figures** | `src/buildings_shanghai/calibration/`, `src/buildings_shanghai/viz/` | Dual-track NMBE calibration; produces all paper figures. |

---

## 3. Hard Constraints (do not violate without asking)

1. **Coordinate handling is non-negotiable.** Every spatial input must be
   transformed **GCJ-02 → WGS84** *before* any spatial join. Taobao and Amap
   data are in GCJ-02; OSM and Microsoft footprints are in WGS84; EULUC uses
   CGCS2000. Mixing these will silently misalign buildings to the wrong POIs.
2. **Calibration targets are fixed.** Public-building target is **NMBE ≤ ±10%**
   monthly; residential target is **NMBE ≤ ±20%** annual. Do not relax these
   to make the model pass.
3. **Pure-Python pipeline only.** No Rhino, no Grasshopper, no Ladybug-Tools
   visual scripts. All geometry generation goes through `eppy` / `geomeppy` /
   `honeybee-energy`.
4. **Mixed-use ("综合") is a first-class archetype.** Wang et al. report that
   *综合建筑* accounts for ~22.5% of the monitored floor area in Shanghai. It
   is **not** a residual / edge-case bucket — treat it as a core archetype with
   its own schedules and HVAC parameterization.
5. **No absolute paths.** Use `pathlib.Path` relative to a project root
   resolved at runtime, or paths read from `config/`.
6. **All tunable parameters live in `config/` YAML.** Source code should
   contain no magic numbers for U-values, LPD, occupancy density, schedules,
   or calibration thresholds.

---

## 4. Directory Conventions

```
config/         # YAML only, no Python
data/raw/       # immutable inputs, organized by source (see data/raw/README.md)
data/interim/   # intermediate joins, CRS-unified, cleaned but not feature-engineered
data/processed/ # final ML features, training tables, simulation inputs
outputs/        # everything generated: geojson, sim results, figures, logs
templates/      # one IDF template per archetype, version-controlled
weather/        # EPW + STAT + DDY, gitignored
src/            # importable as `buildings_shanghai.*`
scripts/        # thin argparse wrappers around src/, one per module
notebooks/      # exploration only; final artifacts get refactored into src/
tests/          # pytest, smoke + unit
```

---

## 5. Naming Conventions

- **Archetypes** are lowercase snake_case: `government_office`, `shopping_mall`,
  `residential_high_rise`. The canonical list of 14 lives in
  `config/archetypes.yaml`.
- **CRS strings** use EPSG codes as integers in code (`4326`, `4547`) and as
  strings in config (`"EPSG:4326"`).
- **DataFrame column names** are snake_case. Geometry column is always
  `geometry`.
- **Output files** are namespaced by module: `module_a_master.geojson`,
  `module_b_predictions.parquet`, `module_c_monthly_eui.csv`, etc.

---

## 6. Things NOT to Do

- **Do not auto-populate `config/poi_mapping.yaml`.** The POI category →
  archetype dictionary requires human judgment (Amap has hundreds of subtypes
  with overlapping semantics). Generate a *candidate list* if asked, but the
  final mapping must be reviewed and committed by a human.
- **Do not modify `config/calibration_targets.yaml`** beyond filling in the
  144-point Wang et al. matrix once. Those numbers are the ground truth the
  model is calibrated against — changing them invalidates the calibration.
- **Do not hardcode absolute paths** in source files, notebooks, or scripts.
- **Do not introduce GUI dependencies** (Rhino, Grasshopper, ArcGIS Pro
  Python). The pipeline must run headless inside a 4-core / 8 GB devcontainer.
- **Do not commit `data/`, `outputs/`, `weather/*.epw`, or EnergyPlus run
  artifacts.** The `.gitignore` covers these — do not override with
  `git add -f`.
- **Do not silently downgrade calibration thresholds** if a module fails to
  meet them. Surface the gap, log it, and ask.

---

## 7. When in Doubt

- Configuration question → look in `config/*.yaml`.
- Data layout question → look in `data/raw/README.md`.
- Pipeline-flow question → look in `scripts/run_pipeline.py`.
- Modeling-decision question → ask the human; do not assume.
