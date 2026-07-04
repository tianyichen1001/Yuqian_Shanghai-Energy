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
- **已锁定设计基线**(2026-06-18 决策,自 §2 归档):mixed_use 按裙楼商业 + 塔楼办公垂直复合体建模(非单一 archetype,`config/archetypes.yaml`);住宅 mid_rise / high_rise 分界 10 层(GB 50016-2014 / GB 50352-2019,`config/archetypes.yaml` globals.floor_count_cutoff);双轨校准目标公建 ±10% monthly NMBE / 住宅 ±20% annual NMBE(仿 Lyu et al. 2026,`config/calibration_targets.yaml`);纯 Python IDF 流水线 eppy/geomeppy/honeybee-energy、无 Rhino/Grasshopper(`pyproject.toml`)。

---

## 2. Recent Decisions

_Last 5 major decisions, dated `YYYY-MM-DD`. New entries go on top; trim the
list to 5 when a sixth is added. Capture the decision, the rationale in one
line, and whether it has been encoded in the repo (commit / config / doc)._

| Date | Decision | Rationale | Encoded in |
|---|---|---|---|
| 2026-07-04 | 云端数据通道**改道定案**:Release 存档 + Codespace 云到云中转 + git 树取用;PAT 机制退役;MD5 对暗号机制保留 | 会话 GitHub 网关 403 证伪 Release API 直下(07-02「实测打通」系记账夸大);git 通道用会话自带授权,07-04 端到端实测成功 | §4.6 |
| 2026-07-04 | ep 字段鉴定为 **14 值分类编码,严禁作层数使用**;2026 集行数定案 **843,062**(供应商宣传 843,063 多记 1) | 三重证据否定层数假设(14 离散值 / height÷ep 中位 1.33 m / 415m 双塔 ep=2 而非 ≈128/101);行数 DBF+SHX+geopandas 三方互证 | `data/raw/taobao/shanghai_2026_height/README.md` + `scripts/ep_investigation.py` |
| 2026-07-03 | Validation set #9 以 **156 annotated + 44 not_found** 记账收官(核实率 156/200) | 44 栋无法定位系街景影像(约 2020)早于建成,集中临港/张江;两处修正:V002 层数按最高塔记 23、V061 补勾 mixed_use 综合体 | `data/raw/validation/`(master.xlsx + v0.csv + README.md, commit 直入 main) |
| 2026-07-03 | 临港窗口规格由 30–50 栋修订为 **20 栋** + 以 2023 Taobao FLOOR 集为主力校准 + 补抽预案留档 | 临港 40 抽样中 20 栋 not_found(影像早于建成),不立即补抽;预案(lingang 窗口、剔除已用行号、height 分层、seed=43)触发条件:Module A 临港层数推断与本集 20 栋显著不符 | `data/raw/validation/README.md` §补抽预案 |
| 2026-07-01 | 采用 One Click LCA + China localization 作为 5 材料 EPD 源;从 6 个 Design 导出后跨类别剔除 140 条非建筑 SKU(铁路/桥梁/围栏/路障/屋面瓦/陶土面砖),合并为 486 rows 的 master 表 | 唯一批量提供中国区 EPD 的商业库(已持有 license);`APPLYLOCALCOMPS: china` + IEA 2023 中国电网自动本地化;统一到 kgCO2e/kg,EOL 双轨(C4 混凝土/玻璃/砖类,C3 钢/铝,C3-balancing CMU/mid-density block) | `data/raw/epd_oneclick/Building_EPD.xlsx` + README |

_2026-06-18 的四条基础设计决策(mixed_use 垂直复合体、10 层住宅分界、双轨校准目标、纯 Python IDF 流水线)已压缩归档至 §1「已锁定设计基线」。2026-06-20 POI 映射字典与 2026-06-21 residential benchmark 两条决策随滚动裁剪出表,内容已编码于 §1 / §4 对应行(`config/poi_mapping.yaml` PR #4;`data/raw/benchmark/residential_annual_eui.csv`)。_

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
| Taobao buildings 2026 (all 16 districts, height) | **ingested 2026-07-04 via 云端 git 通道**(**843,062** buildings —— 实测定案,供应商宣传 843,063 多记 1,DBF+SHX+geopandas 三方互证;WGS84 ✓复测 EPSG:4326;height=4-415m ⚠️超高层段整体失真见 README QC 07-04 升级说明;ep=14 值分类编码禁作层数;encoding=utf-8 per .cpg;zip MD5: 81EBFC2B... 命中暗号,.shp MD5: ED87E281... 与本地版同一文件;gitignored per SOP) | `data/raw/taobao/shanghai_2026_height/README.md` | 2026-07-04 |
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

### 4.6 云端数据通道(2026-07-04 改道定案)

> 注:仓库镜像原无 §4.1–§4.5 子节(长版在 claude.ai),本节按 owner 口述编号直接落地;其余子节待 owner 同步。

1. **正式通道**:Release 存档(tag `data-v1`,zip 附件)→ owner 在 GitHub Codespace 内云到云中转并人工 `md5sum` 核对 → 提交进数据仓库 `Yuqian_Shanghai-Energy-data` git 树(main)→ Claude Code 会话内 `git pull` 取用。
2. **勘误(07-04 实测证伪)**:07-02 记账的「Release API 下载实测打通」系记账夸大 —— Claude Code 会话内 `api.github.com` / Release 资产下载被会话 GitHub 网关 403 拦截(带不带 PAT 均拦,PAT 根本未到达 GitHub),该通道在会话内不可用。
3. **PAT 机制退役**:git 通道使用会话自带授权,无需任何钥匙;不再签发/传递 DATA_PAT。
4. **MD5 对暗号机制保留不变**:zip 落地后逐字符比对暗号,不一致立即停止、不解压。(07-04 实测:zip MD5 `81EBFC2B...` 命中暗号;sha256 与 Release digest 一致;内层 .shp MD5 `ED87E281...` 与 owner 本地 QC 版本为同一文件。)
5. **教训**:通道类结论必须端到端跑通才可标「打通」。

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
- [@owner, surfaced 2026-07-04 from A1 ep 侦查] **ep 字段语义待向供应商核实**:14 值分类编码 {1,2,4,6,7,8,9,10,11,12,13,14,18,26},疑似高度/体量档位(ep=2 ≈ 约百米以上高楼专属);已定案禁作层数,但确切语义未知。详见 2026 README + `scripts/ep_investigation.py`。
- [@owner, surfaced 2026-07-04 from A1 QC] **金茂大厦入库 height 值待 Module A 中人肉锁定**:实际 420.5 m 未出现在 ≥410 区间,疑以浦东 385/361/351 梯队中某值入库;需结合坐标人肉比对锁定,作为超高层失真的定标样本。
- [@owner, surfaced 2026-07-04 from A1 QC] **超高层人工核对名单的具体规则待 Module C 前定**:height 阈值(如 ≥200 m)、名单来源(CTBUH/官方名录)、核对与替换流程均未定;超高层段高度整体不可信,Module C 仿真前必须完成。

---

## 下次 session 起点

A2:2023 数据集上云(走 Codespace 拖拽通道入数据仓库 git 树)+ POI bulk fetch + Stage 1 七步。
