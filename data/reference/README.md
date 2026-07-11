# `data/reference/` — 版本化参考表与对照表

本目录存放**经人工复核、体量小、随仓库版本化**的参考表 / crosswalk /
编码对照。与 `data/raw/`(原始输入,gitignored)、`data/interim/`
(流水线中间产物,gitignored)不同,**本目录内容直接 commit**,是 Module
A–E 各步可引用的稳定查表。

## 文件清单

| 文件 | 来源 | 说明 |
|---|---|---|
| `storey_height_by_band.csv` | A5(`scripts/a5_storey_height.py`) | 2023 FLOOR × 2026 height 分箱层高表 —— **height=4×floors 合成性证据表,非经验换算表**(见下节)。 |
| `supertall_height_floor_crosswalk.csv` | A2(`scripts/floor_semantics.py`) | 超高层 2026 height × 2023 FLOOR 人工替换名单种子(top 20,4 栋 confirmed);Module C 前逐栋核认。 |
| `euluc_class_mapping.csv` | A4(commit `c3609f6`) | EULUC-China 2.0 的 11 类 `Class(int8)` → 中英功能名对照。 |
| `a3_scan_grid.gpkg` | A3(commit `e759e56` / `6a21003`) | 高德 POI 定向抓取的扫描网格几何。 |
| `a3_cell_meta.csv` | A3(同上) | 扫描网格每格元数据(`cell_id, area_ha, dense`)。 |
| `a6_coverage_stats.csv` | A6 Stage 1(`scripts/a6_stage1.py`) | master 覆盖率四个数 ×(全市 / EULUC-scoped)双口径 ×(栋数 / GFA)双权重(见下节)。 |
| `a6_validation_diagnostics.csv` | A6 Stage 1(同上) | validation 分 archetype 规则 accuracy + 10 层翻转率 + 计票 A/C(见下节)。 |
| `a6_class3_10_profile.csv` | A6.1(同上,诊断 d) | Class 3 工业 / Class 10 公园内建筑画像:层数×面积分位数(村居假说验证)。 |

---

## `storey_height_by_band.csv` —— 合成性证据表(**非**经验换算表)

### 这张表是什么、不是什么

A5 用 2023 集(`FLOOR`=2×层数)与 2026 集(`height`, m)在干净配对
(最大交叠 IoU≥0.30,n=354,241)上,按 `floors_2023 = FLOOR // 2` 分箱统计
经验层高 `height / floors_2023` 的中位 / P25 / P75 / n。

**关键结论:2026 `height` 是合成量,不是独立实测。** 证据(`scripts/a5_storey_height.py`
可完整复现):

- 干净配对 **82.5%** 满足 `height == 2×FLOOR`(等价 `height == 4 m × floors`);
  限最高质量配对(IoU≥0.7)升到 **87%** —— 越干净越贴合,说明 4.0 是信号而非错配噪声。
- 逐层众数 `height = 4×floors`(1→4, 2→8, 3→12, … 10→40);`height` 99.7% 可被 4 整除。
- 因此各箱经验层高中位**恒为 4.000 m**(见 `frac_height_eq_2x_floor` 列量化合成占比)。

**推论:**两集共享同一楼层数血统(2023 存 2×层数,2026 以固定 4 m/层折算高度)。
这张表里的 4.0 m **是供应商折算假设,不是上海真实层高**(住宅 GB 口径约 2.9–3.0 m)。
所以:

- ✅ 本表**可用作**:height↔floor 的**内部一致性换算**(见 A6 规则),以及
  "2026 height 为合成量"这一数据事实的**证据留档**。
- ❌ 本表**不可用作**:上海真实经验层高来源。Module C 若需真实楼高做几何,
  须另引外部高度源或 GB 层高×层数正演,不得把本表 4.0 m 当实测层高。

### 列

| 列 | 说明 |
|---|---|
| `band` | floors_2023 分箱标签(`1-3` / `4-6` / `7-9` / `10-18` / `19-30` / `31-39`) |
| `floors_min`, `floors_max` | 箱的 floors_2023 闭区间 |
| `n_clean_pairs` | 该箱干净配对数(IoU≥0.30) |
| `storey_height_median_m` / `_p25_m` / `_p75_m` | `height / floors_2023` 的中位 / P25 / P75(m) |
| `frac_height_eq_2x_floor` | 该箱内 `height == 2×FLOOR` 精确占比(合成度指纹,越高越合成) |

`31-39` 箱系 owner 复核 PR #10 后加(2026-07-10);n=193,统计同口径。

### 覆盖范围与超高层旁路

- **本表覆盖 floors_2023 1–39**。
- **超高层(≥40 层,即 `height ≥ 160 m`)不进本表**:该段 2026 `height`
  已知乱序 / 截断(上海中心实高 632 m 入库 351、环球金融 492 m 入库 361、
  金茂 415 m 截断,见 `supertall_height_floor_crosswalk.csv` 与 PROJECT_MEMORY §7.7),
  连合成的 4 m/层关系也不成立,故排除,走 crosswalk 逐栋人工替换。

### A6 换算规则(2026 全市层数推断)

对 2026 每栋建筑,由 `height` 推层数:

```
if height >= 160:          # supertall flag —— 不走 /4 通道
    floors = 查 supertall_height_floor_crosswalk.csv / 人工替换名单
else:
    floors = round(height / 4)     # = round(height / storey_height);本表全箱 storey=4.0 m
```

说明:
- `160 m = 40 层 × 4 m`,与本表 ≥40 层排除边界一致 —— `height≥160` 即"若按 /4 会落 ≥40 层"。
- 阈值 `160 m` 比 §7.7 的"≥200 m 乱序"更保守,把所有会被 /4 映射到 ≥40 层的建筑一并 flag,
  避免用不可信的超高层 height 直接 /4。
- 因 `height` 合成于 4 m/层,`round(height/4)` 实质是**读回 2026 数据集自带的楼层数**,
  而非独立高度反推。A5 validation(149 可用样本)反推 floors 的误差(MAE 3.04 层、±1 50.3%)
  主体来自 2026 自带层数与人工观测之差,非层高模型误差。

---

## A6 Stage 1 — master 表 + 覆盖率(规则打标)

### master 产品位置(体积失控,走私仓)

84 万栋 master 含几何,GeoJSON 体积失控 → 落 **GPKG**;>100 MB 走私仓 zip 通道:

| 项 | 值 |
|---|---|
| 文件 | `module_a_master.gpkg`(843,062 栋,EPSG:4326) |
| 私仓 | `Yuqian_Shanghai-Energy-data` git 树 `module_a_master.gpkg.zip`(~94 MB) |
| 未压 | ~239 MB;主仓 gitignored(`outputs/module_a_master.gpkg`) |
| 复现 | `python scripts/a6_stage1.py`(输入见脚本 docstring;规则见 `config/a6_rules.yaml`) |
| MD5 | 见私仓 `md5_checksums.txt` |

**schema**:`height, area_m2, is_supertall, floors, floors_source, euluc_class,
euluc_out, mall_signal, hotel_signal, mixed_use_candidate, archetype, label_rule,
bundled_label, geometry`(`bundled_label` A6.1 新增:sport_culture 等捆绑标签 flag)。

### 覆盖率四个数(`a6_coverage_stats.csv`,A6.1 修订)

栋数 / GFA(=footprint 面积 × floors)双权重 × 双口径:

| 口径 | 权重 | rule-labeled | ML(占位) | unknown | height-complete |
|---|---|---|---|---|---|
| 全市(843,062) | 栋数 | **56.98%** | 0% | 43.02% | 99.997%(28 NA+flag) |
| 全市 | GFA(2.73 Gm²) | **63.78%** | 0% | 36.22% | 99.99%(面积加权*) |
| EULUC-scoped(787,696) | 栋数 | **60.96%** | 0% | 39.04% | 99.997% |
| EULUC-scoped | GFA(2.63 Gm²) | **66.23%** | 0% | 33.77% | 99.99%(面积加权*) |

\* floors=NA 无 GFA,GFA 口径的 height-complete 改按 footprint 面积加权(否则恒 100% 无意义)。

- **unknown 结构(A6.1)**:全市 362,655 unknown = 公园(Class 10)173,213 +
  工业(Class 3)126,045 + euluc_out 55,156 + Class 2 商业残余 8,241。
  前三项结构性落 14 类 UBEM 口径外/盲区,非打标失败;
  **GFA 口径下 unknown 占比降至 36.2%**(unknown 建筑偏小偏矮,见诊断 d)。

### 规则打标 accuracy(`a6_validation_diagnostics.csv`,A6.1 修订)

- 全分母 accuracy **42.3%**(n=156,含捆绑命中口径);**同基准对照**(in-parcel
  n=136 同分母):EULUC-direct-only **54.4%** vs 全规则 **48.5%** → POI 覆盖净效应
  **−5.9pp**(A6.1 hotel 门槛修订前为 −12.8pp,已减半)。
- 全分母与 in-parcel 差值主因:**20 栋 euluc_out**(临港/张江 EULUC 2022 时间盲区,
  规则层面全 miss,§14.H 同源)。
- 残余 POI 拖累主体是 **mall 规则**(validation 内 16 flip / 5 hit,12 residential
  被 06≤100m 街铺信号翻标)—— mall 规则本轮按 owner 指令**不动**,留案。
- culture 0/3 说明:3 栋 culture validation 落 Class 0/1/10 parcel,**无一落 Class 9**,
  sport_culture 捆绑无从命中 —— 系 validation 抽样地理,非机制失效
  (sport_culture 全市打标 6,103 栋)。
- 10 层线 ±2 扰动翻转率 **6.1%**(n=49)。
- 计票 A vs C:多码 8.21%;全市 argmax 翻转 20 栋(0.16%),validation 0 翻转
  → **不敏感,采守恒方案 C**。

### 诊断 d — Class 3/10 建筑画像(`a6_class3_10_profile.csv`,A6.1 新增)

| Class | n | floors 中位(P10–P90) | ≤3 层 | area 中位(P10–P90)m² |
|---|---|---|---|---|
| 3 工业 | 126,324 | 2(2–4) | 86.6% | 504.6(135.5–3,284.7) |
| 10 公园 | 173,898 | 2(2–5) | 85.3% | 300.1(119.2–1,083.8) |

低层小 footprint 主导 → **村居/附属小建筑画像成立**(工业尾部 P90 3,285 m² 为厂房/仓储);定性裁决留 owner。

### 规则表(`config/a6_rules.yaml`,A6.1 修订)

优先级 ① supertall(横切 flag)② mixed_use 候选 ③ mall ④ hotel ⑤ EULUC 直接命中类
⑥ unknown。A6.1(owner 复核 PR #11 后):hotel `100200` 仅在建筑落 EULUC Class 1/2
parcel 时计信号;Class 9 → `sport_culture` 捆绑标签(计入 rule-labeled,
`bundled_label` flag,Module C 前拆分);Class 2 → unknown 降级(euluc_class 字段保留);
Class 3/10 维持 out_of_taxonomy → unknown。
