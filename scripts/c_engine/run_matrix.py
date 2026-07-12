"""块 2|52 组模拟矩阵 v0 全跑:archetype × 高度箱,并行批跑 + 断点续传。

矩阵定义:config/simulation_matrix.yaml(14 行 × 4 箱 − 4 excluded = 52)。
产出:
  outputs/simulation/matrix_v0_monthly_eui.csv(52 格 × 12 月分项;入库,
    文件头标注 v0=管线验证值禁引用)
  outputs/simulation/runs/matrix_v0/<cell>/(E+ 原生输出,gitignored;
    `_success` 哨兵 = 断点续传跳过)
运行:python scripts/c_engine/run_matrix.py [--eplus-dir DIR] [--workers N]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.simulation import parse as eparse                      # noqa: E402
from buildings_shanghai.simulation import runner, shoebox                      # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eplus-dir", default=None)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()

    engine = yaml.safe_load(open(PROJECT_ROOT / "config" / "c_engine.yaml"))
    matrix = yaml.safe_load(open(PROJECT_ROOT / "config" / "simulation_matrix.yaml"))
    eplus_dir = runner.resolve_eplus_dir(engine, args.eplus_dir)
    epw = PROJECT_ROOT / engine["weather"]["epw"]
    workers = args.workers or matrix["run"]["max_workers"]

    excluded = {(e["archetype"], e["bin"]) for e in matrix["excluded"]}
    cells = [(a, b) for a in matrix["archetypes"] for b in matrix["height_bins"]
             if (a, b) not in excluded]
    n_total = len(matrix["archetypes"]) * len(matrix["height_bins"])
    print(f"[matrix] {len(matrix['archetypes'])} archetypes × "
          f"{len(matrix['height_bins'])} bins = {n_total} − {len(excluded)} excluded "
          f"= {len(cells)} 格;workers={workers}")

    run_root = PROJECT_ROOT / "outputs" / "simulation" / "runs" / "matrix_v0"
    jobs, meta = [], {}
    for arch_name, bin_name in cells:
        arch = yaml.safe_load(open(PROJECT_ROOT / "config" / "archetypes" / f"{arch_name}.yaml"))
        n_floors = matrix["height_bins"][bin_name]["n_floors"]
        arch["geometry"]["n_floors"] = n_floors
        cell = f"{arch_name}__{bin_name}"
        run_dir = run_root / cell
        run_dir.mkdir(parents=True, exist_ok=True)
        idf_path = run_dir / f"{cell}.idf"
        if not (run_dir / "_success").exists():
            idf = shoebox.build_shoebox(arch, engine, eplus_dir / "Energy+.idd", epw)
            idf.saveas(str(idf_path))
        meta[cell] = {"archetype": arch_name, "height_bin": bin_name,
                      "n_floors": n_floors,
                      "area": shoebox.conditioned_area_m2(arch, engine),
                      "cop_c": arch["hvac"]["cop_cooling"],
                      "cop_h": arch["hvac"]["cop_heating"]}
        jobs.append({"name": cell, "idf": idf_path, "epw": epw, "run_dir": run_dir})

    t0 = time.perf_counter()
    results = runner.run_batch(jobs, eplus_dir, max_workers=workers)
    wall = time.perf_counter() - t0

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    fresh = [r for r in ok if not r.get("cached")]
    secs = [r["seconds"] for r in fresh]
    print(f"[matrix] 完成 {len(ok)}/{len(cells)}(fresh {len(fresh)}, cached "
          f"{len(ok) - len(fresh)});失败 {len(failed)};墙钟 {wall:.0f}s;"
          f"单格均值 {sum(secs) / len(secs):.1f}s / 最大 {max(secs):.1f}s" if fresh
          else f"[matrix] 全部命中缓存;失败 {len(failed)}")
    for r in failed:
        print(f"[matrix][FAILED] {r['name']}: {r['err_summary'][:200]}")

    rows = []
    for r in ok:
        m = meta[r["name"]]
        df = eparse.parse_monthly(run_root / r["name"], m["area"], m["cop_c"], m["cop_h"])
        df.insert(0, "archetype", m["archetype"])
        df.insert(1, "height_bin", m["height_bin"])
        df.insert(2, "n_floors", m["n_floors"])
        rows.append(df)
    out = pd.concat(rows, ignore_index=True)

    out_csv = PROJECT_ROOT / matrix["run"]["out_csv"]
    hdr = ("# 52 组模拟矩阵 v0 月度分项 EUI(kWh/m²/月)— 2026-07-12\n"
           "# ⚠️ v0 = 管线验证值,非终值,禁止引用作结果(参数二手转录待 owner 复核;"
           "IdealLoads×COP,无风机/水泵/热水)\n"
           f"# 引擎 EnergyPlus {engine['energyplus']['version']}-"
           f"{engine['energyplus']['build_sha']} | 气象 CSWD 583620 | "
           f"矩阵 {len(cells)} 格(excluded {len(excluded)} 见 simulation_matrix.yaml)"
           f" | 失败 {len(failed)} 格\n")
    with open(out_csv, "w", encoding="utf-8-sig") as f:
        f.write(hdr)
        out.to_csv(f, index=False)

    annual = (out.groupby(["archetype", "height_bin"])["total_kwh_m2"].sum()
              .rename("annual_kwh_m2").reset_index())
    pivot = annual.pivot(index="archetype", columns="height_bin",
                         values="annual_kwh_m2").round(1)
    print("[matrix] 年度 EUI 一览(kWh/m²/年):")
    print(pivot.to_string())
    print(f"[matrix] 产出 {out_csv}")


if __name__ == "__main__":
    main()
