# Module B — ML Archetype Inference

Corresponds to the **ML Archetype Inference** section of the paper.
两段式(§2 决策 2026-07-11):**B1 基线版**(本目录现状)→ A3b retail
面信号落地后跑**特征版对比**。

## B1 基线版(2026-07-12 工作令)

- 训练真值 = validation 156 annotated,剔除 V009/V096/V141(待改判);
  mall(1,110)/mixed_use 候选(319)规则弱标签**不作训练真值**。
- 类体系 = 真值实际出现的类(人工标注为准);样本 <5 的类如实入表并
  标记"不可学,待 B2 补样"。
- 模型 = RandomForest `class_weight='balanced'`,基线**不做 SMOTE**;
  ~5km 网格 GroupKFold 空间 CV(防泄漏);bootstrap 95% CI。
- 评估双分母:(a) 全匹配真值集(156 与训练真值 153 两口径);
  (b) in-parcel n=136 同分母对比规则 52.2% / EULUC-only 54.4%(A6)。

## Inputs(--data-dir 下,不入 git;MD5 见私仓暗号本)

- `module_a_master.gpkg` — A6 规则打标 master(843,062 栋)
- `euluc_shanghai_2022.gpkg` — EULUC parcel(55,124)
- `2026 Building/2026 Building.shp` — ep / district 按行序回取

## Features(`features.py` — 仅 master + EULUC,零 POI)

| 系 | 特征 |
|---|---|
| 形状 | `area_m2`, `perimeter_m`, `compactness (4πA/P²)`, `aspect_ratio`(最小外接矩形), `convexity`(面积/凸包) |
| 规模 | `floors_feat`, `gfa_m2`, `is_supertall_int` |
| 邻域 | `n_bld_100m`, `nbr_fp_med_m2`, `nn_dist_m` |
| parcel | `euluc_*` one-hot(含 out), `parcel_area_m2`, `n_bld_in_parcel`, `gfa_share_parcel`, `in_parcel` |
| 供应商 | `ep_*` one-hot(14 值分类编码,语义待核实,禁作层数) |

**明确不进特征**:一切 POI 派生列(mall_signal / hotel_signal /
mixed_use_candidate / label_rule / bundled_label —— A6.2 空间不均匀教训)、
district(validation 仅 5 窗口,防伪相关)。

## Outputs

| Path | 入 git | Description |
|---|---|---|
| `data/reference/b1_*.csv`(6 个汇总) | ✓ main | 双分母指标 / 逐类 P/R/F1 / 混淆矩阵 / 特征重要性 / 置信度分布 / 临港张江诊断 |
| `data/raw/validation/b2_annotation_list_v0.csv` | ✓ main | B2 补标清单(分层抽样 seed=20260712) |
| `<out-dir>/b1_citywide_predictions.parquet` | ✗ | 843,062 栋预测+置信度(仅诊断,不落 master) |
| `<out-dir>/b1_model.joblib` | ✗ | 训练好的 RF |

入口:`python scripts/b1_baseline.py --data-dir <dir>`;
参数集中在 `config/b1_baseline.yaml`;单测 `tests/test_b1_features.py`。
