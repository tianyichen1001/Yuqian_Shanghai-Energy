# C 引擎 — EnergyPlus 版本钉死与安装校验链

## 版本(钉死,勿静默升级;2026-07-12 补充指令第 3 条口径)

- **实际安装版本**:`energyplus --version` 实测输出
  `EnergyPlus, Version 26.1.0-6f2e40d102`(NREL GitHub release `v26.1.0`,
  Linux-Ubuntu24.04-x86_64 tarball,229 MB)。
- **安装路径**:容器 `/opt/EnergyPlus-26.1.0`(tar 解包;可用
  `BS_EPLUS_DIR` 或 `--eplus-dir` 覆盖;Codespace 重建后需重装)。
- **安装渠道**:NREL GitHub release 资产经 gh-proxy.com + ghfast.top
  双镜像下载(**非 PyPI** —— PyPI 无官方 energyplus 发行版,实测
  `pip index versions energyplus` 无匹配)。
- config 镜像:`config/c_engine.yaml` → `energyplus.version / build_sha`。

## 2026-07-12 安装校验链(会话 GitHub 网关拦截 NREL 官方直链,走镜像)

1. 会话内 `github.com`/`api.github.com` 对 scope 外仓库一律 403
   (记忆 §4.6 已知),NREL release 直链与 codeload 均不可用;
2. 从两个独立镜像各下载一份:`gh-proxy.com` 与 `ghfast.top`;
3. 两份 sha256 **完全一致**:
   `b651f4197bfc147a0f66dc92c58895d1748bdadb7a0288145fa9d50375edfbca`;
4. 解包后二进制自报 `EnergyPlus, Version 26.1.0-6f2e40d102`,与官方
   release 页(WebFetch 走会话外通道读取)公布的构建哈希逐字符一致;
5. 冒烟测试:自带 `1ZoneUncontrolled.idf` × 仓内 CSWD EPW,
   `EnergyPlus Completed Successfully`(0 Severe/Fatal)。

## 入口

- `python scripts/c_engine/c1_office.py` — 块 1 办公端到端
  (shoebox 生成 → E+ → 月度分项 EUI → 对王 144 点 sanity,不调参)。
- 依赖:`pip install eppy --no-deps && pip install munch six decorator
  beautifulsoup4`(eppy 的 tinynumpy 依赖在 Py3.11 构建失败,核心不需要)。
  geomeppy 依赖 eppy 同因不装;几何全部手写 eppy 对象(合规:纯 Python
  eppy 管线,CLAUDE.md §4.3)。

## 口径审计三笔(2026-07-12 owner 补充指令第 1 条;结论:未发现口径不一致,NMBE +5.5% 不修正)

1. **IdealLoads→电耗换算链**:E+ 月度热量(J;主读
   `DistrictCooling:Facility` / `DistrictHeatingWater:Facility` 电表,
   备援 `Zone Ideal Loads Supply Air Total Cooling/Heating Energy` 变量,
   `parse.py`)→ ÷3.6e6 → kWh 热量 → **÷COP** → kWh 电。
   COP 冷 **3.5** / 热 **2.5**,存于各
   `config/archetypes/<type>.yaml` `hvac.cop_cooling / cop_heating`;
   **出处 = v0 假定值(常规电制冷冷水机组 / 空气源热泵采暖习惯量级),
   非规范值**,已标校准变量。照明/设备电表直读,不经 COP。
2. **EUI 分母**:我方 = shoebox 全楼面面积(footprint × 层数,
   `shoebox.conditioned_area_m2`);王 144 点 = 监测平台按建筑面积的
   月度电耗强度(`config/calibration_targets.yaml` 头注)→ **同基**
   (均为 kWh/m² 建筑面积)。已知模型侧偏差:shoebox 将 100% 面积
   视为空调区,实楼含非空调面积(核心筒/楼梯间等)→ 同分母下 sim
   总量的结构性偏高倾向 —— 属模型简化(校准变量),非分母错配,
   不触发 NMBE 修正。
3. **气象年差异(已知偏差源)**:CSWD 为**典型气象年**(多年历史
   统计合成),王 2026 矩阵为近年**实际运行年**;近年上海夏季偏热
   (2022/2024 极端高温)→ CSWD 供冷侧系统性偏低为已知偏差源,
   量化归论文敏感性段(TMYx.2011-2025 备跑,本阶段不跑)。

## GB 50189-2015 来源核验(2026-07-12 owner 补充指令第 2 条)

- gbeca.org 所谓 PDF 链接**实测返回 HTML 页面而非 PDF 文件**,无法按
  指令抽验;改用多个公开副本交叉核对,结果:
  - ✅ **已核验 3 项**:屋面(D≤2.5)K≤**0.40**;外墙含非透明幕墙
    (D≤2.5)K≤**0.60**;单一立面窗墙比上限 **0.70**(3.2.2 条原文:
    "其他地区甲类公共建筑各单一立面窗墙面积比(包括透光幕墙)均不宜
    大于 0.70")。
  - ⚠️ **未获独立确认 2 项**(公开副本表格均为图片/残缺):外窗
    0.3<WWR≤0.4 档 K≤2.6 / SHGC 东南西 0.40·北 0.44;0.2<WWR≤0.3 档
    K≤3.0 / SHGC 0.44 —— 维持"转录待复核"状态,owner 对照纸本定版。
- **网络副本均为非官方副本,仅作参数参考**;工程判定以正式出版文本
  为准。

## v0 已知局限(记账,校准阶段处理)

- HVAC 用 IdealLoads:供冷/供热为热量,经 config COP(v0 典型值
  3.5/2.5)换算电耗;**不含风机/水泵/生活热水/电梯**。
- 时间表为 GB 50189-2015 附录 B 办公工况的分段简化,非逐时率原文。
- 围护结构限值为二手转录(官方 PDF 会话网络不可达),owner 复核后修订
  `config/archetypes/office.yaml`。
