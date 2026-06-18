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

## 2. Memory Protocol

Project context lives in two places: long-form strategy in `claude.ai`, and a
manual mirror in this repository's `PROJECT_MEMORY.md`. The mirror is the
single source of truth for execution.

**Reading order at the start of every new session:**

1. **`PROJECT_MEMORY.md`** — read FIRST. It carries the current phase, recent
   decisions, active TODOs, data-acquisition status, calibration progress,
   and open questions.
2. **`CLAUDE.md`** (this file) — read SECOND. It captures the durable rules
   that do not change session to session.
3. **The user's current instruction** — read LAST.

**Conflict-resolution rule:** if `PROJECT_MEMORY.md` conflicts with the
user's instruction (e.g., the memory says a decision is still pending in
claude.ai but the user is asking to proceed), **stop and report the
conflict**. Do not pick a side on your own. The owner is the only authority
that can reconcile claude.ai context with repo state.

---

## 3. The Five Modules

| Module | Source dir | What it does |
|---|---|---|
| **A. Data acquisition** | `src/buildings_shanghai/data/` | Reads raw Taobao / OSM / Microsoft / EULUC / CNBH inputs; unifies CRS; cleans geometries; seeds functional labels by POI point-in-polygon. |
| **B. ML archetype inference** | `src/buildings_shanghai/ml/` | Trains a Random Forest (with SMOTE rebalancing) on high-confidence seeded labels using shape features; predicts archetype for every building. |
| **C. EnergyPlus simulation** | `src/buildings_shanghai/simulation/` | Generates per-archetype IDFs via `eppy` / `geomeppy` / `honeybee-energy`; runs batched simulations; parses ESO / SQL output to monthly EUI. |
| **D. Embodied-carbon Monte Carlo** | `src/buildings_shanghai/embodied/` | Samples five-material PDFs (concrete, steel, glass, aluminum, brick) from the One Click LCA China EPD database; 5,000 samples per archetype. |
| **E. Calibration + figures** | `src/buildings_shanghai/calibration/`, `src/buildings_shanghai/viz/` | Dual-track NMBE calibration; produces all paper figures. |

---

## 4. Hard Constraints (do not violate without asking)

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

## 5. Directory Conventions

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

## 6. Naming Conventions

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

## 7. Things NOT to Do

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

## 8. When in Doubt

- Configuration question → look in `config/*.yaml`.
- Data layout question → look in `data/raw/README.md`.
- Pipeline-flow question → look in `scripts/run_pipeline.py`.
- Modeling-decision question → ask the human; do not assume.

---

## 9. File Preservation Policy

Everything Claude Code produces during a session must end up in the
repository at the canonical location for its type. Codespaces are
ephemeral — anything left in a temp directory is lost when the container
is reclaimed.

- **Python source** generated for a pipeline module belongs in the
  matching `src/buildings_shanghai/<submodule>/` directory and must be
  committed in the same PR. Entry-point scripts belong in `scripts/`.
  Never leave Python files in the Codespace workspace outside `src/`,
  `scripts/`, `tests/`, or `notebooks/` without committing.
- **Intermediate tables** (`.xlsx`, `.csv`, `.parquet`) belong in
  `data/interim/` (pipeline intermediates) or `outputs/tables/`
  (pipeline outputs). Final paper-ready tables go in
  `outputs/tables/paper/`. See README §3 for the full convention.
- **Figures** (`.png`, `.pdf`, `.svg`) belong in `outputs/figures/`.
  Module-specific subdirectories (e.g.,
  `outputs/figures/calibration/`) are encouraged.
- **Exploratory code** belongs in `notebooks/` as Jupyter notebooks,
  not as ad-hoc Python files in `src/`. Once a notebook stabilizes,
  refactor the reusable logic into `src/buildings_shanghai/...` and
  reference it from the notebook.
- **Reproducibility check:** every PR must leave the repository
  runnable from a fresh clone. After `pip install -e .` and the
  documented Module-A inputs, the pipeline must produce identical
  outputs to those committed under `outputs/tables/` and
  `outputs/figures/`. Hidden state in a Codespace is a regression.

---

## 10. Division of Labor

This project runs on two ends:

- **`claude.ai` is the design end.** Architecture choices, parameter
  selection, archetype definitions, schedule sources, calibration
  tuning direction, and any modeling trade-off live there.
- **Claude Code is the execution end.** Implementing the agreed design,
  wiring it into the pipeline, running it, and reporting results live
  here.

When Claude Code faces a *design* decision — anything in the
`claude.ai` list above — **stop and report it in the active PR
description or in a PR comment**. State the decision needed, the
options, and what is blocked. Wait for the owner to consult `claude.ai`
and reply. Do not invent architecture, choose archetype boundaries,
pick schedule sources, or steer calibration tuning on your own.
Implementation autonomy is fine; design autonomy is not.
