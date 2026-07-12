"""E+ 输出解析:eplusout.csv(readvars 月度)→ 月度分项 EUI。

分项口径(v0):
  cooling / heating = IdealLoads 供冷/供热热量 ÷ 对应 COP → 电耗
  lighting / equipment = 电表直读
  不含风机/水泵/生活热水(IdealLoads 阶段无此设备,记入 README 局限)
输出单位:kWh/m²/月;分母 = 乘数展开后的空调面积。
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

J_PER_KWH = 3.6e6

_COOL_METER = "DistrictCooling:Facility"
_HEAT_METERS = ("DistrictHeatingWater:Facility", "DistrictHeating:Facility")
_COOL_VAR = "Zone Ideal Loads Supply Air Total Cooling Energy"
_HEAT_VAR = "Zone Ideal Loads Supply Air Total Heating Energy"


def parse_monthly(run_dir: Path, area_m2: float, cop_cooling: float,
                  cop_heating: float) -> pd.DataFrame:
    """返回 12 行 DataFrame:month, cooling, heating, lighting, equipment, total(kWh/m²)。"""
    csv_path = run_dir / "eplusout.csv"
    assert csv_path.exists(), f"缺 eplusout.csv(需 energyplus -r): {run_dir}"
    df = pd.read_csv(csv_path)
    assert len(df) == 12, f"月度行数 {len(df)} != 12: {csv_path}"

    def _sum_cols(patterns: tuple[str, ...] | str) -> pd.Series:
        if isinstance(patterns, str):
            patterns = (patterns,)
        cols = [c for c in df.columns
                if any(p.lower() in c.lower() for p in patterns)]
        if not cols:
            return pd.Series([0.0] * 12)
        return df[cols].sum(axis=1)

    lights_j = _sum_cols("InteriorLights:Electricity")
    equip_j = _sum_cols("InteriorEquipment:Electricity")
    cool_j = _sum_cols(_COOL_METER)
    if float(cool_j.sum()) == 0.0:
        cool_j = _sum_cols(_COOL_VAR)
    heat_j = _sum_cols(_HEAT_METERS)
    if float(heat_j.sum()) == 0.0:
        heat_j = _sum_cols(_HEAT_VAR)

    out = pd.DataFrame({
        "month": range(1, 13),
        "cooling_kwh_m2": cool_j.to_numpy() / J_PER_KWH / cop_cooling / area_m2,
        "heating_kwh_m2": heat_j.to_numpy() / J_PER_KWH / cop_heating / area_m2,
        "lighting_kwh_m2": lights_j.to_numpy() / J_PER_KWH / area_m2,
        "equipment_kwh_m2": equip_j.to_numpy() / J_PER_KWH / area_m2,
    })
    out["total_kwh_m2"] = out[["cooling_kwh_m2", "heating_kwh_m2",
                               "lighting_kwh_m2", "equipment_kwh_m2"]].sum(axis=1)
    return out.round(3)
