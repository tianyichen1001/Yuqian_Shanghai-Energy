"""Shoebox IDF 生成器 — 纯 eppy,ASHRAE 5-zone(core + 4 perimeter)。

多层表示(config c_engine.yaml shoebox 节):
  n_floors == 1 : 单片(地面 + 屋面),5 zones
  n_floors == 2 : 底片(地面)+ 顶片(屋面),10 zones
  n_floors >= 3 : 底/中/顶三片,中间片 floor+ceiling 绝热、
                  Zone Multiplier = n_floors - 2,15 zones

所有数值(几何、层高、朝向、窗墙比、U 值、内扰、时间表)来自 config;
本模块只做几何与 IDF 对象组装,不含任何参数默认值以外的魔数。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from eppy.modeleditor import IDF

Vec = tuple[float, float]


def _rot(x: float, y: float, deg: float) -> Vec:
    r = math.radians(deg)
    return (x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r))


def _zone_rects(fx: float, fy: float, pd: float) -> dict[str, tuple[Vec, Vec]]:
    """5 分区平面:返回 zone -> (min corner, max corner)(未旋转局部坐标)。"""
    assert 2 * pd < fx and 2 * pd < fy, "perimeter_depth 过大,core 不存在"
    return {
        "core":  ((pd, pd), (fx - pd, fy - pd)),
        "south": ((0, 0), (fx, pd)),
        "north": ((0, fy - pd), (fx, fy)),
        "east":  ((fx - pd, pd), (fx, fy - pd)),
        "west":  ((0, pd), (pd, fy - pd)),
    }


# 每 zone 的四面墙:(起点, 终点) 逆时针;外墙按 zone 命名规则判定
_WALLS = {
    "south": [((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 1), (0, 1)), ((0, 1), (0, 0))],
}


def new_idf(idd_path: Path, epw_path: Path) -> IDF:
    from io import StringIO
    if IDF.getiddname() is None:
        IDF.setiddname(str(idd_path))
    idf = IDF(StringIO(""))  # 空模型
    idf.epw = str(epw_path)
    return idf


def _sched_limits(idf: IDF) -> None:
    idf.newidfobject("SCHEDULETYPELIMITS", Name="Fraction",
                     Lower_Limit_Value=0, Upper_Limit_Value=1, Numeric_Type="Continuous")
    idf.newidfobject("SCHEDULETYPELIMITS", Name="Temperature", Numeric_Type="Continuous")
    idf.newidfobject("SCHEDULETYPELIMITS", Name="AnyNumber", Numeric_Type="Continuous")


def _hourly_schedule(idf: IDF, name: str, weekday: list[float],
                     weekend: list[float], limits: str = "Fraction") -> None:
    """Schedule:Compact,工作日/周末两版逐时值(各 24)。"""
    assert len(weekday) == 24 and len(weekend) == 24, f"{name}: 需 24 小时值"

    def _block(vals: list[float]) -> list[str]:
        fields, prev, start = [], vals[0], 0
        for h in range(1, 25):
            if h == 24 or vals[h] != prev:
                fields += [f"Until: {h:02d}:00", str(prev)]
                if h < 24:
                    prev = vals[h]
        return fields

    fields = ["Through: 12/31", "For: Weekdays SummerDesignDay WinterDesignDay Holiday"]
    fields += _block(weekday)
    fields += ["For: Weekends AllOtherDays"]
    fields += _block(weekend)
    obj = idf.newidfobject("SCHEDULE:COMPACT", Name=name, Schedule_Type_Limits_Name=limits)
    for i, f in enumerate(fields, 1):
        setattr(obj, f"Field_{i}", f)


def _hvac_avail_values(hours: list[int] | None) -> list[float]:
    if hours is None:
        return [0.0] * 24
    lo, hi = hours
    return [1.0 if lo <= h < hi else 0.0 for h in range(24)]


def _constructions(idf: IDF, arch: dict, films: dict, mass: dict) -> None:
    """外墙/屋面 = NoMass 保温层 + 内衬混凝土质量层(数值稳定性)。

    GB 的 K 含内外膜阻:R_nomass = 1/K − r_si − r_se − R_mass。
    """
    r_mass = mass["thickness_m"] / mass["conductivity_w_mk"]
    idf.newidfobject("MATERIAL", Name="MassLayer", Roughness="MediumRough",
                     Thickness=mass["thickness_m"],
                     Conductivity=mass["conductivity_w_mk"],
                     Density=mass["density_kg_m3"],
                     Specific_Heat=mass["specific_heat_j_kgk"],
                     Thermal_Absorptance=0.9, Solar_Absorptance=0.7,
                     Visible_Absorptance=0.7)
    wall_r = 1.0 / arch["envelope"]["wall_u"] - films["wall_r_si"] - films["wall_r_se"] - r_mass
    roof_r = 1.0 / arch["envelope"]["roof_u"] - films["roof_r_si"] - films["roof_r_se"] - r_mass
    slab_r = arch["envelope"]["ground_slab_r"] - r_mass
    assert wall_r > 0 and roof_r > 0 and slab_r > 0, "U/R 与质量层不相容"
    for name, r in [("WallLayer", wall_r), ("RoofLayer", roof_r), ("SlabLayer", slab_r)]:
        idf.newidfobject("MATERIAL:NOMASS", Name=name, Roughness="MediumRough",
                         Thermal_Resistance=r, Thermal_Absorptance=0.9,
                         Solar_Absorptance=0.7, Visible_Absorptance=0.7)
    idf.newidfobject("WINDOWMATERIAL:SIMPLEGLAZINGSYSTEM", Name="Glz",
                     UFactor=arch["envelope"]["window_u"],
                     Solar_Heat_Gain_Coefficient=arch["envelope"]["window_shgc"])
    for cname, outer in [("ExtWall", "WallLayer"), ("Roof", "RoofLayer"),
                         ("GroundSlab", "SlabLayer")]:
        idf.newidfobject("CONSTRUCTION", Name=cname, Outside_Layer=outer,
                         Layer_2="MassLayer")
    idf.newidfobject("CONSTRUCTION", Name="AdiabaticSurf", Outside_Layer="MassLayer")
    idf.newidfobject("CONSTRUCTION", Name="Window", Outside_Layer="Glz")


def _add_zone_slab(idf: IDF, slab: str, z0: float, zh: float, rects: dict,
                   fx: float, fy: float, orient: float, wwr: dict,
                   floor_bc: str, ceil_bc: str, multiplier: int) -> list[str]:
    """生成一片楼层的 5 个 zone;返回 zone 名列表。

    floor_bc/ceil_bc ∈ {ground, adiabatic, roof}:
      floor: ground→Ground/GroundSlab, adiabatic→Adiabatic/AdiabaticSurf
      ceil : roof→Outdoors/Roof,       adiabatic→Adiabatic/AdiabaticSurf
    """
    names = []
    for zkey, ((x0, y0), (x1, y1)) in rects.items():
        zn = f"{slab}_{zkey}"
        names.append(zn)
        idf.newidfobject("ZONE", Name=zn, Multiplier=multiplier)
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        gc = [_rot(x, y, orient) for x, y in corners]

        floor_con = "GroundSlab" if floor_bc == "ground" else "AdiabaticSurf"
        floor_obc = "Ground" if floor_bc == "ground" else "Adiabatic"
        srf = idf.newidfobject("BUILDINGSURFACE:DETAILED", Name=f"{zn}_floor",
                               Surface_Type="Floor", Construction_Name=floor_con,
                               Zone_Name=zn, Outside_Boundary_Condition=floor_obc,
                               Sun_Exposure="NoSun", Wind_Exposure="NoWind")
        for i, (x, y) in enumerate(reversed(gc), 1):   # floor 顺时针(法向下)
            srf[f"Vertex_{i}_Xcoordinate"], srf[f"Vertex_{i}_Ycoordinate"], \
                srf[f"Vertex_{i}_Zcoordinate"] = round(x, 4), round(y, 4), round(z0, 4)

        ceil_con = "Roof" if ceil_bc == "roof" else "AdiabaticSurf"
        ceil_obc = "Outdoors" if ceil_bc == "roof" else "Adiabatic"
        srf = idf.newidfobject("BUILDINGSURFACE:DETAILED", Name=f"{zn}_ceil",
                               Surface_Type="Roof" if ceil_bc == "roof" else "Ceiling",
                               Construction_Name=ceil_con, Zone_Name=zn,
                               Outside_Boundary_Condition=ceil_obc,
                               Sun_Exposure="SunExposed" if ceil_bc == "roof" else "NoSun",
                               Wind_Exposure="WindExposed" if ceil_bc == "roof" else "NoWind")
        for i, (x, y) in enumerate(gc, 1):             # ceiling 逆时针(法向上)
            srf[f"Vertex_{i}_Xcoordinate"], srf[f"Vertex_{i}_Ycoordinate"], \
                srf[f"Vertex_{i}_Zcoordinate"] = round(x, 4), round(y, 4), round(z0 + zh, 4)

        # 四面墙:局部边 -> 判定外墙(贴 footprint 边界)或内墙(Adiabatic)
        edges = [((x0, y0), (x1, y0), "south"), ((x1, y0), (x1, y1), "east"),
                 ((x1, y1), (x0, y1), "north"), ((x0, y1), (x0, y0), "west")]
        for (ax, ay), (bx, by), facing in edges:
            on_boundary = ((facing == "south" and ay == 0) or (facing == "north" and ay == fy)
                           or (facing == "west" and ax == 0) or (facing == "east" and ax == fx))
            ext = on_boundary
            wname = f"{zn}_wall_{facing}"
            srf = idf.newidfobject(
                "BUILDINGSURFACE:DETAILED", Name=wname, Surface_Type="Wall",
                Construction_Name="ExtWall" if ext else "AdiabaticSurf", Zone_Name=zn,
                Outside_Boundary_Condition="Outdoors" if ext else "Adiabatic",
                Sun_Exposure="SunExposed" if ext else "NoSun",
                Wind_Exposure="WindExposed" if ext else "NoWind")
            (gax, gay), (gbx, gby) = _rot(ax, ay, orient), _rot(bx, by, orient)
            verts = [(gax, gay, z0 + zh), (gax, gay, z0), (gbx, gby, z0), (gbx, gby, z0 + zh)]
            for i, (x, y, z) in enumerate(verts, 1):
                srf[f"Vertex_{i}_Xcoordinate"], srf[f"Vertex_{i}_Ycoordinate"], \
                    srf[f"Vertex_{i}_Zcoordinate"] = round(x, 4), round(y, 4), round(z, 4)

            if ext:
                ratio = wwr[facing]
                if ratio and ratio > 0:
                    wlen = math.hypot(bx - ax, by - ay)
                    s = math.sqrt(ratio)                # 居中等比内缩
                    ww, wh = wlen * s, zh * s
                    m_l, m_z = (wlen - ww) / 2, (zh - wh) / 2
                    ux, uy = (bx - ax) / wlen, (by - ay) / wlen
                    p1 = (ax + ux * m_l, ay + uy * m_l)
                    p2 = (ax + ux * (m_l + ww), ay + uy * (m_l + ww))
                    (g1x, g1y), (g2x, g2y) = _rot(*p1, orient), _rot(*p2, orient)
                    win = idf.newidfobject("FENESTRATIONSURFACE:DETAILED",
                                           Name=f"{wname}_win", Surface_Type="Window",
                                           Construction_Name="Window",
                                           Building_Surface_Name=wname)
                    wverts = [(g1x, g1y, z0 + m_z + wh), (g1x, g1y, z0 + m_z),
                              (g2x, g2y, z0 + m_z), (g2x, g2y, z0 + m_z + wh)]
                    for i, (x, y, z) in enumerate(wverts, 1):
                        win[f"Vertex_{i}_Xcoordinate"], win[f"Vertex_{i}_Ycoordinate"], \
                            win[f"Vertex_{i}_Zcoordinate"] = round(x, 4), round(y, 4), round(z, 4)
    return names


def _zone_services(idf: IDF, zones: list[str], arch: dict) -> None:
    il, hv = arch["internal_loads"], arch["hvac"]
    idf.newidfobject("DESIGNSPECIFICATION:OUTDOORAIR", Name="DSOA",
                     Outdoor_Air_Method="Flow/Person",
                     Outdoor_Air_Flow_per_Person=il["fresh_air_m3h_per_person"] / 3600.0)
    for zn in zones:
        idf.newidfobject("PEOPLE", Name=f"{zn}_people", Zone_or_ZoneList_or_Space_or_SpaceList_Name=zn,
                         Number_of_People_Schedule_Name="OccSched",
                         Number_of_People_Calculation_Method="Area/Person",
                         Floor_Area_per_Person=il["occupancy_m2_per_person"],
                         Fraction_Radiant=0.3, Activity_Level_Schedule_Name="ActivitySched")
        idf.newidfobject("LIGHTS", Name=f"{zn}_lights", Zone_or_ZoneList_or_Space_or_SpaceList_Name=zn,
                         Schedule_Name="LightSched",
                         Design_Level_Calculation_Method="Watts/Area",
                         Watts_per_Floor_Area=il["lighting_w_per_m2"],
                         Fraction_Radiant=0.42, Fraction_Visible=0.18)
        idf.newidfobject("ELECTRICEQUIPMENT", Name=f"{zn}_equip",
                         Zone_or_ZoneList_or_Space_or_SpaceList_Name=zn,
                         Schedule_Name="EquipSched",
                         Design_Level_Calculation_Method="Watts/Area",
                         Watts_per_Floor_Area=il["equipment_w_per_m2"],
                         Fraction_Radiant=0.3)
        idf.newidfobject("ZONEINFILTRATION:DESIGNFLOWRATE", Name=f"{zn}_inf",
                         Zone_or_ZoneList_or_Space_or_SpaceList_Name=zn,
                         Schedule_Name="AlwaysOn",
                         Design_Flow_Rate_Calculation_Method="AirChanges/Hour",
                         Air_Changes_per_Hour=hv["infiltration_ach"])
        idf.newidfobject("ZONECONTROL:THERMOSTAT", Name=f"{zn}_tstat", Zone_or_ZoneList_Name=zn,
                         Control_Type_Schedule_Name="TstatType",
                         Control_1_Object_Type="ThermostatSetpoint:DualSetpoint",
                         Control_1_Name="DualSP")
        idf.newidfobject("ZONEHVAC:IDEALLOADSAIRSYSTEM", Name=f"{zn}_ideal",
                         Availability_Schedule_Name="HvacAvail",
                         Zone_Supply_Air_Node_Name=f"{zn}_supply",
                         Design_Specification_Outdoor_Air_Object_Name="DSOA",
                         Outdoor_Air_Economizer_Type="NoEconomizer",
                         Heat_Recovery_Type="None")
        eq = idf.newidfobject("ZONEHVAC:EQUIPMENTLIST", Name=f"{zn}_eqlist",
                              Zone_Equipment_1_Object_Type="ZoneHVAC:IdealLoadsAirSystem",
                              Zone_Equipment_1_Name=f"{zn}_ideal",
                              Zone_Equipment_1_Cooling_Sequence=1,
                              Zone_Equipment_1_Heating_or_NoLoad_Sequence=1)
        idf.newidfobject("ZONEHVAC:EQUIPMENTCONNECTIONS", Zone_Name=zn,
                         Zone_Conditioning_Equipment_List_Name=f"{zn}_eqlist",
                         Zone_Air_Inlet_Node_or_NodeList_Name=f"{zn}_supply",
                         Zone_Air_Node_Name=f"{zn}_air",
                         Zone_Return_Air_Node_or_NodeList_Name=f"{zn}_return")


def build_shoebox(arch: dict[str, Any], engine: dict[str, Any],
                  idd_path: Path, epw_path: Path) -> IDF:
    """由 archetype dict + engine dict 组装完整可跑 IDF。"""
    sb = dict(engine["shoebox"])
    sb.update(arch.get("geometry", {}))
    n_floors = int(sb.get("n_floors", 1))
    fx, fy = float(sb["footprint_x_m"]), float(sb["footprint_y_m"])
    zh, pd = float(sb["floor_height_m"]), float(sb["perimeter_depth_m"])
    orient = float(sb.get("orientation_deg", 0.0))
    wwr = sb["wwr"]

    idf = new_idf(idd_path, epw_path)
    idf.newidfobject("VERSION", Version_Identifier=engine["energyplus"]["version"].rsplit(".", 1)[0])
    idf.newidfobject("BUILDING", Name=f"shoebox_{arch['archetype']}",
                     North_Axis=0.0, Terrain="City",
                     Solar_Distribution="FullExterior")
    idf.newidfobject("GLOBALGEOMETRYRULES", Starting_Vertex_Position="UpperLeftCorner",
                     Vertex_Entry_Direction="Counterclockwise",
                     Coordinate_System="World")
    idf.newidfobject("TIMESTEP", Number_of_Timesteps_per_Hour=engine["simulation"]["timestep_per_hour"])
    rp = engine["simulation"]["run_period"]
    idf.newidfobject("RUNPERIOD", Name="RunYear", Begin_Month=rp["begin_month"],
                     Begin_Day_of_Month=rp["begin_day"], End_Month=rp["end_month"],
                     End_Day_of_Month=rp["end_day"])
    idf.newidfobject("SIMULATIONCONTROL", Do_Zone_Sizing_Calculation="No",
                     Do_System_Sizing_Calculation="No", Do_Plant_Sizing_Calculation="No",
                     Run_Simulation_for_Sizing_Periods="No",
                     Run_Simulation_for_Weather_File_Run_Periods="Yes")

    _sched_limits(idf)
    sch = arch["schedules"]
    _hourly_schedule(idf, "OccSched", sch["weekday"]["occupancy"], sch["weekend"]["occupancy"])
    _hourly_schedule(idf, "LightSched", sch["weekday"]["lighting"], sch["weekend"]["lighting"])
    _hourly_schedule(idf, "EquipSched", sch["weekday"]["equipment"], sch["weekend"]["equipment"])
    _hourly_schedule(idf, "HvacAvail", _hvac_avail_values(sch["weekday"]["hvac_hours"]),
                     _hvac_avail_values(sch["weekend"]["hvac_hours"]))
    for name, val in [("AlwaysOn", 1.0), ("ActivitySched", 120.0),
                      ("TstatType", 4.0)]:
        obj = idf.newidfobject("SCHEDULE:COMPACT", Name=name,
                               Schedule_Type_Limits_Name="AnyNumber")
        obj.Field_1, obj.Field_2, obj.Field_3 = "Through: 12/31", "For: AllDays", f"Until: 24:00"
        obj.Field_4 = str(val)
    hv = arch["hvac"]
    # 设定点:运行时段用设计温度,非运行时段用保护带(IdealLoads 不可用时不动作)
    avail_wd = _hvac_avail_values(sch["weekday"]["hvac_hours"])
    avail_we = _hvac_avail_values(sch["weekend"]["hvac_hours"])
    heat_wd = [hv["heating_setpoint_c"] if a else hv["setback_heating_c"] for a in avail_wd]
    heat_we = [hv["heating_setpoint_c"] if a else hv["setback_heating_c"] for a in avail_we]
    cool_wd = [hv["cooling_setpoint_c"] if a else hv["setback_cooling_c"] for a in avail_wd]
    cool_we = [hv["cooling_setpoint_c"] if a else hv["setback_cooling_c"] for a in avail_we]
    _hourly_schedule(idf, "HeatSP", heat_wd, heat_we, limits="Temperature")
    _hourly_schedule(idf, "CoolSP", cool_wd, cool_we, limits="Temperature")
    idf.newidfobject("THERMOSTATSETPOINT:DUALSETPOINT", Name="DualSP",
                     Heating_Setpoint_Temperature_Schedule_Name="HeatSP",
                     Cooling_Setpoint_Temperature_Schedule_Name="CoolSP")

    _constructions(idf, arch, engine["envelope_films"], engine["thermal_mass"])

    rects = _zone_rects(fx, fy, pd)
    zones: list[str] = []
    if n_floors == 1:
        zones += _add_zone_slab(idf, "f1", 0.0, zh, rects, fx, fy, orient, wwr,
                                floor_bc="ground", ceil_bc="roof", multiplier=1)
    elif n_floors == 2:
        zones += _add_zone_slab(idf, "bot", 0.0, zh, rects, fx, fy, orient, wwr,
                                floor_bc="ground", ceil_bc="adiabatic", multiplier=1)
        zones += _add_zone_slab(idf, "top", zh, zh, rects, fx, fy, orient, wwr,
                                floor_bc="adiabatic", ceil_bc="roof", multiplier=1)
    else:
        zones += _add_zone_slab(idf, "bot", 0.0, zh, rects, fx, fy, orient, wwr,
                                floor_bc="ground", ceil_bc="adiabatic", multiplier=1)
        zones += _add_zone_slab(idf, "mid", zh, zh, rects, fx, fy, orient, wwr,
                                floor_bc="adiabatic", ceil_bc="adiabatic",
                                multiplier=n_floors - 2)
        zones += _add_zone_slab(idf, "top", 2 * zh, zh, rects, fx, fy, orient, wwr,
                                floor_bc="adiabatic", ceil_bc="roof", multiplier=1)

    _zone_services(idf, zones, arch)

    for meter in ["InteriorLights:Electricity", "InteriorEquipment:Electricity",
                  "DistrictCooling:Facility", "DistrictHeatingWater:Facility"]:
        idf.newidfobject("OUTPUT:METER", Key_Name=meter, Reporting_Frequency="Monthly")
    idf.newidfobject("OUTPUT:VARIABLE", Key_Value="*",
                     Variable_Name="Zone Ideal Loads Supply Air Total Cooling Energy",
                     Reporting_Frequency="Monthly")
    idf.newidfobject("OUTPUT:VARIABLE", Key_Value="*",
                     Variable_Name="Zone Ideal Loads Supply Air Total Heating Energy",
                     Reporting_Frequency="Monthly")
    idf.newidfobject("OUTPUTCONTROL:TABLE:STYLE", Column_Separator="Comma")
    idf.newidfobject("OUTPUT:TABLE:SUMMARYREPORTS", Report_1_Name="AllSummary")
    return idf


def conditioned_area_m2(arch: dict, engine: dict) -> float:
    """乘数展开后的空调面积(EUI 分母)。"""
    sb = dict(engine["shoebox"])
    sb.update(arch.get("geometry", {}))
    return float(sb["footprint_x_m"]) * float(sb["footprint_y_m"]) * int(sb.get("n_floors", 1))
