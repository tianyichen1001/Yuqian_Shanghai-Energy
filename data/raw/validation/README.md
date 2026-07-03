# `data/raw/validation/` — Validation Set #9(层数/功能人工核实验证集)

> 数据源 #9,Phase 1 数据采集的最后一项。2026-07-03 记账收官。
> 本目录下 `working/` 为机器生成的预标注资产,**任何情况下不要改动**
> (见 `working/README.md`)。

## 文件清单

| 文件 | 说明 |
|---|---|
| `shanghai_validation_set_master.xlsx` | 标注母表(owner 标注工作簿终稿,含标注原文与修正痕迹) |
| `shanghai_validation_set_v0.csv` | 机器可读定稿 v0,200 行,UTF-8(带 BOM),供 Module A 校验脚本直接消费 |
| `working/` | 抽样流水交付物(workbook / KML / 抽样参数 README),PR #6 产出,勿动 |

## 数据来源

1. **抽样工作包(PR #6,2026-07-02)**:`scripts/build_validation_workbook.py`
   三段流水(extract → checkpoint 1 → links-test / checkpoint 2 → emit),
   seed=42,5 窗口 × 40 栋(陆家嘴 / 徐家汇 / 莘庄 / 张江 / 临港),
   EPSG:4547 度量开窗,面积下限 100 m²,同款去重。窗口边界、去重
   统计与盲测规则见 `working/README_working.md`。
2. **人工标注(2026-07,owner)**:逐栋通过百度街景 / 卫星影像核实
   建筑功能与层数,盲测(标注时不可见 Taobao height 字段)。

## 核实率:156 / 200

| status | 行数 | 说明 |
|---|---|---|
| `annotated` | 156 | 功能 + 层数完成人工判读 |
| `not_found` | 44 | 无法定位:街景影像约 2020 年,早于建筑建成 |

44 栋 not_found 按窗口分布:**临港 20**、**张江 13**、莘庄 8、徐家汇 3、
陆家嘴 0 —— 集中在临港 / 张江两个新开发片区,与"影像早于建成"的
成因一致。

## 标注修正(两处)

| val_id | 修正 | 依据 |
|---|---|---|
| V002 | 层数记 **23**(按最高塔) | 标注原文"门诊 10 + 住院 23",总层数按最高塔记 |
| V061 | 补勾 **mixed_use**(is_podium_tower=1,裙楼 3 层 + 塔楼 18 层) | 综合体特征明确,标注时漏勾,定稿时补 |

## 字段说明(`shanghai_validation_set_v0.csv`)

| 列 | 类型 | 说明 |
|---|---|---|
| `val_id` | str | `V001`–`V200`,无缺无重;V 段与窗口对应关系见 `working/README_working.md` |
| `lat`, `lon` | float | 建筑代表点,**WGS84**(源自 2026 Taobao footprints,checkpoint-2 单点判定确认真 WGS84);均落在上海范围内(实测 lat 30.90–31.24, lon 121.38–121.93) |
| `area` | str | 抽样窗口 slug(`lujiazui` / `xujiahui` / `xinzhuang` / `zhangjiang` / `lingang`);**注意:列名沿用工作簿的"片区",不是面积** |
| `sample_mode` | str | 恒为 `window`(本集全部为开窗抽样) |
| `status` | str | `annotated` / `not_found`;`not_found` 行的标注列全部留空 |
| `archetype` | str | 人工判读功能,取 `config/archetypes.yaml` 的 14 类之一或 `unclear`(1 行);residential 不细分 mid/high rise(由层数派生) |
| `is_podium_tower` | 0/1 | 是否裙楼 + 塔楼组合体 |
| `podium_floors` | int | 裙楼层数(仅组合体填写) |
| `floors_observed` | int | 人工判读层数,1–101;组合体记最高塔层数(V002 规则) |
| `floors_confidence` | str | `high` (110) / `medium` (37) / `low` (9) |
| `evidence` | str | 判读依据:`建筑外形` / `其他` |
| `streetview_vintage` | str | 街景影像年份,本集约为 `2020` |
| `notes` | str | 自由文本(标注原文、同款自动识别提示等) |

## 补抽预案(临港 top-up,留档备用)

临港窗口有效样本 20 栋(40 抽样 − 20 not_found),低于原规格 30–50。
2026-07-03 决策:**规格修订为 20 栋记账收官**,层数→高度关系以
2023 Taobao FLOOR 集(412,100 栋)为主力校准,不立即补抽。

**触发条件**:Module A 的临港层数推断与本集 20 栋 annotated 显著不符时,
启动补抽。

**补抽方案**(参数留档,保证可复现):

- 窗口:沿用 lingang 窗口(中心 30.9120, 121.9180,halfwidth 1500 m,
  必要时按 +300 m 步长扩窗,同 PR #6 规则);
- 剔除本集已用的候选行号(V161–V200 对应的 source rows,见
  `working/` 内部候选表);
- 抽样方式:按 **height 分层**抽样(替代纯随机,保证高层段覆盖);
- 随机种子:**seed=43**(与本集 seed=42 区分);
- 标注影像优先选用 2023 年以后的街景 / 卫星源,避免再次"影像早于建成"。
