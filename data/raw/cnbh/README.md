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
不可见)——与论文已知局限一致。含义:该源适用于中低层段层高校验;
28 栋 supertall 裁定如何用它(或退回 crosswalk)是下一对话的分析题。
