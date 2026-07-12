"""NMBE 计算 + 校准循环骨架(块 1 只建骨架,不做任何实际校准迭代)。

NMBE(%) = Σ(sim_i − obs_i) / (n · mean(obs)) × 100
目标(config/calibration_targets.yaml,不得为过关而放宽):
  公建 |NMBE| ≤ 10%(月度);住宅 |NMBE| ≤ 20%(年度)。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd


def nmbe_pct(sim: Sequence[float], obs: Sequence[float]) -> float:
    sim, obs = np.asarray(sim, float), np.asarray(obs, float)
    assert sim.shape == obs.shape and len(sim) > 0, "sim/obs 长度不一致或为空"
    m = obs.mean()
    assert m != 0, "obs 均值为 0,NMBE 无定义"
    return float((sim - obs).sum() / (len(obs) * m) * 100.0)


def monthly_nmbe_table(sim_df: pd.DataFrame, obs_df: pd.DataFrame,
                       archetype: str) -> pd.DataFrame:
    """单 archetype 月度对表:sim(total_kwh_m2) vs obs(eui_kwh_m2)。

    返回逐月 sim/obs/差值 + 全年 NMBE 汇总行(month=0 表示 annual)。
    """
    obs = obs_df[obs_df.archetype == archetype].sort_values("month")
    assert len(obs) == 12, f"{archetype}: 基准非 12 个月(n={len(obs)})"
    sim = sim_df.sort_values("month")
    t = pd.DataFrame({
        "archetype": archetype, "month": sim["month"].to_numpy(),
        "sim_kwh_m2": sim["total_kwh_m2"].to_numpy(),
        "obs_kwh_m2": obs["eui_kwh_m2"].to_numpy(),
    })
    t["diff_kwh_m2"] = (t.sim_kwh_m2 - t.obs_kwh_m2).round(3)
    t["ratio"] = (t.sim_kwh_m2 / t.obs_kwh_m2).round(3)
    total = pd.DataFrame([{
        "archetype": archetype, "month": 0,
        "sim_kwh_m2": round(t.sim_kwh_m2.sum(), 2),
        "obs_kwh_m2": round(t.obs_kwh_m2.sum(), 2),
        "diff_kwh_m2": round(t.sim_kwh_m2.sum() - t.obs_kwh_m2.sum(), 2),
        "ratio": round(t.sim_kwh_m2.sum() / t.obs_kwh_m2.sum(), 3),
        "nmbe_pct": round(nmbe_pct(t.sim_kwh_m2, t.obs_kwh_m2), 1),
    }])
    return pd.concat([t, total], ignore_index=True)


def calibration_loop(run_fn: Callable[[dict], pd.DataFrame], obs_df: pd.DataFrame,
                     archetype: str, param_updates: list[dict],
                     out_csv: Path | None = None) -> pd.DataFrame:
    """"改 config → 重跑 → 出 NMBE 表" 的循环脚手架。

    run_fn(param_update) -> 月度 sim DataFrame(total_kwh_m2 列)。
    param_updates 为每轮要应用的参数增量 dict(空 dict = 基线轮)。
    只负责机械循环与记录;**调参方向属设计决策,归 claude.ai**。
    """
    rows = []
    for i, upd in enumerate(param_updates):
        sim = run_fn(upd)
        nm = nmbe_pct(sim.sort_values("month")["total_kwh_m2"],
                      obs_df[obs_df.archetype == archetype].sort_values("month")["eui_kwh_m2"])
        rows.append({"iteration": i, "params": repr(upd), "nmbe_pct": round(nm, 2)})
        print(f"[calib] iter {i}: NMBE={nm:+.2f}%  params={upd}", flush=True)
    table = pd.DataFrame(rows)
    if out_csv:
        table.to_csv(out_csv, index=False)
    return table
