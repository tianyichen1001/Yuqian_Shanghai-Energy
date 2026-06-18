# Buildings.Shanghai

End-to-end UBEM pipeline for Shanghai: data acquisition → ML archetype inference → EnergyPlus simulation → embodied carbon Monte Carlo → calibration and figures.

---

## 1. Pipeline Modules

The codebase is organized as five sequential modules. Each module reads from the previous module's outputs and writes to a structured location under `outputs/`.

| Module | Purpose | Primary output |
|---|---|---|
| **A. Data Acquisition** | Building footprints (Taobao + OSM + Microsoft ML), POI, land-use; coordinate unification (GCJ-02 → WGS84 → CGCS2000 / UTM 51N); geometry cleaning; functional seeding via point-in-polygon | `outputs/geojson/master.geojson` (one row per building) |
| **B. ML Archetype Inference** | Random Forest classifier trained on high-confidence seeded labels; shape features (footprint, height, levels, perimeter, aspect ratio, compactness, convexity); SMOTE for class imbalance | Predicted archetype + classification probability per building |
| **C. EnergyPlus Simulation** | Per-archetype IDF templates (ASHRAE 5-zone shoebox) generated via `eppy` / `geomeppy` / `honeybee-energy`; HVAC, schedules, and internal gains parameterized from GB 50189, DGJ32, and Wang et al. (2026) clustering; batch execution and output parsing | Monthly EUI and end-use breakdown per archetype × height bin |
| **D. Embodied Carbon Monte Carlo** | EPD-based probability density functions for five materials (concrete, steel, glass, aluminum, brick); A1–A5 lifecycle stages; 5,000 samples per archetype | Mean, median, and 90% confidence intervals per archetype |
| **E. Calibration and Figures** | Dual-track NMBE calibration — public buildings against monthly Wang et al. data (target ±10%), residential against Tsinghua annual reports and GB/T 51161 (target ±20%); generates all figures | Calibration logs + `outputs/figures/` |

---

## 2. Repository Structure

```
.
├── .devcontainer/                  # GitHub Codespaces configuration
│   ├── devcontainer.json
│   └── install_energyplus.sh
├── config/                         # All tunable parameters as YAML
│   ├── shanghai.yaml               # City-level settings (weather, CRS, study area)
│   ├── archetypes.yaml             # 14 archetype definitions and default parameters
│   ├── poi_mapping.yaml            # POI category → archetype dictionary
│   ├── standards.yaml              # GB 50189 / DGJ32 / GB/T 51161 reference values
│   └── calibration_targets.yaml    # Wang et al. 144-point matrix + residential benchmarks
├── data/                           # All git-ignored (see data/raw/README.md)
│   ├── raw/
│   ├── interim/
│   └── processed/
├── src/buildings_shanghai/         # Main pipeline source code
│   ├── data/                       # Module A
│   ├── ml/                         # Module B
│   ├── simulation/                 # Module C
│   ├── embodied/                   # Module D
│   ├── calibration/                # Module E
│   └── viz/                        # Figure generation
├── notebooks/                      # Exploration and figure notebooks
├── templates/                      # EnergyPlus IDF templates (one per archetype)
├── weather/                        # EPW weather files (gitignored)
├── scripts/                        # Entry-point scripts (one per module + full pipeline)
├── tests/                          # Unit tests
├── outputs/                        # Generated results and figures (gitignored)
├── pyproject.toml                  # Python dependencies and project metadata
├── CLAUDE.md                       # Project guidance for Claude Code
└── README.md                       # This file
```

---

## 3. Quick Start (GitHub Codespaces)

1. On the repository page, click `<> Code` → `Codespaces` → `Create codespace on main`.
2. Wait approximately 5 minutes for the container to build. EnergyPlus 25.1, Python 3.11, and all required libraries install automatically based on `.devcontainer/devcontainer.json`.
3. Verify the environment:
   ```bash
   energyplus --version
   python -c "import eppy, geomeppy, honeybee_energy"
   ```
4. Run the first module on a small demo area (Xuhui District):
   ```bash
   python scripts/run_module_a.py --area xuhui
   ```
5. Run the full pipeline once all modules are implemented:
   ```bash
   python scripts/run_pipeline.py --city shanghai
   ```

---

## 4. Data Sources

| Type | Source | Access |
|---|---|---|
| Building footprints + storeys | Taobao commercial vector dataset | Commercial (~80 RMB) |
| Building footprints (fallback) | OpenStreetMap via Overpass API | Open |
| Building footprints (fallback) | Microsoft Global ML Building Footprints | Open |
| Building height (fallback) | CNBH-10m / 3D-GloBFP | Open |
| Points of Interest | Taobao bulk export or Amap (Gaode) API | Commercial / API |
| Land-use classification | EULUC-China | Open |
| Public-building monthly EUI | Wang H. et al., *Green Building*, 2026(1) | Published literature |
| Residential annual EUI | Tsinghua Building Energy Annual Reports; GB/T 51161-2016 | Published literature / standards |
| Embodied carbon factors | One Click LCA China EPD database; CLCD | Licensed; Open |
| Weather | EnergyPlus Shanghai TMY / CSWD | Open |

Detailed acquisition instructions and file naming conventions are documented in `data/raw/README.md`.

---

## 5. Calibration Targets

| Building category | Source | Granularity | Target NMBE |
|---|---|---|---|
| Public buildings (12 archetypes) | Wang et al. 2026 (Shanghai monitoring platform) | Monthly | ±10% |
| Residential buildings (2 archetypes) | Tsinghua Annual Reports + GB/T 51161-2016 + Shanghai Statistical Yearbook | Annual | ±20% |

---

## 6. Configuration

All tunable parameters live under `config/`. To adapt this pipeline to another city (e.g., Nanjing), modify the YAML files without touching `src/`.

| File | Purpose |
|---|---|
| `shanghai.yaml` | Weather file path, CRS, study-area bounding box |
| `archetypes.yaml` | 14 archetype definitions, default floor heights, WWR, HVAC types |
| `poi_mapping.yaml` | POI category → archetype mapping dictionary |
| `standards.yaml` | GB 50189 / DGJ32 / GB/T 51161 reference values (U-values, LPD, occupancy density) |
| `calibration_targets.yaml` | Wang et al. 144-point matrix and residential benchmarks |
