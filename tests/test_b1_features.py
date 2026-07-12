"""B1 特征工程单元测试(合成几何,不依赖数据文件)。"""
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon

from buildings_shanghai.ml import features as F

EPSG = 32651  # 测试几何直接以米制坐标构造,to_crs 为无操作


def _gdf(geoms):
    g = gpd.GeoDataFrame({"geometry": geoms}, crs=EPSG)
    g["area_m2"] = g.geometry.area
    return g


def test_shape_features_square():
    g = _gdf([Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])])
    F.shape_features(g, EPSG)
    assert g["perimeter_m"].iloc[0] == pytest.approx(40.0)
    assert g["compactness"].iloc[0] == pytest.approx(np.pi / 4, rel=1e-6)
    assert g["aspect_ratio"].iloc[0] == pytest.approx(1.0, rel=1e-6)
    assert g["convexity"].iloc[0] == pytest.approx(1.0, rel=1e-6)


def test_shape_features_rectangle_and_lshape():
    rect = Polygon([(0, 0), (20, 0), (20, 5), (0, 5)])
    lshape = Polygon([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])
    g = _gdf([rect, lshape])
    F.shape_features(g, EPSG)
    assert g["aspect_ratio"].iloc[0] == pytest.approx(4.0, rel=1e-6)
    assert g["convexity"].iloc[1] < 1.0          # 凹形 convexity < 1
    assert 0 < g["compactness"].iloc[1] < 1.0


def test_neighborhood_features_counts_and_nn():
    # 三栋同簇(间距 50m 内),一栋孤立(>100m)
    sq = lambda x, y: Polygon([(x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)])
    g = _gdf([sq(0, 0), sq(30, 0), sq(0, 30), sq(500, 500)])
    gm = g.copy()
    F.neighborhood_features(g, gm, radius_m=100.0, no_neighbor_fill=0.0)
    assert g["n_bld_100m"].tolist() == [2, 2, 2, 0]
    assert g["nbr_fp_med_m2"].iloc[0] == pytest.approx(100.0)
    assert g["nbr_fp_med_m2"].iloc[3] == 0.0      # 无邻居回填
    assert g["nn_dist_m"].iloc[0] == pytest.approx(30.0, abs=1.0)


def test_feature_matrix_no_nan():
    g = _gdf([Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])])
    F.shape_features(g, EPSG)
    g["floors"] = [2]
    g["is_supertall"] = [False]
    F.scale_features(g)
    g["euluc_class"] = [np.nan]
    g["euluc_out"] = [True]
    g["ep"] = [np.nan]
    g["nn_dist_m"], g["n_bld_100m"], g["nbr_fp_med_m2"] = [5.0], [0], [0.0]
    g["parcel_area_m2"], g["n_bld_in_parcel"] = [0.0], [0]
    g["gfa_share_parcel"], g["in_parcel"] = [0.0], [0]
    X = F.build_feature_matrix(g)
    assert np.isfinite(X.to_numpy()).all()
    assert "euluc_nan" in X.columns and "ep_nan" in X.columns
