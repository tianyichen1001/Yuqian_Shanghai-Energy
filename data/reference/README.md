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
