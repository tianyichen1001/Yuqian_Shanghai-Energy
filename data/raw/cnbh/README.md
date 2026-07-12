# CNBH-10m — 上海建筑高度栅格切片(2020,10 m)

> 全项目唯一**独立高度测量源**(A5 判定:2026 集 height=4×floors 合成量、
> 2023 集仅 FLOOR)。2026-07-10 由 dropped 升格必要项;2026-07-12 采集入库。
> 用途(Module C 前):GB 规范层高正演的抽样校验、超高层乱序高度替换、
> 28 栋未配 2023 的 supertall 层数裁定。**本目录只记账采集;误差分布与
> 超高层裁定分析归后续对话。**

## 来源(只认官方 DOI)

- **数据**:Wu W. *CNBH-10 m: A first Chinese building height at 10 m
  resolution*,Zenodo **DOI 10.5281/zenodo.7923866**(latest 版本;
  concept DOI 10.5281/zenodo.7015081),License **CC-BY-4.0**。
- **论文**:Wu et al., *A first Chinese building height estimate at 10 m
  resolution (CNBH-10 m) using multi-source earth observations and machine
  learning*, **RSE** 291:113578, DOI 10.1016/j.rse.2023.113578
  (全国精度 RMSE 6.1 m / MAE 5.2 m / R 0.77;基准年 2020)。
- 备选源 3D-GloBFP 未动用(CNBH 官方源即命中,无需降级)。

## 源瓦片(命名按瓦片中心,2°×2°,EPSG:32651 原生)

| 瓦片 | 覆盖 (lon×lat) | 大小 | MD5(与 Zenodo 元数据命中) |
|---|---|---|---|
| `CNBH10m_X121Y31.tif` | [120,122]×[30,32] | 335.2 MB | `72fccc03160010daeb697220e2c0db1b` |
| `CNBH10m_X123Y31.tif` | [122,124]×[30,32] | 15.8 MB | `cbf6c31733dac9f273a4ccbb2a7df829` |

master 全部建筑(bbox 东至 121.98°E)落 X121Y31;X123Y31 仅补 GADM
上海东部外礁水域。

## 切片处理(`scripts/cnbh_clip_shanghai.py`)

GADM 4.1 `NAME_1=='Shanghai'` 市界 mask+crop(与 A4 EULUC 切片同口径)
→ 两瓦片 merge 单文件;**不重采样、不改值**;deflate+predictor 压缩。

## 成品(私仓 git 树,gitignored 于此)

- `Yuqian_Shanghai-Energy-data/cnbh10m_shanghai_2020.tif.zip`
  **76.3 MB**(<100 MB 单文件,无需分片);zip MD5
  `075f92591ed7d363bbcbc8f96b1dacbb`,内层 tif MD5
  `e15fc47bfc5696d41ffd811f90e15d2e`(均已记入私仓暗号本)。
- 栅格:18837×14622 px,float32,EPSG:32651,10 m;nodata=-9999(界外),
  **界内无建筑像元 = NaN**(源编码,保留)。

## 像元统计概要(采集 QC,非分析)

| 项 | 值 |
|---|---|
| 界内像元 | 68,812,724 |
| 有高度(>0) | 16,644,950 |
| NaN(无建筑) | 52,167,774 |
| 高度 min / p50 / mean | 8.5 / 16.7 / 17.97 m |
| p95 / p99 / **max** | 29.1 / 34.5 / **41.7 m** |

⚠️ max=41.7 m:CNBH-10m 对高层/超高层**严重饱和**(上海中心实高 632 m
不可见)。成因法证见下节(2026-07-12 块 3 定案)。

## 40m 封顶法证(2026-07-12,只查因;复现 `scripts/cnbh_saturation_probe.py`)

**结论:产品固有,非切裁处理引入。**三路证据:

1. **切裁前原始瓦片**:X121Y31 全域([120,122]×[30,32],含苏州昆山等,
   6,834 万有效像元)max = **43.02 m**,>45 m 像元 **0 个**;顶端直方图
   (40,41] 2,121 / (41,42] 330 / (42,45] 35,呈**软饱和渐灭**而非固定值
   硬截断;p99.9 = 37.3 m。X123Y31 max = 38.2 m。切裁后成品 max
   41.69 ≤ 43.02(子集关系成立,处理链未改值)。
2. **地标像元实测**(3×3 窗口 max,crosswalk confirmed 坐标):
   金茂大厦 实高 420.5 → CNBH **38.4 m**(−91%);环球金融中心 492 →
   **36.3 m**(−93%);上海中心 632 → **37.7 m**(−94%)。
3. **产品文档**:Wu et al.(RSE 291:113578)与 Zenodo 元数据均**未声明
   取值范围上限**;方法为像元级 Random Forest **回归**(全国 RMSE 6.1 m,
   R=0.77),软饱和形态与 RF 回归对稀缺极端样本的均值回归行为一致
   (训练参考样本中超高层极少);论文局限节仅泛提"复杂 3D 结构不确定性",
   未单列高层低估 —— 本法证即为该缺口的项目内补充证据。

## CNBH 可用范围(据上,供验证链正段引用)

- **可信段 ≤~30 m(约 ≤8-10 层)**:占界内有高度像元 >97%,相对
  全国 RMSE 6.1 m 可控 —— GB 规范层高正演的抽样校验主用段。
- **谨慎段 30-43 m**:进入软饱和肩部,系统性低估风险随高度上升。
- **不可用段 >43 m**:产品值域之外,任何更高建筑必然被压平;
  **28 栋未配 supertall 的层数裁定不能使用 CNBH 绝对值**(至多作
  "该处确有高层"的存在性信号)——裁定方案归 CNBH 验证链正段,
  本节不做处置。
