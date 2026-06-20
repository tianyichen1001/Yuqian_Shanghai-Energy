# PROJECT_MEMORY.md

> This file is a manual mirror of project context maintained in claude.ai.
> Updated by the project owner after each significant strategy session.
> Claude Code MUST read this file before reading CLAUDE.md or executing
> any task at the start of every new session.

---

## 1. Project Status

_Current phase, headline goal of the current sprint, and what counts as "done"
for the active milestone. The owner updates this after each strategy session._

- **Current phase:** Pre-Module-A. Skeleton (PR #1), workflow scaffolding (PR #2), iron rule (PR #3), and POI mapping dictionary (PR #4) merged to main as of 2026-06-20. Awaiting data acquisition.
- **Active milestone:** Module A — Data Acquisition. Collect 7 external data sources and place under `data/raw/` per `data/raw/README.md`, then produce a coverage-reported `outputs/geojson/master.geojson`.
- **Definition of done for this milestone:** All 7 data sources committed (or noted in `data/raw/README.md` as acquired but gitignored), and one full Module A run produces `master.geojson` with documented coverage statistics (% labeled / % ML-predicted / % unknown / % height-complete). [`config/poi_mapping.yaml` ✓ merged in PR #4, 2026-06-20]

---

## 2. Recent Decisions

_Last 5 major decisions, dated `YYYY-MM-DD`. New entries go on top; trim the
list to 5 when a sixth is added. Capture the decision, the rationale in one
line, and whether it has been encoded in the repo (commit / config / doc)._

| Date | Decision | Rationale | Encoded in |
|---|---|---|---|
| 2026-06-20 | POI category → archetype mapping dictionary completed (869 codes → 14 archetypes, 0 unknown) | Key calls: 金融保险→office (ATM single-out skip); 综合市场→shopping_mall (no wet_market archetype); 宿舍→residential (Wang et al. 144 不收宿舍); 商住两用→mixed_use prior | `config/poi_mapping.yaml` (PR #4) |
| 2026-06-18 | Mixed-use modeled as podium retail + tower office vertical composite (not a single archetype) | Wang et al. 综合建筑 monthly EUI is closer to office than to pure retail; ~22.5% of monitored floor area justifies first-class treatment | `config/archetypes.yaml` mixed_use |
| 2026-06-18 | Residential mid_rise vs high_rise cutoff set at 10 storeys | Aligns with GB 50016-2014 / GB 50352-2019 fire-safety definition of 高层住宅 | `config/archetypes.yaml` globals.floor_count_cutoff |
| 2026-06-18 | Dual-track calibration: public buildings ±10% monthly NMBE, residential ±20% annual NMBE | Mirrors Lyu et al. 2026 mixed-precision approach; reflects the residential data availability gap | `config/calibration_targets.yaml` |
| 2026-06-18 | Pure-Python IDF generation pipeline (eppy/geomeppy/honeybee-energy), no Rhino/Grasshopper | Reproducibility + batch scalability + removes licensing barrier for Chinese institutions | `pyproject.toml` runtime deps |

---

## 3. Active TODOs

_Cross-PR running list of things the owner has agreed to do, things waiting on
external data, and things explicitly deferred. One bullet per item with the
owner ("@owner" / "@claude-code") and a one-line status._

- [@owner] 设定综合体 (mixed_use) 的 POI 类目多样性熵阈值 — 模块 A POI 计票实现后再定。先验参考:Wang et al. 2026 综合建筑占上海监测面积 22.5%。
---

## 4. Data Acquisition Progress

_Per data source: status (not-started / requested / received / ingested),
on-disk location once ingested, last update date. This block tracks the raw
inputs Module A depends on._

| Source | Status | Location | Last updated |
|---|---|---|---|
| Taobao buildings + storeys | _TODO_ | `data/raw/taobao/` | _TODO_ |
| Taobao / Amap POI | _TODO_ | `data/raw/taobao/poi/` or `data/raw/amap/` | _TODO_ |
| OpenStreetMap buildings (fallback) | _TODO_ | `data/raw/osm/` | _TODO_ |
| Microsoft Global ML Building Footprints | _TODO_ | `data/raw/ms_buildings/` | _TODO_ |
| CNBH-10m / 3D-GloBFP height raster | _TODO_ | `data/raw/cnbh/` | _TODO_ |
| EULUC-China land use | _TODO_ | `data/raw/euluc/` | _TODO_ |
| Wang et al. 2026 monthly EUI (144 points) | _TODO_ | `data/raw/benchmark/wang_2026_public_monthly.csv` | _TODO_ |
| Tsinghua residential annual benchmarks | _TODO_ | `data/raw/benchmark/` | _TODO_ |
| One Click LCA China EPDs | _TODO_ | `data/raw/epd_oneclick/` | _TODO_ |
| Shanghai EPW (TMY / CSWD) | _TODO_ | `weather/` | _TODO_ |

---

## 5. Calibration Progress

_Per archetype × month grid status for the 12 public archetypes + annual
status for the 2 residential archetypes. Cell values: `–` (not run),
`pending` (run but NMBE not yet within target), `pass` (within target).
The target thresholds are public ±10 % monthly, residential ±20 % annual._

### Public archetypes — monthly NMBE (Wang et al. 144 points)

| Archetype | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| government_office | – | – | – | – | – | – | – | – | – | – | – | – |
| office            | – | – | – | – | – | – | – | – | – | – | – | – |
| hotel             | – | – | – | – | – | – | – | – | – | – | – | – |
| shopping_mall     | – | – | – | – | – | – | – | – | – | – | – | – |
| healthcare        | – | – | – | – | – | – | – | – | – | – | – | – |
| education         | – | – | – | – | – | – | – | – | – | – | – | – |
| sports            | – | – | – | – | – | – | – | – | – | – | – | – |
| culture           | – | – | – | – | – | – | – | – | – | – | – | – |
| transportation    | – | – | – | – | – | – | – | – | – | – | – | – |
| exhibition        | – | – | – | – | – | – | – | – | – | – | – | – |
| mixed_use         | – | – | – | – | – | – | – | – | – | – | – | – |
| other_public      | – | – | – | – | – | – | – | – | – | – | – | – |

### Residential archetypes — annual NMBE

| Archetype | Status |
|---|---|
| residential_high_rise | – |
| residential_mid_rise  | – |

---

## 6. Open Questions

_Anything Claude Code surfaced that the owner has not yet answered. Each
question stays here until it is resolved by the owner via claude.ai, after
which it migrates to §2 Recent Decisions as a row._

- _TODO — no open questions yet._
