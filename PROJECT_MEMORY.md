# PROJECT_MEMORY.md

> This file is a manual mirror of project context maintained in claude.ai.
> Updated by the project owner after each significant strategy session.
> Claude Code MUST read this file before reading CLAUDE.md or executing
> any task at the start of every new session.

---

## 1. Project Status

_Current phase, headline goal of the current sprint, and what counts as "done"
for the active milestone. The owner updates this after each strategy session._

- **Current phase:** Phase 1 数据采集 **9/9 完成**(2026-07-03);**Module A 收官 6/6**(A1 ✅ 07-04 · A2 ✅ 07-05 · A4 ✅ 07-07 · A3a ✅ 07-09 · A5 ✅ 07-10 · **A6 ✅ 2026-07-11**,A3b 为 8/1 补充项)。milestone 达成:master.gpkg(843,062 行,私仓)+ 覆盖率四个数(栋数/GFA × 全市/EULUC-scoped 双权重双口径)已报,**Module B 全量 ML 判 GO**(规则法天花板实证:同分母 52.2% vs EULUC-only 54.4%)。下一站:**Module B**(基线版即启;retail 特征版随 A3b 8/1)。
- **Active milestone:** Module B — ML archetype 推断。Random Forest + shape features,EULUC 作先验,validation 156 作 ground truth;mall/mixed_use 弱标签不作训练真值;验收要求含 sport_culture 拆分与 culture/hotel 补样评估。
- **Definition of done for this milestone:** All 7 data sources committed (or noted in `data/raw/README.md` as acquired but gitignored), and one full Module A run produces `master.geojson` with documented coverage statistics (% labeled / % ML-predicted / % unknown / % height-complete). [`config/poi_mapping.yaml` ✓ merged in PR #4, 2026-06-20]
- **已锁定设计基线**(2026-06-18 决策,自 §2 归档):mixed_use 按裙楼商业 + 塔楼办公垂直复合体建模(非单一 archetype,`config/archetypes.yaml`);住宅 mid_rise / high_rise 分界 10 层(GB 50016-2014 / GB 50352-2019,`config/archetypes.yaml` globals.floor_count_cutoff);双轨校准目标公建 ±10% monthly NMBE / 住宅 ±20% annual NMBE(仿 Lyu et al. 2026,`config/calibration_targets.yaml`);纯 Python IDF 流水线 eppy/geomeppy/honeybee-energy、无 Rhino/Grasshopper(`pyproject.toml`)。

---

## 2. Recent Decisions

_Last 5 major decisions, dated `YYYY-MM-DD`. New entries go on top; trim the
list to 5 when a sixth is added. Capture the decision, the rationale in one
line, and whether it has been encoded in the repo (commit / config / doc)._

| Date | Decision | Rationale | Encoded in |
|---|---|---|---|
| 2026-07-10 | **A5 收官:2026 height 判定为合成量(= 4 m × 层数),双集共享同一楼层数血统**;干净配对(IoU≥0.30,n=354,241)82.5% 满足 height=2×FLOOR、IoU≥0.7 升 87%、99.7% 可被 4 整除。三处置:① A6 换算 floors=round(height/4)(原 /3.0 作废);② Module C 物理高度改 GB 规范层高正演,全段 height 不作物理米数;③ CNBH-10m/3D-GloBFP 由 dropped 升格必要项(全项目唯一独立高度源,Module C 前采集)。附带:7-12 层段 ratio=1.0 悬案销(错配伪影);超高层订正 2023 ≥40 层共 111 栋("9 锚点"降格 FLOOR>130 已验子集);31-39 独立箱(n=193,恒等比率 0.472,补全 85%→47% 衰减链);supertall 规则 height≥160 m flag 不走 /4 | 越干净的配对越贴合恒等式 = 生成规则指纹非错配噪声;§7.7 "empirical storey-to-height" Methods 话术作废,改写数据溯源发现 | PR #10(squash):`scripts/a5_storey_height.py` + `data/reference/storey_height_by_band.csv` + `data/reference/README.md` |
| 2026-07-11 | **A6 收官(Stage 1 七步 + A6.1/A6.2 两轮补丁)**:master.gpkg 843,062 行行有 floors 或 flag(28 栋超高层 NA+flag);覆盖率四个数终版 —— 全市栋数 56.97% / 全市 GFA 63.75% / EULUC-scoped 栋数 60.95% / GFA 66.21% rule-labeled,height-complete 99.997%;GFA 加权 +6.8pp 与诊断 d 村居画像互证(Class 3/10 计 30 万栋,≤3 层占 85-87%,footprint 中位 300-505 m²,作 unlabeled 进 Module B);两悬案销 —— 多 typecode 计票采方案 C(多码 8.21%,argmax 翻转全市 0.16% / validation 0)、10 层线翻转率 4.8%(±2 扰动,切分线稳健) | POI 净效应收敛线 −12.8 → −5.9 → −2.2pp,规则法修至天花板;supertall 121 栋(2026 全市口径,与 111 为 2023 市区口径不矛盾)93 配 2023 取 FLOOR//2、28 挂 crosswalk/CNBH | 主仓 PR #11(squash,`scripts/a6_stage1.py` + config 规则表 + `a6_class3_10_profile.csv`)+ 私仓 PR #1(master.gpkg.zip,MD5 5d616bb9…) |
| 2026-07-11 | **Module B 全量 ML 判 GO + POI 规则收敛定档**:同分母全规则 52.2% vs EULUC-only 54.4% = 规则法真实天花板 → ML 必要性实证。规则终态:hotel = (100100 ≤150m) OR (100200 ≤150m AND EULUC∈{1,2})(公寓式酒店住宅过挂 10,882→6,886);mall 收敛单条 060100 ≤150m,060000≤100m 分支撤下(数据仅存 19 validation 格,空间不均匀,16 flip/5 hit 净负,A3b 后重估);**mall(1,110)与 mixed_use 候选(319)降级未验证弱标签,不作 Module B 训练真值** | Class 0 裙楼商场识别的正确归宿是 ML 特征(POI 密度 × footprint × 层数)而非规则阈值;Module B 两段式:基线版即启,A3b retail 特征版对比(顺带量化 A3b 价值);验收要求:sport_culture 拆分(全市 6,103 栋 bundled)+ culture/hotel validation 补样评估 | PR #11 config 注释留档 + 本行;Module B brief 由 claude.ai 下发 |
| 2026-07-09 | **A3a 抓取门槛判定收官**:收窄 typecode + 8ha 门槛主抓 3,128 格 3,295 请求(capped=0);QC 原判 mall 2/14 触发预注册回退承诺 → 分诊定位 typecode 收窄为主因 → 微探针 12 请求探路 → 定向补抓 156 栋 annotated 所在 19 格全量 060000(110 请求 / 2,321 POI)→ mall 重裁标准 (mall 级 ≤150m) OR (060000 ≤100m),最终 10/12 通过 | 预注册回退承诺兑现,收窄不伤主业;残余 V096/V141 归 §7.12 改判后门;残余发现:validation 里 shopping_mall 实为 retail 兜底类(独栋餐饮/街边小商业)8/12 | 数据 `6a21003` + 脚本 `e759e56`;`scripts/a3_batch.py` + `scripts/a3_qc.py` + `scripts/a3_valwin_topup.py` + 决策链证据 `a3_dryrun_v3.py` / `a3_qc_diag.py` / `a3_probe_missed.py` / `a3_grid_audit.py` |
| 2026-07-09 | **EULUC 2022 时间盲区在 A3 网格中的结构性继承**:200 验证行 40 行落网格外(annotated 156 中占 20,与 §14.H 20 unmatched 一一对应);V199/V200 显性证据 —— Amap 探针在其 220m 框内明确有 mall 级 POI(百联临港生活中心 060101\|060102),但成果表 978m 内无 mall,因该区域在 EULUC 2022 分类范围外,继承入 A3 扫描网格 | A3 覆盖论述统一改口径为 "EULUC-scoped coverage";盲区补扫方案随 A3b 8/1 执行卡评估;论文 Methods 中作为 EULUC 数据源固有属性如实报告(与 A4/§7.12 attrition 论述一脉相承) | `scripts/a3_grid_audit.py`;A3b 8/1 执行卡待写 |

_2026-06-18 的四条基础设计决策(mixed_use 垂直复合体、10 层住宅分界、双轨校准目标、纯 Python IDF 流水线)已压缩归档至 §1「已锁定设计基线」。2026-06-20 POI 映射字典、2026-06-21 residential benchmark、2026-07-01 One Click LCA EPD 源、2026-07-03 临港窗口 20 栋修订 + validation 156+44 收官、2026-07-04 ep 字段鉴定为分类编码六条决策随滚动裁剪出表,内容已编码于 §1 / §4 对应行、`data/raw/validation/README.md` §补抽预案、`data/raw/epd_oneclick/`、`data/raw/taobao/shanghai_2026_height/README.md` + `scripts/ep_investigation.py`。2026-07-04 的云端数据通道改道随本次滚动裁剪出表,内容已固化于 §4.6。2026-07-05 FLOOR=2× 定案与金茂销案、2026-07-07 A3 战略重排 α' 与 A4 EULUC 切片收官随本次滚动出表,内容已编码于本文件 §7.7、`data/reference/supertall_height_floor_crosswalk.csv`、`data/raw/euluc/README.md` + `data/reference/euluc_class_mapping.csv`,且 α' 已被 2026-07-09 A3a 收官行(此前出表,见下)实质承接;2026-07-09 A3a 收官行同批出表,编码于数据 `6a21003` + 脚本 `e759e56` + §3 A3b TODO 行。_

---

## 3. Active TODOs

## 3. Active TODOs

_Cross-PR running list of things the owner has agreed to do, things waiting on
external data, and things explicitly deferred. One bullet per item with the
owner ("@owner" / "@claude-code") and a one-line status._

- [@owner + @claude-code, next] **Module B 基线版(ML archetype 推断)**:RF + shape features + EULUC prior + ep 特征;训练真值 = validation 156(mall/mixed_use 弱标签除外,见 §2 2026-07-11 决策);Class 3/10 村居 ~30 万栋作 unlabeled 池;验收要求:sport_culture 拆分(全市 6,103 栋 bundled)、culture(validation 仅 3 栋)/hotel 补样评估、A3b 后跑 retail 特征版对比。brief 由 claude.ai 下发,Claude Code 勿自行开工。
- [@owner + @codespace, before Module C] **CNBH-10m / 3D-GloBFP 重新采集**:2026-07-10 决策由 dropped 升格必要项 —— A5 揭示两商用集均无独立高度测量(2026 height=4×floors 合成量、2023 仅 FLOOR);用途 = GB 规范层高正演的抽样校验 + 超高层乱序高度替换 + 28 栋未配 2023 的 supertall 层数裁定。
- [~~done 2026-07-09~~] A3a 高德 POI 定向抓取:mall+hotel 双 archetype 信号收全,10/12 validation 通过。3,417 请求总消耗(主抓 3,295 + 微探针 12 + 补抓 110);数据 `6a21003`(`data/raw/poi/` + `data/reference/a3_*`),七脚本 `e759e56`。详见 §2 决策 2026-07-09。
- [@owner + @codespace, deferred 2026-08-01] **A3b 全市 060000 补抓(retail 兜底类信号)**:配 8 月 1 日免费额度刷新执行;门槛 8ha,页上限 4,预算 4,500-6,000;当天先 10 次预检验证 typecode 密度,GO 后开跑;script 复用 `a3_batch.py` 改 types 参数,QC 复用 `a3_qc.py`。目的:把独栋餐饮/街边小商业等 retail 案例的 POI 信号收全,消化 §2 2026-07-09 决策里"validation shopping_mall 8/12 是小体量零售"的方法学缺口。**新增职责(2026-07-11,A6.2 定档)**:mall `060000≤100m` 分支重估(A6.2 撤下待此,含 V030/V125 命中口径疑点厘清)+ mixed_use 候选策略重估 + retail 面信号作 Module B 特征输入(特征版对比,顺带量化 A3b 价值)。
- [@owner + @codespace, deferred 2026-08-01] **EULUC 2022 时间盲区补扫评估**:与 A3b 一起或独立执行;候选方案 = 以 2026 建筑矢量的临港/张江覆盖差集为盲区扫描网格,预算另算;或维持 "EULUC-scoped" 口径不补扫,只在论文 Methods 中如实标注 —— 8/1 前二选一拍板。
- [@owner] 设定综合体 (mixed_use) 的 POI 类目多样性熵阈值 —— 原触发条件"模块 A POI 计票实现后再定"已过时(计票 2026-07-11 定案方案 C);随 A3b mixed_use 候选策略重估一并考虑。先验参考:Wang et al. 2026 综合建筑占上海监测面积 22.5%。
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
| CNBH-10m / 3D-GloBFP height raster | **re-activated 2026-07-10**(A5 判定 2026 height=4×floors 合成量、2023 仅 FLOOR,全项目无独立高度测量源;Module C 前采集) | `data/raw/cnbh/`(README 约定保留) | 2026-07-10 |
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

- ~~[Multi-typecode POI 计票策略]~~ **销案 2026-07-11**:采方案 C(1/N 票均分,投票权守恒);A6 实证多码 POI 占比 8.21%,方案 A vs C argmax 翻转全市仅 0.16%、validation 0 —— 方案不敏感,C 的守恒性最稳。见 §2 决策 2026-07-11 行。
- [@owner, surfaced 2026-07-04 from A1 ep 侦查] **ep 字段语义待向供应商核实**:14 值分类编码 {1,2,4,6,7,8,9,10,11,12,13,14,18,26},疑似高度/体量档位(ep=2 ≈ 约百米以上高楼专属);已定案禁作层数,但确切语义未知;Module B 中作免费特征使用不受阻塞。详见 2026 README + `scripts/ep_investigation.py`。
- ~~[金茂入库值]~~ **销案 2026-07-05**:金茂以 height=415(截断)入库,见 `data/reference/supertall_height_floor_crosswalk.csv`。
- [@owner, surfaced 2026-07-04 from A1 QC,范围扩展 2026-07-11] **超高层人工核对名单的具体规则待 Module C 前定**:height 阈值、名单来源(CTBUH/官方名录)、核对与替换流程均未定;A5 后语境更新 —— 全段 height 均为合成量,超高层段还叠加乱序,物理高度一律走 GB 正演 + CNBH 校验;A6 实测 supertall(height≥160 m)全市 121 栋,93 栋已配 2023 取 FLOOR//2,**28 栋未配者层数 NA+flag,待 crosswalk/CNBH 裁定**(随 CNBH 采集一并处理,见 §3)。种子表 `data/reference/supertall_height_floor_crosswalk.csv`(top 20,4 栋 confirmed)。
- [@owner, surfaced 2026-07-05 from A2 侦查] **height=415 / Area 6,027 m² 那栋身份待认领**:与金茂并列的另一栋 415,质心对到 2023 FLOOR=20(疑裙房错配),crosswalk 表中标"待人肉"。
- ~~[validation 对表 7–12 层段 ratio=1.0 异常(n=13)]~~ **销案 2026-07-10**:A5 干净配对(IoU≥0.30)复查定性为点对面错配伪影 —— 13 点全在裙塔密集窗口(莘庄/徐家汇/张江/陆家嘴),干净配对下该段隐含层高稳定 4.0、无 1× 编码分叉,逐点确认 2026 height 与 2023 FLOOR 指向不同建筑。非 FLOOR 编码问题。见 §2 A5 决策行 + PR #10。
- [@owner + @codespace, surfaced 2026-07-07 from A4 交叉验证,更新 2026-07-11] **mixed_use 综合体识别策略**:EULUC parcel-level 分类把综合体裙楼商业信号吞进主导功能(5 栋 validation 综合体 4 栋落 Class 1、12 栋 mall 6 栋落 Class 0)。原策略"Class 1 + 060000 命中"在 A6 实证不可用 —— 060000 全量数据仅存 19 个 validation 格(空间不均匀),分支撤下后候选 479→319、validation 命中 0/5。**不销,随 A3b 全市 060000 落地后重估**;正确归宿倾向 Module B 特征(POI 密度 × footprint × 层数)而非规则阈值。
- [@owner, surfaced 2026-07-07 from A4 交叉验证] **临港 20 栋 validation 落 EULUC 未匹配**:87% 空间匹配率(136/156)里的 20 unmatched 集中临港/张江,机制 = EULUC 2022 版本时点早于新楼建成(与 §7.12 影像 ~2020 attrition 同源、不同数据源、同一时点问题)。**方法学注脚,不销**;论文如实报告"POI seeding 在临港有 EULUC 时点漂移风险"。A6.2 实证补充:全分母 accuracy 中 −6.2pp 即来自这 20 栋 euluc_out 结构性 miss。
- [@owner + @codespace, surfaced 2026-07-09 from A3a QC,范围扩展 2026-07-11] **hotel POI 无 validation 对手 + culture 样本不足**:A3a 抓回 13,493 条酒店 POI,156 栋验证集无 hotel 标注,命中率不可测;A6.1 实证 100200 公寓式酒店住宅过挂(10,882→6,886),已加 EULUC∈{1,2} 门禁。**补样需求扩至 culture**:validation 仅 3 栋 culture 且全落 Class 0/1/10,sport_culture 拆分(全市 6,103 栋 bundled)无从验证。候选方案:(a) 复用 156 栋外候选池抽 hotel 15-20 栋 + culture 若干补标;(b) Module B 阶段批量抽样;(c) Wang et al. 2026 hotel 档 EUI 反推信号密度。短期不阻塞 Module B;Module C 仿真前必须销案。
- [@owner, surfaced 2026-07-09 from A3a QC] **V009 / V096 / V141 shopping_mall 改判后门(§7.12 已留)**:V009 陆家嘴独栋餐饮(备注"餐厅",按 §7.12 标注裁定"店不定义楼")、V096 莘庄 060000 最近 186m、V141 张江 060000 最近 204m;待百度全景 2020 影像人工复核后决定归 unclear / mixed_use / 保持 mall 之一。
- [@owner + @codespace, surfaced 2026-07-09 from A3a grid audit] **EULUC 2022 时间盲区案(见 §2 决策 2026-07-09 行)**:200 验证行 40 行网格外(临港/张江主导);A3 覆盖论述统一改为 "EULUC-scoped";盲区补扫方案 8/1 前拍板(见 §3 TODO)。方法学注脚同 attrition 家族,不销;补扫方案销。
- [@owner + @codespace, surfaced 2026-07-11 from A6.2] **mall 真商场召回不可测案**:validation mall 8/12 系 retail 兜底类,060100 规则全市 1,110 栋 mall 标签无验证对手 —— 与 hotel 同为"无对手"信号,**不作 Module B 训练真值**(§2 2026-07-11 决策)。另记疑点:A3a QC 曾测 mall 级 ≤150m 单独命中 2/14(V030 92m / V125 117m),A6.2 同类规则报 0/14,疑优先级②(Class 1+060100 → mixed_use 候选)截胡或挂靠口径差异,A3b 重估时厘清。A3b + 补标后销。
- [@owner + @codespace, surfaced 2026-07-10 from A5 误差报告] **楼层账本 vs 人工观测误差 → 10 层切分线翻转率(已有数,留作口径)**:149 栋可用样本 MAE 3.04 层、bias −1.19(供应商楼层数系统性偏低)、±2 层内 68.5%;A6.2 终版翻转率 **4.8%**(±2 扰动下 residential mid/high 归属翻转,n=62)—— 切分线稳健性有数,论文 Methods 直接引用。**降级为方法学注脚,不阻塞任何模块**;若 Module E 校准阶段 residential 两 archetype NMBE 异常再回访。
</parameter>

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

**Module B 基线版(ML archetype 推断)**——输入就位:master.gpkg(843,062 行,含 floors/supertall flag/EULUC prior/POI 特征/bundled_label/ep)+ validation 156 真值(mall/mixed_use 弱标签除外)+ 村居 unlabeled 池 30 万栋。两段式:基线版即启;8/1 A3b retail 面信号落地后跑特征版对比。brief 由 claude.ai 下发,Claude Code 勿自行开工。悬案余:ep 语义(供应商)、415/6,027 身份、超高层名单细则 + 28 栋未配 supertall(Module C 前,随 CNBH)、hotel/culture 补样(Module C 前)、V009/V096/V141 改判后门、mall 召回不可测(A3b 销)、EULUC 盲区补扫二选一(8/1)。
