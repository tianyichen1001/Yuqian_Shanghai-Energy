"""Unit tests for the validation-set curation pipeline.

The real shapefile lives outside the repo (per SOP), so these tests
build synthetic in-memory GeoDataFrames sized to exercise every branch
without touching disk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


geopandas = pytest.importorskip("geopandas")
openpyxl = pytest.importorskip("openpyxl")
shapely = pytest.importorskip("shapely")

from shapely.geometry import Polygon

from buildings_shanghai.validation import baidu
from buildings_shanghai.validation.dedup import (
    AREA_REL_TOL,
    DISTANCE_TOL_M,
    HEIGHT_ABS_TOL_M,
    KEEP_PER_CLUSTER,
    dedup_same_building,
)
from buildings_shanghai.validation.kml import BlindTestViolationError as KMLBlindError
from buildings_shanghai.validation.kml import build_kml
from buildings_shanghai.validation.sampling import (
    HALFWIDTH_STEP_M,
    MIN_FOOTPRINT_AREA_M2,
    NotEnoughCandidatesError,
    sample_window,
)
from buildings_shanghai.validation.windows import WINDOWS, format_id, id_range
from buildings_shanghai.validation.workbook import (
    BUILDING_TYPE_CODES,
    BlindTestViolationError as XLSXBlindError,
    build_workbook,
)


# ---------------------------------------------------------------------------
# windows.py
# ---------------------------------------------------------------------------


def test_windows_total_quota_is_200() -> None:
    """Five windows × 40 = 200. If either changes the paper's frame breaks."""
    assert sum(w.quota for w in WINDOWS) == 200
    assert len(WINDOWS) == 5


def test_window_id_ranges_are_contiguous() -> None:
    """V001–V200 must be contiguous, no gaps or overlaps."""
    expected_lo = 1
    for w in WINDOWS:
        lo, hi = id_range(w.key)
        assert lo == expected_lo
        assert hi - lo + 1 == w.quota
        expected_lo = hi + 1
    assert expected_lo == 201


@pytest.mark.parametrize(
    "n,expected",
    [(1, "V001"), (40, "V040"), (41, "V041"), (200, "V200")],
)
def test_format_id(n: int, expected: str) -> None:
    assert format_id(n) == expected


@pytest.mark.parametrize("n", [0, -1, 201, 500])
def test_format_id_rejects_out_of_range(n: int) -> None:
    with pytest.raises(ValueError):
        format_id(n)


# ---------------------------------------------------------------------------
# baidu.py — coord conversions
# ---------------------------------------------------------------------------


def test_wgs84_to_bd09_beijing_reference() -> None:
    """Regression against the canonical Beijing published example.

    WGS84 (39.916527, 116.397128) → GCJ (~39.9178, 116.4034)
                                   → BD09 (~39.9235, 116.4099).
    The 1e-3 deg (~110 m) tolerance covers the small differences between
    published polynomial variants; well below Baidu's rendering tolerance.
    """
    g_lat, g_lon = baidu.wgs84_to_gcj02(39.916527, 116.397128)
    assert g_lat == pytest.approx(39.91784, abs=1e-3)
    assert g_lon == pytest.approx(116.40342, abs=1e-3)

    b_lat, b_lon = baidu.wgs84_to_bd09(39.916527, 116.397128)
    assert b_lat == pytest.approx(39.92347, abs=1e-3)
    assert b_lon == pytest.approx(116.40990, abs=1e-3)


def test_wgs84_to_bd09_shifts_toward_ne_in_china() -> None:
    """Sanity: for Shanghai coords, BD09 sits NE of WGS84 by ~0.003–0.012 deg."""
    bd_lat, bd_lon = baidu.wgs84_to_bd09(31.2337, 121.5054)
    assert 31.2337 < bd_lat < 31.24  # north shift
    assert 121.5054 < bd_lon < 121.52  # east shift


def test_wgs84_to_bd09_out_of_china_passes_through() -> None:
    """Points outside China are treated as WGS84 == GCJ-02 == BD09-shifted-only."""
    bd_lat, bd_lon = baidu.wgs84_to_bd09(40.7128, -74.0060)  # NYC
    # Only the BD09 rotation is applied (no GCJ shift), so the output must
    # still be within a few metres of the input.
    assert abs(bd_lat - 40.7128) < 0.02
    assert abs(bd_lon - -74.0060) < 0.02


def test_marker_link_wgs84_default() -> None:
    url = baidu.marker_link(31.2337, 121.5054, title="V001")
    assert url.startswith("https://api.map.baidu.com/marker?")
    assert "coord_type=wgs84" in url
    assert "location=31.2337000%2C121.5054000" in url
    assert "title=V001" in url
    assert "src=ubem.validation" in url


def test_marker_link_bd09_converts_client_side() -> None:
    url = baidu.marker_link(31.2337, 121.5054, title="V001", coord_type="bd09ll")
    assert "coord_type=bd09ll" in url
    # Coordinate must have been shifted from the input.
    assert "location=31.2337000%2C121.5054000" not in url


# ---------------------------------------------------------------------------
# dedup.py — same-building clustering
# ---------------------------------------------------------------------------


def _dedup_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal input frame with the columns dedup expects."""
    return pd.DataFrame(rows)


def test_dedup_isolated_buildings_survive() -> None:
    """Buildings that are far apart never cluster."""
    df = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0, "height": 30.0, "x_m": 400.0, "y_m": 0.0},  # >250 m
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 400.0},
        ]
    )
    result = dedup_same_building(df)
    assert len(result.kept) == 3
    assert len(result.dropped) == 0
    assert set(result.cluster_sizes.values()) == {1}


def test_dedup_keeps_at_most_three_per_cluster() -> None:
    """Five identical towers 100 m apart on one plot → keep the first 3."""
    df = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": float(i * 100), "y_m": 0.0}
            for i in range(5)
        ]
    )
    result = dedup_same_building(df)
    assert len(result.kept) == KEEP_PER_CLUSTER
    assert len(result.dropped) == 2
    assert (result.kept["cluster_size"] == 5).all()


def test_dedup_area_threshold() -> None:
    """A 6% area gap breaks the cluster; a 3% gap keeps them together."""
    df_break = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0 * 1.061, "height": 30.0, "x_m": 50.0, "y_m": 0.0},
        ]
    )
    assert len(dedup_same_building(df_break).kept) == 2

    df_join = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0 * 1.03, "height": 30.0, "x_m": 50.0, "y_m": 0.0},
        ]
    )
    result = dedup_same_building(df_join)
    assert len(result.kept) == 2  # cluster of 2, both kept (≤3)
    assert (result.kept["cluster_size"] == 2).all()


def test_dedup_height_threshold() -> None:
    """A 0.6 m height gap breaks the cluster; a 0.4 m gap keeps it."""
    df_break = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0, "height": 30.6, "x_m": 50.0, "y_m": 0.0},
        ]
    )
    assert len(dedup_same_building(df_break).kept) == 2  # separate clusters
    assert set(dedup_same_building(df_break).cluster_sizes.values()) == {1}

    df_join = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0, "height": 30.4, "x_m": 50.0, "y_m": 0.0},
        ]
    )
    assert (dedup_same_building(df_join).kept["cluster_size"] == 2).all()


def test_dedup_distance_threshold() -> None:
    """250 m apart clusters; 300 m apart doesn't."""
    df_break = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0, "height": 30.0, "x_m": 300.0, "y_m": 0.0},
        ]
    )
    assert len(dedup_same_building(df_break).kept) == 2
    assert set(dedup_same_building(df_break).cluster_sizes.values()) == {1}

    df_join = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0, "height": 30.0, "x_m": 240.0, "y_m": 0.0},
        ]
    )
    assert (dedup_same_building(df_join).kept["cluster_size"] == 2).all()


def test_dedup_transitivity_via_union_find() -> None:
    """A—B match, B—C match, A—C do NOT match → still one cluster."""
    df = _dedup_frame(
        [
            {"Area": 500.0, "height": 30.0, "x_m": 0.0, "y_m": 0.0},
            {"Area": 500.0, "height": 30.0, "x_m": 240.0, "y_m": 0.0},   # 240 from A
            {"Area": 500.0, "height": 30.0, "x_m": 480.0, "y_m": 0.0},   # 240 from B, 480 from A
        ]
    )
    result = dedup_same_building(df)
    # All three in one cluster of size 3.
    assert len(result.kept) == 3
    assert (result.kept["cluster_size"] == 3).all()


def test_dedup_empty_frame() -> None:
    df = _dedup_frame([])
    df["Area"] = pd.Series(dtype=float)
    df["height"] = pd.Series(dtype=float)
    df["x_m"] = pd.Series(dtype=float)
    df["y_m"] = pd.Series(dtype=float)
    result = dedup_same_building(df)
    assert len(result.kept) == 0
    assert len(result.dropped) == 0


# ---------------------------------------------------------------------------
# sampling.py — window scan
# ---------------------------------------------------------------------------


def _synthetic_metric_gdf(n: int = 200, *, seed: int = 1) -> "geopandas.GeoDataFrame":
    """Grid of ``n`` synthetic buildings inside a 3-km square, all distinct.

    Areas fan across [80, 400] m² so we can verify the 100-m² floor kicks in.
    """
    rng = np.random.default_rng(seed)
    xs = rng.uniform(-1500, 1500, size=n)
    ys = rng.uniform(-1500, 1500, size=n)
    areas = np.linspace(80, 400, n)
    heights = np.linspace(6, 200, n)  # unique heights → no dedup collisions
    geoms = [Polygon([(x - 5, y - 5), (x + 5, y - 5), (x + 5, y + 5), (x - 5, y + 5)]) for x, y in zip(xs, ys)]
    return geopandas.GeoDataFrame(
        {
            "Area": areas,
            "height": heights,
            "x_m": xs,
            "y_m": ys,
            "geometry": geoms,
        },
        crs="EPSG:4547",
    )


def test_sample_window_respects_area_floor() -> None:
    gdf = _synthetic_metric_gdf(n=200)
    small_window = WINDOWS[0]._replace() if hasattr(WINDOWS[0], "_replace") else WINDOWS[0]
    from buildings_shanghai.validation.windows import Window
    tiny_quota_window = Window("tiny", "tiny", 0.0, 0.0, 3000, quota=5)
    rng = np.random.default_rng(42)
    res = sample_window(gdf, tiny_quota_window, centre_x=0, centre_y=0, rng=rng)
    assert (res.picked["Area"] >= MIN_FOOTPRINT_AREA_M2).all()


def test_sample_window_deterministic_with_seed() -> None:
    from buildings_shanghai.validation.windows import Window
    gdf = _synthetic_metric_gdf(n=200)
    w = Window("t", "t", 0.0, 0.0, 3000, quota=20)

    r1 = sample_window(gdf, w, centre_x=0, centre_y=0, rng=np.random.default_rng(42))
    r2 = sample_window(gdf, w, centre_x=0, centre_y=0, rng=np.random.default_rng(42))
    assert list(r1.picked["Area"]) == list(r2.picked["Area"])


def test_sample_window_expands_halfwidth_when_short() -> None:
    from buildings_shanghai.validation.windows import Window
    # Put 40 candidates outside the initial halfwidth so we force an expansion.
    gdf = _synthetic_metric_gdf(n=200)
    # Move everyone to x=2500 so nothing lands inside a 500-m box.
    gdf["x_m"] = 2500.0
    gdf["y_m"] = 0.0
    # Rebuild geometry to match new coords (simple squares).
    gdf["geometry"] = [
        Polygon([(2495, -5), (2505, -5), (2505, 5), (2495, 5)])
        for _ in range(len(gdf))
    ]
    # Give them all a distinct height so nothing clusters together.
    gdf["height"] = np.linspace(6, 200, len(gdf))
    gdf["Area"] = np.linspace(150, 400, len(gdf))

    w = Window("t", "t", 0.0, 0.0, 500, quota=10)  # halfwidth 500 → too small
    rng = np.random.default_rng(42)
    res = sample_window(gdf, w, centre_x=0, centre_y=0, rng=rng)
    # 500 + 300*k must have expanded until it hit x=2500. Confirm it grew.
    assert res.final_halfwidth_m > 500
    assert res.final_halfwidth_m == pytest.approx(2600, abs=HALFWIDTH_STEP_M)


def test_sample_window_stops_at_max_halfwidth() -> None:
    from buildings_shanghai.validation.windows import Window
    # Not enough candidates anywhere → sampler must raise, not silently truncate.
    gdf = _synthetic_metric_gdf(n=5)
    w = Window("t", "t", 0.0, 0.0, 500, quota=40)
    rng = np.random.default_rng(42)
    with pytest.raises(NotEnoughCandidatesError):
        sample_window(gdf, w, centre_x=0, centre_y=0, rng=rng, max_halfwidth_m=3000)


# ---------------------------------------------------------------------------
# workbook.py — xlsx builder & blind-test guard
# ---------------------------------------------------------------------------


def _mock_annotator_frame(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "编号": [format_id(i + 1) for i in range(n)],
            "百度直达链接": [f"https://api.map.baidu.com/marker?location=31.2,121.5&title=V{i}" for i in range(n)],
            "片区": ["陆家嘴"] * n,
            "抽样方式": ["窗口扫描"] * n,
            "备注": [""] * n,
            "lat_wgs84": [31.23 + i * 0.001 for i in range(n)],
            "lon_wgs84": [121.5 + i * 0.001 for i in range(n)],
        }
    )


def test_build_workbook_writes_xlsx(tmp_path) -> None:
    df = _mock_annotator_frame(n=5)
    out = tmp_path / "annotation_workbook.xlsx"
    build_workbook(df, out)
    assert out.is_file()
    wb = openpyxl.load_workbook(out)
    assert "标注工作表" in wb.sheetnames
    assert "类型代码对照" in wb.sheetnames

    # Header row is where we placed it.
    main = wb["标注工作表"]
    assert main.cell(row=1, column=1).value == "编号"
    assert main.cell(row=2, column=1).value == "V001"
    # Baidu link renders as a hyperlink cell.
    link_cell = main.cell(row=2, column=2)
    assert link_cell.hyperlink is not None
    assert link_cell.hyperlink.target == df.loc[0, "百度直达链接"]
    # Blank columns for the annotator.
    assert main.cell(row=2, column=5).value is None  # 建筑类型
    assert main.cell(row=2, column=8).value is None  # 总层数

    # Data-validation dropdowns present for the four categorical columns.
    dvs = main.data_validations.dataValidation
    assert len(dvs) == 4


def test_build_workbook_rejects_height_leak(tmp_path) -> None:
    df = _mock_annotator_frame(n=1)
    df["height"] = 42.0
    with pytest.raises(XLSXBlindError):
        build_workbook(df, tmp_path / "leak.xlsx")


def test_building_type_codes_matches_paper() -> None:
    """14 codes, no duplicates, exactly the paper's canonical list."""
    codes = [c for c, _ in BUILDING_TYPE_CODES]
    assert len(codes) == 14
    assert len(set(codes)) == 14
    assert "mixed_use" in codes
    assert "unclear" in codes
    assert "residential" in codes


# ---------------------------------------------------------------------------
# kml.py
# ---------------------------------------------------------------------------


def test_build_kml_writes_folders_per_district(tmp_path) -> None:
    gdf = geopandas.GeoDataFrame(
        {
            "编号": ["V001", "V002", "V041"],
            "片区": ["陆家嘴", "陆家嘴", "徐家汇"],
            "百度直达链接": ["https://x", "https://y", "https://z"],
            "geometry": [
                Polygon([(121.5, 31.23), (121.501, 31.23), (121.501, 31.231), (121.5, 31.231)]),
                Polygon([(121.502, 31.23), (121.503, 31.23), (121.503, 31.231), (121.502, 31.231)]),
                Polygon([(121.44, 31.19), (121.441, 31.19), (121.441, 31.191), (121.44, 31.191)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )
    out = tmp_path / "validation_pins.kml"
    build_kml(gdf, out)
    text = out.read_text(encoding="utf-8")

    # Two <Folder> blocks, one per district.
    assert text.count("<Folder>") == 2
    assert text.count("</Folder>") == 2
    assert "陆家嘴" in text
    assert "徐家汇" in text
    assert "<name>V001</name>" in text
    assert "<name>V041</name>" in text
    # Baidu URL is embedded via CDATA (not raw).
    assert "<![CDATA[<a href=" in text


def test_build_kml_rejects_height_leak(tmp_path) -> None:
    gdf = geopandas.GeoDataFrame(
        {
            "编号": ["V001"],
            "片区": ["陆家嘴"],
            "百度直达链接": ["https://x"],
            "height": [42.0],
            "geometry": [
                Polygon([(121.5, 31.23), (121.501, 31.23), (121.501, 31.231), (121.5, 31.231)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )
    with pytest.raises(KMLBlindError):
        build_kml(gdf, tmp_path / "leak.kml")
