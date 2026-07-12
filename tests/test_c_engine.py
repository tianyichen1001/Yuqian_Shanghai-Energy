"""C 引擎单测:NMBE 纯函数 + shoebox 生成(有 E+ IDD 时)+ 解析。"""
from pathlib import Path

import pandas as pd
import pytest

from buildings_shanghai.calibration.nmbe import nmbe_pct
from buildings_shanghai.simulation.shoebox import _hvac_avail_values, _zone_rects

EPLUS_DIR = Path("/opt/EnergyPlus-26.1.0")
HAS_EPLUS = (EPLUS_DIR / "Energy+.idd").exists()


def test_nmbe_basics():
    assert nmbe_pct([1, 2, 3], [1, 2, 3]) == 0.0
    assert nmbe_pct([11, 22, 33], [10, 20, 30]) == pytest.approx(10.0)
    assert nmbe_pct([9, 18, 27], [10, 20, 30]) == pytest.approx(-10.0)


def test_hvac_avail_values():
    v = _hvac_avail_values([7, 18])
    assert sum(v) == 11 and v[6] == 0 and v[7] == 1 and v[17] == 1 and v[18] == 0
    assert _hvac_avail_values(None) == [0.0] * 24


def test_zone_rects_partition():
    rects = _zone_rects(10.0, 10.0, 3.0)
    area = sum((x1 - x0) * (y1 - y0) for (x0, y0), (x1, y1) in rects.values())
    assert area == pytest.approx(100.0)
    assert rects["core"] == ((3.0, 3.0), (7.0, 7.0))


@pytest.mark.skipif(not HAS_EPLUS, reason="EnergyPlus 26.1.0 未安装")
@pytest.mark.parametrize("n_floors,expect_zones", [(1, 5), (2, 10), (8, 15)])
def test_shoebox_zone_count(n_floors, expect_zones, tmp_path):
    import yaml

    from buildings_shanghai.simulation.shoebox import build_shoebox
    root = Path(__file__).resolve().parents[1]
    engine = yaml.safe_load(open(root / "config" / "c_engine.yaml"))
    arch = yaml.safe_load(open(root / "config" / "archetypes" / "office.yaml"))
    arch["geometry"]["n_floors"] = n_floors
    idf = build_shoebox(arch, engine, EPLUS_DIR / "Energy+.idd",
                        root / engine["weather"]["epw"])
    zones = idf.idfobjects["ZONE"]
    assert len(zones) == expect_zones
    if n_floors >= 3:
        mid = [z for z in zones if z.Name.startswith("mid_")]
        assert all(int(z.Multiplier) == n_floors - 2 for z in mid)
    wwr = arch["geometry"]["wwr"]["south"]
    walls = {w.Name: w for w in idf.idfobjects["BUILDINGSURFACE:DETAILED"]}
    wins = idf.idfobjects["FENESTRATIONSURFACE:DETAILED"]
    assert wins, "无窗生成"
    w = wins[0]
    host = walls[w.Building_Surface_Name]

    def _area(obj):
        xs = [obj[f"Vertex_{i}_Xcoordinate"] for i in range(1, 5)]
        ys = [obj[f"Vertex_{i}_Ycoordinate"] for i in range(1, 5)]
        zs = [obj[f"Vertex_{i}_Zcoordinate"] for i in range(1, 5)]
        import math
        w_ = math.hypot(xs[2] - xs[1], ys[2] - ys[1])
        h_ = abs(zs[0] - zs[1])
        return w_ * h_
    assert _area(w) / _area(host) == pytest.approx(wwr, rel=0.01)


def test_parse_monthly_math(tmp_path):
    from buildings_shanghai.simulation.parse import J_PER_KWH, parse_monthly
    df = pd.DataFrame({
        "Date/Time": [f"2026-{m:02d}" for m in range(1, 13)],
        "InteriorLights:Electricity [J](Monthly)": [J_PER_KWH * 100] * 12,
        "InteriorEquipment:Electricity [J](Monthly)": [J_PER_KWH * 200] * 12,
        "DistrictCooling:Facility [J](Monthly)": [J_PER_KWH * 350] * 12,
        "DistrictHeatingWater:Facility [J](Monthly)": [J_PER_KWH * 250] * 12,
    })
    df.to_csv(tmp_path / "eplusout.csv", index=False)
    out = parse_monthly(tmp_path, area_m2=100.0, cop_cooling=3.5, cop_heating=2.5)
    assert out["lighting_kwh_m2"].iloc[0] == pytest.approx(1.0)
    assert out["equipment_kwh_m2"].iloc[0] == pytest.approx(2.0)
    assert out["cooling_kwh_m2"].iloc[0] == pytest.approx(1.0)   # 350/3.5/100
    assert out["heating_kwh_m2"].iloc[0] == pytest.approx(1.0)   # 250/2.5/100
    assert out["total_kwh_m2"].iloc[0] == pytest.approx(5.0)
