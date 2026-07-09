# PROJECT_MEMORY.md

> This file is a manual mirror of project context maintained in claude.ai.
> Updated by the project owner after each significant strategy session.
> Claude Code MUST read this file before reading CLAUDE.md or executing
> any task at the start of every new session.

---

## 1. Project Status

_Current phase, headline goal of the current sprint, and what counts as "done"
for the active milestone. The owner updates this after each strategy session._

- **Current phase:** Phase 1 数据采集 **9/9 完成**(2026-07-03);**Module A 进行中 4/6**(A1 ✅ 2026-07-04 + A2 ✅ 2026-07-05 + A4 ✅ 2026-07-07 + **A3a ✅ 2026-07-09**)。Skeleton (PR #1), workflow scaffolding (PR #2), iron rule (PR #3), POI mapping dictionary (PR #4) merged; OSM / Microsoft footprints / CNBH-10m 三个 fallback 源已于 2026-06-21 决策 dropped(见 §4)。**A3a 收官**(mall+hotel 信号 3,417 请求;10/12 validation 通过;数据 `6a21003`,七脚本 `e759e56`);A3b 全市 060000 补抓推 8/1 免费额度刷新执行。下一站:**A5**(2023×2026 楼层-高度联合校准)+ A3b(8/1)+ A6。
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
| 2026-07-09 | **A3a 抓取门槛判定收官**:收窄 typecode + 8ha 门槛主抓 3,128 格 3,295 请求(capped=0);QC 原判 mall 2/14 触发预注册回退承诺 → 分诊定位 typecode 收窄为主因 → 微探针 12 请求探路 → 定向补抓 156 栋 annotated 所在 19 格全量 060000(110 请求 / 2,321 POI)→ mall 重裁标准 (mall 级 ≤150m) OR (060000 ≤100m),最终 10/12 通过 | 预注册回退承诺兑现,收窄不伤主业;残余 V096/V141 归 §7.12 改判后门;残余发现:validation 里 shopping_mall 实为 retail 兜底类(独栋餐饮/街边小商业)8/12 | 数据 `6a21003` + 脚本 `e759e56`;`scripts/a3_batch.py` + `scripts/a3_qc.py` + `scripts/a3_valwin_topup.py` + 决策链证据 `a3_dryrun_v3.py` / `a3_qc_diag.py` / `a3_probe_missed.py` / `a3_grid_audit.py` |
| 2026-07-09 | **EULUC 2022 时间盲区在 A3 网格中的结构性继承**:200 验证行 40 行落网格外(annotated 156 中占 20,与 §14.H 20 unmatched 一一对应);V199/V200 显性证据 —— Amap 探针在其 220m 框内明确有 mall 级 POI(百联临港生活中心 060101\|060102),但成果表 978m 内无 mall,因该区域在 EULUC 2022 分类范围外,继承入 A3 扫描网格 | A3 覆盖论述统一改口径为 "EULUC-scoped coverage";盲区补扫方案随 A3b 8/1 执行卡评估;论文 Methods 中作为 EULUC 数据源固有属性如实报告(与 A4/§7.12 attrition 论述一脉相承) | `scripts/a3_grid_audit.py`;A3b 8/1 执行卡待写 |
| 2026-07-07 | **A3 战略重排 α'**:废原扫 EULUC Class 2 商业方案(交叉验证暴露漏 92% 商场——12 栋 validation 商场只 1 栋落 Class 2);改为在 Class 0+1+2 面积并集内定向抓 `060000 购物` + `100000 住宿` 两类,预算 ~5,800/月 | `data/raw/euluc/README.md`(交叉验证结论段)+ 待写的 A3 批量脚本 |
| 2026-07-07 | **A4 EULUC 上海市界切片收官**:Zenodo 3.1 GB → GADM 4.1 市界内 55,124 parcels / 4,267.8 km²(占官方 6,340 的 67%);schema 定案仅 `Class(int8)+geometry`(原多字段档案作废);11 类 Class 编码破译;GPKG zip 通道 deflate 45%(103→54 MB)三段旅程 MD5 无损上私仓 | 主仓 `c3609f6` + 私仓 `9eea025`;`data/raw/euluc/README.md` + `data/reference/euluc_class_mapping.csv` |
| 2026-07-05 | **FLOOR = 2×实际层数定案**(2023 集),换算 floors=FLOOR//2;旧过滤规则「FLOOR>130→NA」作废,9 行改判合法超高层校准点 | 三路证据:地标锚点 176/88 金茂、202/101 环球、236/118 上海中心、132/66 白玉兰(决定性);万对抽样隐含层高中位 4.0 m、86.7% 落 2.5–5 m;validation 132 样本中位 ratio 恰 2.000;全表 0 奇数指纹 | `data/raw/taobao/shanghai_2023_floor/README.md` + `scripts/floor_semantics.py` |
| 2026-07-05 | **金茂悬案销案**:金茂大厦以 height=415(顶端截断)入库 2026 集(Area 2,610 m² 那栋,FLOOR 锚点 176→88 层) | 空间对照锁定;同法实锤 2026 超高层高度乱序(上海中心 632m 入库 351、环球 492m 入库 361) | `data/reference/supertall_height_floor_crosswalk.csv` |

_2026-06-18 的四条基础设计决策(mixed_use 垂直复合体、10 层住宅分界、双轨校准目标、纯 Python IDF 流水线)已压缩归档至 §1「已锁定设计基线」。2026-06-20 POI 映射字典、2026-06-21 residential benchmark、2026-07-01 One Click LCA EPD 源、2026-07-03 临港窗口 20 栋修订 + validation 156+44 收官、2026-07-04 ep 字段鉴定为分类编码六条决策随滚动裁剪出表,内容已编码于 §1 / §4 对应行、`data/raw/validation/README.md` §补抽预案、`data/raw/epd_oneclick/`、`data/raw/taobao/shanghai_2026_height/README.md` + `scripts/ep_investigation.py`。2026-07-04 的云端数据通道改道随本次滚动裁剪出表,内容已固化于 §4.6。_

---

## 3. Active TODOs

_Cross-PR running list of things the owner has agreed to do, things waiting on
external data, and things explicitly deferred. One bullet per item with the
owner ("@owner" / "@claude-code") and a one-line status._

- [~~done 2026-07-09~~] A3a 高德 POI 定向抓取:mall+hotel 双 archetype 信号收全,10/12 validation 通过。3,417 请求总消耗(主抓 3,295 + 微探针 12 + 补抓 110);数据 `6a21003`(`data/raw/poi/` + `data/reference/a3_*`),七脚本 `e759e56`。详见 §2 决策 2026-07-09。
- [@owner + @codespace, deferred 2026-08-01] **A3b 全市 060000 补抓(retail 兜底类信号)**:配 8 月 1 日免费额度刷新执行;门槛 8ha,页上限 4,预算 4,500-6,000;当天先 10 次预检验证 typecode 密度,GO 后开跑;script 复用 `a3_batch.py` 改 types 参数,QC 复用 `a3_qc.py`。目的:把独栋餐饮/街边小商业等 retail 案例的 POI 信号收全,消化 §2 2026-07-09 决策里"validation shopping_mall 8/12 是小体量零售"的方法学缺口。
- [@owner + @codespace, deferred 2026-08-01] **EULUC 2022 时间盲区补扫评估**:与 A3b 一起或独立执行;候选方案 = 以 2026 建筑矢量的临港/张江覆盖差集为盲区扫描网格,预算另算;或维持 "EULUC-scoped" 口径不补扫,只在论文 Methods 中如实标注 —— 8/1 前二选一拍板。
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
| Taobao buildings 2023 (central, FLOOR) | **ingested 2026-07-05 via 云端 git 通道**(**412,099** buildings —— 实测定案,供应商宣传 412,100 多记 1;WGS84 ✓复测;schema 极简仅 FLOOR+geometry;**FLOOR=2×实际层数定案**,floors=FLOOR//2,全表偶数指纹;zip MD5: 6E033592... 命中暗号,.shp MD5: 674A7662... 与本地版同一文件;gitignored per SOP)— Height→Floor 校准集 | `data/raw/taobao/shanghai_2023_floor/README.md` | 2026-07-05 |
| Taobao / Amap POI | Amap personal-dev key acquired (held locally, not in Git); fetch deferred to Module A | `data/raw/amap/` | 2026-06-20 |
| OpenStreetMap buildings (fallback) | **dropped**(2026-06-21 决策,§8.1;Taobao 2026 全市覆盖后 fallback 不再需要) | `data/raw/osm/`(空,保留 README 约定) | 2026-07-03 |
| Microsoft Global ML Building Footprints | **dropped**(2026-06-21 决策,§8.1;同上) | `data/raw/ms_buildings/`(空,保留 README 约定) | 2026-07-03 |
| CNBH-10m / 3D-GloBFP height raster | **dropped**(2026-06-21 决策,§8.1;Taobao 2026 自带 height,fallback 不再需要) | `data/raw/cnbh/`(空,保留 README 约定) | 2026-07-03 |
| EULUC-China land use | **ingested 2026-07-07 via A4 收官**(**55,124 parcels / 4,267.8 km²** 覆盖上海市界内,占官方 6,340 的 67%;GADM 4.1 `NAME_1==Shanghai` 切片;**schema 定案仅 `Class(int8)+geometry` 两列**;11 类 Class 编码破译入库 `data/reference/euluc_class_mapping.csv`;**交叉验证 156 栋 validation 87% 匹配**,单一功能 archetype 60–77% 命中 / 综合体 <10% 命中——parcel-level vs building-level 张力,论文 Methods 素材;GPKG 99 MB gitignored,zip 54 MB(deflate 45%)MD5 `0af6391f...` 上私仓 git 树 `9eea025`) | 主仓 `data/raw/euluc/README.md` + `data/reference/euluc_class_mapping.csv`(`c3609f6`);私仓 `Yuqian_Shanghai-Energy-data/euluc_shanghai_2022.gpkg.zip` | 2026-07-07 |
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
6. **GPKG zip 通道经验(07-07 A4 实证)**:大 GPKG 走 zip 打包 push git 树,SQLite 二进制 gzip deflate 实测 45%(103 MB → 54 MB),优于预估 30–40%;54 MB 单文件在 100 MB 硬限内 push 成功(GitHub 会警告"建议 <50 MB 走 LFS"但不阻塞)。**主仓 Codespace → 本地下载 → 私仓 Codespace 上传**三段旅程 MD5 位对位无损。90–100 MB 量级 GPKG 数据可复用此路径。

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
- ~~[金茂入库值]~~ **销案 2026-07-05**:金茂以 height=415(截断)入库,见 §2 决策行与 `data/reference/supertall_height_floor_crosswalk.csv`。
- [@owner, surfaced 2026-07-04 from A1 QC] **超高层人工核对名单的具体规则待 Module C 前定**:height 阈值(如 ≥200 m)、名单来源(CTBUH/官方名录)、核对与替换流程均未定;超高层段高度整体不可信,Module C 仿真前必须完成。种子表已入库 `data/reference/supertall_height_floor_crosswalk.csv`(top 20,4 栋 confirmed)。
- [@owner, surfaced 2026-07-05 from A2 侦查] **height=415 / Area 6,027 m² 那栋身份待认领**:与金茂并列的另一栋 415,质心对到 2023 FLOOR=20(疑裙房错配),crosswalk 表中标"待人肉"。
- [@owner, surfaced 2026-07-05 from A2 侦查] **validation 对表 7–12 层段 ratio=1.0 异常(n=13)**:该分箱中位 FLOOR÷标注 =1.0 而非 2.0,样本小且混有错配,未定性;A5 时用 369,035 对全量空间配对分层复查。
- - [@owner + @codespace, surfaced 2026-07-07 from A4 交叉验证] **mixed_use 综合体识别策略**:EULUC parcel-level 分类把综合体裙楼商业信号吞进主导功能——5 栋 validation 综合体里 4 栋落 Class 1 Business office(裙楼商业信号丢失)、shopping_mall 12 栋里 6 栋落 Class 0 Residential(商住综合体裙楼)。当前策略 = A6 用"EULUC Class 1 + `060000` POI 命中"标 mixed_use 候选,由覆盖率四个数验证。A6 收官时销案。
- [@owner, surfaced 2026-07-07 from A4 交叉验证] **临港 20 栋 validation 落 EULUC 未匹配**:87% 空间匹配率(136/156)里的 20 unmatched 集中临港/张江,机制 = EULUC 2022 版本时点早于新楼建成(与 §7.12 影像 ~2020 attrition 同源、不同数据源、同一时点问题)。**方法学注脚,不销**;论文如实报告"POI seeding 在临港有 EULUC 时点漂移风险"。
- - [@owner + @codespace, surfaced 2026-07-09 from A3a QC] **hotel POI 无 validation 对手**:A3a 抓回 13,493 条酒店 POI,但 156 栋验证集中无 hotel archetype 标注,当前无法量化 hotel 命中率。候选方案:(a) 复用 156 栋外原始 5,000+ 候选池抽 15-20 栋酒店补标注;(b) A6 阶段做架构级验证时批量抽样;(c) 复用 §7.6 residential 四源拼接思路,用 Wang et al. 2026 hotel 档 EUI 反推信号密度。短期不阻塞 Module B 上跑;Module C 仿真前必须销案。
- [@owner, surfaced 2026-07-09 from A3a QC] **V009 / V096 / V141 shopping_mall 改判后门(§7.12 已留)**:V009 陆家嘴 lujiazui 独栋餐饮(备注"餐厅",按 §7.12 标注裁定"店不定义楼")、V096 莘庄 060000 最近 186m、V141 张江 060000 最近 204m;待百度全景 2020 影像人工复核后决定归 unclear / mixed_use / 保持 mall 之一;不阻塞 A3a 收官记账。
- [@owner + @codespace, surfaced 2026-07-09 from A3a grid audit] **EULUC 2022 时间盲区案(见 §2 决策 2026-07-09 第二条)**:200 验证行 40 行网格外(临港/张江主导);A3 覆盖论述统一改为 "EULUC-scoped";盲区补扫方案 8/1 前拍板(见 §3 TODO)。方法学注脚同 §14.H attrition,不销;补扫方案销。

---

## 7. 双数据集策略(部分镜像)

> 注:仓库镜像原无 §7(长版在 claude.ai),以下按 owner 口述编号落地 §7.7 / §7.12;其余子节待 owner 同步。

### 7.7 双数据集角色与字段口径(2026-07-05 更新)

- **2023 集(FLOOR)**:**FLOOR = 2×实际层数定案**,换算式 `floors = FLOOR // 2`;旧 outlier 规则「FLOOR>130→NA」**作废**,该 9 行(隐含 66–118 层)改判为**超高层校准点**。角色不变:Height→Floor 经验层高分布的校准集。三路证据与复现:`scripts/floor_semantics.py`、`data/raw/taobao/shanghai_2023_floor/README.md`。
- **2026 集(height)**:**超高层高度乱序实锤**(不只截断)——上海中心(实高 632 m)入库 351、环球金融中心(实高 492 m)入库 361、金茂以 415 截断入库;≥200 m 段数值与真实高度普遍脱钩。Module C 人工替换名单种子见 `data/reference/supertall_height_floor_crosswalk.csv`(top 20,含 WGS84 坐标,4 栋 confirmed)。
- **关联方式**:两集无公共属性键(仅 geometry),只能空间 join;两版 footprint 切分不一致,塔楼密集区错配率不可忽略(A5 ETL 设计时按 2023 README「已知局限」处理)。

### 7.12 validation set 空间覆盖备注

- 2026-07-05 A2 对表实测:validation 200 点对 2023 集 point-in-polygon + 10 m 最近邻共匹配 153,未匹配 47,其中**临港 35/40 属预期**(2023 仅覆盖市区);其余为张江 5、莘庄 3、陆家嘴 3、徐家汇 1(疑 2020 街景后新建或几何缺失)。

---

## 下次 session 起点

**A3 批量抓取脚本编写(方案 α' 定向版)**——回主仓 Codespace(EULUC + pilot 脚本都在 `~/euluc/`),用 `data/raw/euluc/euluc_shanghai_2022.gpkg` 的 Class 0/1/2 面积并集生成扫描 mask,抓 `060000|100000` 两类 typecode,网格 1km × 1km 内置自适应细分 + WGS84↔GCJ-02 转换 + 断点续传,预算 ~5,800 请求。开工前先决定是否做高德个人实名认证提额(免费 5,000/月 略超预算)。悬案:ep 语义(供应商)、415/6,027 身份、7-12 层段异常(A5 销)、多 typecode 计票(A6)、超高层名单细则(Module C 前)、**mixed_use 综合体识别 by Class 1 + 060000 命中**(A6 销)、**临港 EULUC 2022 版本时点外**(方法学注脚,不销)。
