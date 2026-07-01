# EPD Data from One Click LCA

Building material EPD (Environmental Product Declaration) data for embodied-carbon modelling in Module D.

## Files

- `Building_EPD.xlsx` — Master table, 486 rows across 6 material categories (Yuqian 5 materials expanded)

## Data Structure

**Sheets in Building_EPD.xlsx**:
- `master` — 486 EPD rows × 38 columns
- `_summary` — Category-level A1-A3 GWP statistics
- `_metadata` — Unit conventions, EOL logic, source info

**Material categories**:

| Category | Records |
|---|---|
| concrete_readymix | 96 |
| concrete_precast | 133 |
| glass | 16 |
| steel | 74 |
| aluminum | 81 |
| bricks_masonry | 86 |
| **Total** | **486** |

## Unit Convention

All GWP values normalized to **kgCO2e/kg** for consistent Monte Carlo sampling in Module D:

- **Concrete**: originally kgCO2e/m³ → divided by `density_kg_m3`
- **Glass**: originally kgCO2e/m² → divided by `mass_per_m2_kg`
- **Steel / Aluminum / Bricks**: originally kgCO2e/kg → used as-is

Original values preserved in `gwp_a1_a3_original` + `gwp_original_unit` columns for traceability.

## End-of-Life Stage

Different materials use different EOL stages per EN 15804 convention. Unified into single `gwp_eol_per_kg` column; `eol_stage` records the source stage:

- **C4** (landfill): Concrete, Glass, AAC, Clay brick, Reclaimed brick
- **C3** (recycling): Steel, Aluminum
- **C3-balancing**: CMU + Medium density concrete blocks (concrete masonry crushed for aggregate reuse)

## Source

One Click LCA generic library, filtered for China region using `APPLYLOCALCOMPS: china` and `averageElectricityChinaEPD.IEA2023` (IEA 2023 China electricity mix).

**LCA Standard**: EN 15804 +A1/+A2 (Level(s) life-cycle carbon)

## Data Filtering

Raw exports contained 626 SKUs across 6 One Click LCA Designs (aaa / Ready-mix concrete / Precast concrete / Glass / Steel / Aluminum / Brick). 486 rows retained after cross-material filtering:

- **Excluded**: railway sleepers, catenary wire, bridge segments, road barriers, bollards, fence/barbed wire, lightning earthing, temporary scaffolds, roof tiles, terracotta facade brick
- **Retained**: standard building superstructure + substructure materials

## Generated

2026-07-01, auto-consolidated by claude.ai code interpreter from 6 per-material intermediate files (kept locally at `E:\Energy\Yuqian_Shanghai_Energy_data\epd_oneclick\`).
