# PROJECT_MEMORY.md

> This file is a manual mirror of project context maintained in claude.ai.
> Updated by the project owner after each significant strategy session.
> Claude Code MUST read this file before reading CLAUDE.md or executing
> any task at the start of every new session.

---

## 1. Project Status

_Current phase, headline goal of the current sprint, and what counts as "done"
for the active milestone. The owner updates this after each strategy session._

- **Current phase:** Phase 1 数据采集 **9/9 完成**(2026-07-03,validation set #9 入库记账收官)。Skeleton (PR #1), workflow scaffolding (PR #2), iron rule (PR #3), POI mapping dictionary (PR #4) merged; OSM / Microsoft footprints / CNBH-10m 三个 fallback 源已于 2026-06-21 决策 dropped(见 §4)。下一步进入 Module A 数据处理流水线实施。
- **Active milestone:** Module A — Data Acquisition. Collect 7 external data sources and place under `data/raw/` per `data/raw/README.md`, then produce a coverage-reported `outputs/geojson/master.geojson`.
- **Definition of done for this milestone:** All 7 data sources committed (or noted in `data/raw/README.md` as acquired but gitignored), and one full Module A run produces `master.geojson` with documented coverage statistics (% labeled / % ML-predicted / % unknown / % height-complete). [`config/poi_mapping.yaml` ✓ merged in PR #4, 2026-06-20]

---

## 2. Recent Decisions

_Last 5 major decisions, dated `YYYY-MM-DD`. New entries go on top; trim the
list to 5 when a sixth is added. Capture the decision, the rationale in one
line, and whether it has been encoded in the repo (commit / config / doc)._

| Date | Decision | Rationale | Encoded in |
|---|---|---|---|
| 2026-07-03 | Validation set #9 以 **156 annotated + 44 not_found** 记账收官(核实率 156/200) | 44 栋无法定位系街景影像(约 2020)早于建成,集中临港/张江;两处修正:V002 层数按最高塔记 23、V061 补勾 mixed_use 综合体 | `data/raw/validation/`(master.xlsx + v0.csv + README.md, commit 直入 main) |
| 2026-07-03 | 临港窗口规格由 30–50 栋修订为 **20 栋** + 以 2023 Taobao FLOOR 集为主力校准 + 补抽预案留档 | 临港 40 抽样中 20 栋 not_found(影像早于建成),不立即补抽;预案(lingang 窗口、剔除已用行号、height 分层、seed=43)触发条件:Module A 临港层数推断与本集 20 栋显著不符 | `data/raw/validation/README.md` §补抽预案 |
| 2026-07-01 | 采用 One Click LCA + China localization 作为 5 材料 EPD 源;从 6 个 Design 导出后跨类别剔除 140 条非建筑 SKU(铁路/桥梁/围栏/路障/屋面瓦/陶土面砖),合并为 486 rows 的 master 表 | 唯一批量提供中国区 EPD 的商业库(已持有 license);`APPLYLOCALCOMPS: china` + IEA 2023 中国电网自动本地化;统一到 kgCO2e/kg,EOL 双轨(C4 混凝土/玻璃/砖类,C3 钢/铝,C3-balancing CMU/mid-density block) | `data/raw/epd_oneclick/Building_EPD.xlsx` + README |
| 2026-06-21 | Residential benchmark 改用 GB/T 51161 + 上海阶梯电价 + 上海统计公报 + Hu & Yan 2016 Energy Policy,放弃原计划的清华 CBEM 2025 | 公开政府文件 + 顶刊论文引用规范度优于工具书;数据时点对齐(2024 上海)优于 CBEM 整本 2023 年统计;能精确折算 per-area EUI(GB 户 → 上海户均面积 98.4 m²) | `data/raw/benchmark/residential_annual_eui.csv` |
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
- [~~done 2026-07-03~~] Validation set #9:人工标注 200 行已完成并入库记账(156 annotated + 44 not_found),定稿在 `data/raw/validation/`(master.xlsx + v0.csv + README.md)。详见 §2 决策与 §4 第 9 源。
- [@deferred] Phase 7: Buildings.shanghai 公开平台 — fork City-Syntax/buildings.city framework + 套上海数据 + 部署。1-2 周工作量,等 Phase 1-6 全部跑完再启动。

---

## 4. Data Acquisition Progress

_Per data source: status (not-started / requested / received / ingested),
on-disk location once ingested, last update date. This block tracks the raw
inputs Module A depends on._

| Source | Status | Location | Last updated |
|---|---|---|---|
| Taobao buildings 2026 (all 16 districts, height) | acquired locally (843,063 buildings, WGS84 ✓实测 2026-07-02 checkpoint-2 单点判定, height=4-415m ⚠️超高层段截断/失真见 README QC, +Area +district fields, encoding=utf-8 per .cpg(原记 gbk 有误,已实测更正), MD5: ED87E281..., gitignored per SOP) | `data/raw/taobao/shanghai_2026_height/README.md` | 2026-07-02 |
| Taobao buildings 2023 (central, FLOOR) | acquired locally (412,100 buildings, WGS84, FLOOR=2-236 w/ <0.1% outliers >128, MD5: 674A7662..., gitignored per SOP) — used as Height→Floor calibration set | `data/raw/taobao/shanghai_2023_floor/README.md` | 2026-06-21 |
| Taobao / Amap POI | Amap personal-dev key acquired (held locally, not in Git); fetch deferred to Module A | `data/raw/amap/` | 2026-06-20 |
| OpenStreetMap buildings (fallback) | **dropped**(2026-06-21 决策,§8.1;Taobao 2026 全市覆盖后 fallback 不再需要) | `data/raw/osm/`(空,保留 README 约定) | 2026-07-03 |
| Microsoft Global ML Building Footprints | **dropped**(2026-06-21 决策,§8.1;同上) | `data/raw/ms_buildings/`(空,保留 README 约定) | 2026-07-03 |
| CNBH-10m / 3D-GloBFP height raster | **dropped**(2026-06-21 决策,§8.1;Taobao 2026 自带 height,fallback 不再需要) | `data/raw/cnbh/`(空,保留 README 约定) | 2026-07-03 |
| EULUC-China land use | acquired locally (v2.0, 3.1 GB GPKG, MD5-verified, gitignored per SOP); README scaffolded in repo | `data/raw/euluc/README.md` (full GPKG stored outside repo at owner's `E:\Energy\Yuqian_Shanghai_Energy_data\`) | 2026-06-21 |
| Wang et al. 2026 monthly EUI (144 points) | ingested (12 archetypes × 12 months, sanity-checked vs published annual within ±0.2 kWh/m²) | `data/raw/benchmark/wang_2026_public_monthly.csv` | 2026-06-21 |
| Residential annual benchmarks | ingested (GB/T 51161 约束值 + 上海发改委阶梯电价档位 + 上海统计公报 + Hu & Yan 2016 Energy Policy 采暖占比;原计划的清华 CBEM 2025 评估后改用上述公开源,引用更规范) | `data/raw/benchmark/residential_annual_eui.csv` | 2026-06-21 |
| One Click LCA China EPDs | ingested (486 rows across 6 materials: concrete_readymix 96 + concrete_precast 133 + glass 16 + steel 74 + aluminum 81 + bricks_masonry 86; 剔除 140 条非建筑 SKU;统一到 kgCO2e/kg;EOL 双轨 C3/C4) | `data/raw/epd_oneclick/Building_EPD.xlsx` | 2026-07-01 |
| Shanghai EPW (TMY / CSWD) | ingested (CSWD + TMYx.2011-2025, station 583620 Baoshan) | `weather/` | 2026-06-20 |
| Validation set #9 (200 栋层数/功能人工核实) | **ingested 2026-07-03**(156 annotated + 44 not_found;V001–V200 无缺;坐标 WGS84 实测在沪;修正 V002/V061;临港补抽预案留档见 README) | `data/raw/validation/` | 2026-07-03 |

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

- [@owner, surfaced 2026-06-20 from Amap API test] **Multi-typecode POI 计票策略**:实测发现单个 POI 可能有多个 typecode(`|` 分隔),例:"上海东方明珠广播电视塔有限公司" 的 typecode = `170200|141300|141100`,会同时贡献 office × 2 + education × 1。模块 A 实现 `poi_seeding.py` 时需决定计票方案:(A) 每 typecode 算 1 票,(B) 只用第一个,(C) 1/N 票均分,(D) 多 typecode 视为 mixed_use 信号。当前倾向方案 C(投票权守恒),待模块 A 跑通后用实际数据分布验证。
