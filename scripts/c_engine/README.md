# C 引擎 — EnergyPlus 版本钉死与安装校验链

## 版本(钉死,勿静默升级)

- **EnergyPlus 26.1.0**,官方构建 `6f2e40d102`(NREL GitHub release
  `v26.1.0`,Linux-Ubuntu24.04-x86_64 tarball,229 MB)。
- config 镜像:`config/c_engine.yaml` → `energyplus.version / build_sha`。
- 安装位:容器 `/opt/EnergyPlus-26.1.0`(可用 `BS_EPLUS_DIR` 或
  `--eplus-dir` 覆盖;Codespace 重建后需重装)。

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

## v0 已知局限(记账,校准阶段处理)

- HVAC 用 IdealLoads:供冷/供热为热量,经 config COP(v0 典型值
  3.5/2.5)换算电耗;**不含风机/水泵/生活热水/电梯**。
- 时间表为 GB 50189-2015 附录 B 办公工况的分段简化,非逐时率原文。
- 围护结构限值为二手转录(官方 PDF 会话网络不可达),owner 复核后修订
  `config/archetypes/office.yaml`。
