# Shanghai Building Footprints — 2023, Central Districts (with FLOOR)

## Provenance

- **Source:** Commercial vendor via Taobao（淘宝代购）
- **Acquired:** 2026-06-21 (local) / **2026-07-05 ingested via 云端 git 通道**（见 PROJECT_MEMORY §4.6）
- **License:** Commercial dataset; redistribution not permitted.

## Specification

| Attribute | Value |
|---|---|
| Coverage | Shanghai central urban area (市区; validation 对表实证不覆盖临港等外围) |
| Reference year | 2023 |
| File format | ESRI Shapefile (.shp + .shx + .dbf + .prj + .cpg; 无 .qix/.sbn/.sbx 索引) |
| CRS | WGS84 (EPSG:4326) — verified via .prj + geopandas 复测 2026-07-05 |
| Feature count | **412,099** buildings (measured 2026-07-05; vendor claimed 412,100 — off by one, DBF 头部自洽, 与 2026 集差 1 先例同判, 采信实测) |
| File size | 76 MB (uncompressed) |
| MD5 (.shp) | `674A7662AF9E36992D04F7494D3203BA`（与 owner 本地 QC 版本同一文件, 2026-07-05 复核） |
| MD5 (zip, cloud archive) | `6E033592072263F658DA637B504A38E4` (`shanghai_2023_floor.zip`) |

## Attributes — schema 极简

| Column | Type | Range | Notes |
|---|---|---|---|
| `FLOOR` | **str**（需转 int, 全部可无损转换, 0 空值） | 2 – 236, **68 个唯一值全为偶数** | 语义见下节。 |
| `geometry` | polygon | — | 唯一的另一列。 |

**没有** district / city / province / Area / height / 名称等任何其他属性。`.cpg` 声明 **GBK**(与 2026 集的 UTF-8 不同),但本集无中文字段(FLOOR 为纯数字文本),编码选择无实际影响;规程上仍按声明以 `encoding="gbk"` 读取。

## FLOOR 语义（本 README 核心, 2026-07-05 定案）

**FLOOR = 2 × 实际层数。换算式:`floors = FLOOR // 2`。**

三路独立证据(完整复现:`scripts/floor_semantics.py`):

1. **超高层锚点(决定性)**:金茂大厦 FLOOR=176 → 88 层 ✓;环球金融中心 202 → 101 层 ✓;上海中心 236 → 118 层(常见标注)✓;白玉兰广场 132 → 66 层且落虹口区 ✓ —— 四个可独立核对的地标层数+区位全部吻合。
2. **规模化旁证**:2026 集质心落入 2023 面共 369,035 对,抽 10,000 对:height/FLOOR 中位 2.0 m(按"FLOOR=层数"隐含层高 2 m,物理不合理);height/(FLOOR/2) 隐含层高中位 **4.0 m**,86.7% 落 2.5–5 m 合理区间。
3. **validation set 对表**:132 个匹配样本 FLOOR÷标注层数 **中位恰为 2.000**;低层段(1–6 层,n=83,错配风险最低)|FLOOR/2−标注| ≤1 层占 70–73%。高层段大偏差为塔楼密集区点对面错配噪声(裙塔混淆、双向乱跳),非语义反证。

全表 412,099 行 **0 个奇数** —— 偶数指纹本身即"2×"的结构性证据。

## 旧过滤规则作废声明

~~`df.loc[df["FLOOR"] > 130, "FLOOR"] = pd.NA` 然后用 height/POI 插补~~ —— **作废(2026-07-05)**。FLOOR>130 的 9 行按"2×"全部为合法超高层:132→66、140→70、152→76、176→88(金茂)、192→96(×2)、202→101(环球,×2)、236→118(上海中心),隐含层数 66–118,无一超过上海真实极限。这 9 行是**超高层校准点**,不是脏值,不得过滤。

## Module A Ingestion Rules

- **Read syntax:**
```python
  gdf = gpd.read_file("path/to/2023 Building.shp", encoding="gbk")  # per .cpg
  gdf["floors"] = gdf["FLOOR"].astype(int) // 2                     # 2026-07-05 定案换算
```
- **Use case:** Height→Floor 经验层高分布的**校准集**(与 2026 集 height 空间配对),用于 2026 全市层数推断
- **超高层校准种子:** `data/reference/supertall_height_floor_crosswalk.csv`

## 已知局限

- **与 2026 集无公共属性键**(唯一共有列是 geometry)——双数据集关联只能**空间 join**。
- **两版 footprint 切分不一致**(不同年份、不同采集批次):塔楼密集区(如陆家嘴)质心/点位易落入裙房或邻栋,点对面匹配需按"裙塔混淆"预设错配率;validation 对表实测高层段错配显著。
- 市区覆盖边界未在属性中标示(无 district 字段),覆盖范围需空间求证;validation 200 点中临港 35/40 未匹配属预期。

## Storage

- **Repo:** this directory contains only README (per SOP, large binaries gitignored)
- **Cloud archive (正式通道):** private data repo `Yuqian_Shanghai-Energy-data` git 树 `shanghai_2023_floor.zip`(main),会话内 `git pull` 后按 zip MD5 对暗号、解压至本目录
- **Local path:** `E:\Energy\Yuqian_Shanghai_Energy_data\2023 Building\`

## Cross-Reference

- Companion dataset: `data/raw/taobao/shanghai_2026_height/` — primary (all-district, height-labeled)
- 超高层 height–FLOOR 对照种子表: `data/reference/supertall_height_floor_crosswalk.csv`
- QC 脚本: `scripts/qc_shanghai_2023.py`;语义鉴定: `scripts/floor_semantics.py`
