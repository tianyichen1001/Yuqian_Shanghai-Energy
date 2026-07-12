"""块 1|C 引擎端到端:办公 shoebox → E+ → 月度分项 EUI → 对王 144 点 sanity。

sanity check ≠ 校准:只对办公列比量级与季节形状(夏峰冬次峰、春秋谷),
不调任何参数;偏差如实记录(NMBE + 逐月比值)。

运行:python scripts/c_engine/c1_office.py [--eplus-dir DIR] [--out-dir DIR]
产出:
  outputs/simulation/runs/office_v0/(E+ 原生输出,gitignored)
  outputs/figures/c_engine/c1_office_sanity.png(.gitignore 例外,入库)
  data/reference/c1_office_v0_monthly.csv(月度 12 数 + sanity 表,入库)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.calibration.nmbe import monthly_nmbe_table, nmbe_pct   # noqa: E402
from buildings_shanghai.simulation import parse as eparse                      # noqa: E402
from buildings_shanghai.simulation import runner, shoebox                      # noqa: E402

BENCH = PROJECT_ROOT / "data/raw/benchmark/wang_2026_public_monthly.csv"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eplus-dir", default=None)
    ap.add_argument("--out-dir", type=Path,
                    default=PROJECT_ROOT / "outputs" / "simulation" / "runs" / "office_v0")
    args = ap.parse_args()

    engine = yaml.safe_load(open(PROJECT_ROOT / "config" / "c_engine.yaml"))
    arch = yaml.safe_load(open(PROJECT_ROOT / "config" / "archetypes" / "office.yaml"))
    eplus_dir = runner.resolve_eplus_dir(engine, args.eplus_dir)
    epw = PROJECT_ROOT / engine["weather"]["epw"]
    assert epw.exists(), f"EPW 不存在: {epw}"

    print(f"[c1] EnergyPlus {engine['energyplus']['version']}-"
          f"{engine['energyplus']['build_sha']} @ {eplus_dir}")
    idf = shoebox.build_shoebox(arch, engine, eplus_dir / "Energy+.idd", epw)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    idf_path = args.out_dir / "office_v0.idf"
    idf.saveas(str(idf_path))
    print(f"[c1] IDF: {idf_path}({len(idf.idfobjects['ZONE'])} zones)")

    res = runner.run_one(eplus_dir, idf_path, epw, args.out_dir)
    assert res["ok"], f"E+ 运行失败: {res.get('err_summary', '')}"
    print(f"[c1] E+ 完成({res['seconds']}s)")

    area = shoebox.conditioned_area_m2(arch, engine)
    sim = eparse.parse_monthly(args.out_dir, area, arch["hvac"]["cop_cooling"],
                               arch["hvac"]["cop_heating"])
    print("[c1] 办公 v0 月度 EUI(kWh/m²):")
    print(sim.to_string(index=False))

    obs = pd.read_csv(BENCH)
    table = monthly_nmbe_table(sim, obs, "office")
    nm = float(table.loc[table.month == 0, "nmbe_pct"].iloc[0])
    sim_peak = int(sim.loc[sim.total_kwh_m2.idxmax(), "month"])
    obs_o = obs[obs.archetype == "office"].sort_values("month")
    obs_peak = int(obs_o.loc[obs_o.eui_kwh_m2.idxmax(), "month"])
    shape_r = float(pd.Series(sim.sort_values("month").total_kwh_m2.to_numpy())
                    .corr(pd.Series(obs_o.eui_kwh_m2.to_numpy())))
    print(f"[c1] sanity(不调参):NMBE={nm:+.1f}% | 形状相关 r={shape_r:.2f} | "
          f"sim 峰值月 {sim_peak} vs 观测 {obs_peak}")

    ref = PROJECT_ROOT / "data" / "reference"
    hdr = ("# C1 办公 v0 月度 EUI + 对王 144 点 sanity(2026-07-12)\n"
           "# v0 = 管线验证值,非终值,禁止引用作结果;sanity 不调参,偏差如实记录\n"
           f"# 引擎: EnergyPlus {engine['energyplus']['version']}-"
           f"{engine['energyplus']['build_sha']} | 气象: CSWD 583620 | "
           f"分母: 全楼面面积 {area:.0f} m²(shoebox,与王 144 点建筑面积口径同基)\n"
           f"# 换算链: IdealLoads 热量 ÷ COP(冷 {arch['hvac']['cop_cooling']} / "
           f"热 {arch['hvac']['cop_heating']},v0 假定值,config hvac 节)→ 电耗;"
           "照明/设备电表直读\n"
           "# 已知偏差源: CSWD 典型气象年 vs 王矩阵近年实际运行年(近年夏偏热,"
           "供冷侧倾向偏低);敏感性归 TMYx 段\n")
    with open(ref / "c1_office_v0_monthly.csv", "w", encoding="utf-8-sig") as f:
        f.write(hdr)
        table.to_csv(f, index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5))
    months = sim.sort_values("month")["month"]
    ax.plot(months, sim.sort_values("month")["total_kwh_m2"], "o-",
            label="v0 simulated (total elec.)")
    ax.plot(months, obs_o["eui_kwh_m2"], "s--",
            label="Wang et al. 2026 office (monitored)")
    ax.set_xlabel("Month")
    ax.set_ylabel("EUI [kWh/m2/month]")
    ax.set_title(f"Office v0 sanity check (no tuning) — NMBE {nm:+.1f}%, shape r={shape_r:.2f}")
    ax.set_xticks(range(1, 13))
    ax.legend()
    ax.grid(alpha=0.3)
    figdir = PROJECT_ROOT / "outputs" / "figures" / "c_engine"
    figdir.mkdir(parents=True, exist_ok=True)
    fig.savefig(figdir / "c1_office_sanity.png", dpi=150, bbox_inches="tight")
    print(f"[c1] 图: {figdir / 'c1_office_sanity.png'};表: data/reference/c1_office_v0_monthly.csv")


if __name__ == "__main__":
    main()
