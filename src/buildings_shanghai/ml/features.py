"""Module B 特征工程 — 仅 master + EULUC,零 POI 特征。

特征纪律(B1 工作令 2026-07-12,承 A6.2 空间不均匀教训):
POI 面数据在 A3a 阶段只覆盖 validation 网格 + 收窄 typecode,空间不均匀,
入特征会把"有没有被抓过 POI"学成伪信号 —— 一切 POI 派生列(mall_signal /
hotel_signal / mixed_use_candidate / label_rule / archetype / bundled_label)
都不进特征矩阵。district 同样不进(validation 仅 5 窗口,n 太小防伪相关)。

五个特征系:
  形状系  footprint_m2 / perimeter_m / compactness / aspect_ratio / convexity
  规模系  floors / gfa_m2 / is_supertall
  邻域系  n_bld_100m / nbr_fp_med_m2 / nn_dist_m
  parcel  euluc_class(one-hot 含 out)/ parcel_area_m2 / n_bld_in_parcel /
          gfa_share_parcel / in_parcel
  供应商  ep(one-hot;14 值分类编码,语义待供应商核实,禁作层数)
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely


def load_master(master_gpkg: Path) -> gpd.GeoDataFrame:
    """读 module_a_master.gpkg,fid 保留为 bid 列(1-based,= 2026 shp 行序+1)。"""
    g = gpd.read_file(master_gpkg, fid_as_index=True)
    g = g.reset_index().rename(columns={"fid": "bid"})
    assert g.crs.to_epsg() == 4326, f"master CRS != 4326: {g.crs}"
    return g


def attach_vendor_fields(g: gpd.GeoDataFrame, shp26: Path) -> None:
    """ep / district 按行序回取(master 由 2026 shp 保序构建,a6_stage1 load_chassis)。

    district 仅作 B0/B2 导出元数据,不进特征。
    """
    vend = pyogrio.read_dataframe(shp26, columns=["ep", "district"], read_geometry=False)
    assert len(vend) == len(g), f"2026 DBF 行数 {len(vend)} != master {len(g)}"
    idx = g["bid"].to_numpy() - 1
    g["ep"] = pd.to_numeric(vend["ep"].to_numpy()[idx], errors="coerce")
    g["district"] = vend["district"].to_numpy()[idx]


def shape_features(g: gpd.GeoDataFrame, metric_epsg: int,
                   aspect_min_side_m: float = 0.5) -> gpd.GeoDataFrame:
    """形状系(米制投影下计算);返回米制投影副本供后续邻域/网格复用。"""
    gm = g.to_crs(metric_epsg)
    geom = gm.geometry.to_numpy()
    area = shapely.area(geom)
    perim = shapely.length(geom)
    g["perimeter_m"] = perim
    g["compactness"] = 4.0 * np.pi * area / np.square(np.maximum(perim, 1e-9))

    hull_area = shapely.area(shapely.convex_hull(geom))
    g["convexity"] = np.where(hull_area > 0, area / np.maximum(hull_area, 1e-9), 1.0)

    # 最小外接矩形长宽比;退化几何(envelope 非 5 点闭环 / 短边过短)回填中位数
    rect = shapely.oriented_envelope(geom)
    coords, cidx = shapely.get_coordinates(rect, return_index=True)
    counts = np.bincount(cidx, minlength=len(g))
    starts = np.cumsum(counts) - counts
    ok = counts == 5
    aspect = np.full(len(g), np.nan)
    p0, p1, p2 = coords[starts[ok]], coords[starts[ok] + 1], coords[starts[ok] + 2]
    e1 = np.linalg.norm(p1 - p0, axis=1)
    e2 = np.linalg.norm(p2 - p1, axis=1)
    long_side, short_side = np.maximum(e1, e2), np.minimum(e1, e2)
    aspect[ok] = np.where(short_side >= aspect_min_side_m,
                          long_side / np.maximum(short_side, 1e-9), np.nan)
    n_bad = int(np.isnan(aspect).sum())
    if n_bad:
        aspect = np.where(np.isnan(aspect), np.nanmedian(aspect), aspect)
    g["aspect_ratio"] = aspect
    g.attrs["aspect_degenerate_n"] = n_bad
    return gm


def scale_features(g: gpd.GeoDataFrame) -> None:
    """规模系。28 栋 supertall 未配层数仅在特征层面回填(不回写数据),
    is_supertall flag 保留其"层数不可靠"信息。"""
    floors = pd.to_numeric(g["floors"], errors="coerce")
    sup_med = floors[g["is_supertall"].astype(bool) & floors.notna()].median()
    g["floors_feat"] = floors.fillna(sup_med).astype(float)
    g.attrs["supertall_floors_imputed_n"] = int(floors.isna().sum())
    g.attrs["supertall_floors_impute_value"] = float(sup_med)
    g["gfa_m2"] = g["area_m2"].to_numpy() * g["floors_feat"].to_numpy()
    g["is_supertall_int"] = g["is_supertall"].astype(int)


def neighborhood_features(g: gpd.GeoDataFrame, gm: gpd.GeoDataFrame,
                          radius_m: float, no_neighbor_fill: float = 0.0) -> np.ndarray:
    """邻域系:100m 内楼栋数 / 邻居 footprint 中位数 / 最近邻距离。

    以米制 representative_point 为楼栋代表点;返回代表点坐标 (N,2) 供网格分组复用。
    """
    from scipy.spatial import cKDTree

    rp = gm.geometry.representative_point()
    xy = np.column_stack([rp.x.to_numpy(), rp.y.to_numpy()])
    tree = cKDTree(xy)

    dist, _ = tree.query(xy, k=2, workers=-1)
    g["nn_dist_m"] = dist[:, 1]

    pairs = tree.query_pairs(r=radius_m, output_type="ndarray")   # 每对一次
    n = len(g)
    counts = np.bincount(pairs[:, 0], minlength=n) + np.bincount(pairs[:, 1], minlength=n)
    g["n_bld_100m"] = counts

    area = g["area_m2"].to_numpy()
    node = np.concatenate([pairs[:, 0], pairs[:, 1]])
    nbr_area = np.concatenate([area[pairs[:, 1]], area[pairs[:, 0]]])
    order = np.argsort(node, kind="stable")
    node_s, nbr_s = node[order], nbr_area[order]
    starts = np.searchsorted(node_s, np.arange(n))
    ends = np.searchsorted(node_s, np.arange(n) + 1)
    med = np.full(n, no_neighbor_fill)
    has = ends > starts
    med[has] = [np.median(nbr_s[s:e]) for s, e in zip(starts[has], ends[has])]
    g["nbr_fp_med_m2"] = med
    return xy


def parcel_features(g: gpd.GeoDataFrame, euluc_gpkg: Path, metric_epsg: int) -> None:
    """parcel 系:representative_point within parcel(与 A6 join_euluc 同口径)。

    euluc_class 采用 master 既有列(A6 血统);本函数补 parcel 几何派生特征,
    并对两次 join 的 Class 一致率做 sanity 记录。
    """
    eu = gpd.read_file(euluc_gpkg)
    assert eu.crs.to_epsg() == 4326, f"EULUC CRS != 4326: {eu.crs}"
    eu = eu.reset_index().rename(columns={"index": "parcel_id"})
    eu["parcel_area_m2"] = eu.to_crs(metric_epsg).geometry.area

    cent = gpd.GeoDataFrame({"row": np.arange(len(g))},
                            geometry=g.geometry.representative_point(), crs=g.crs)
    jj = gpd.sjoin(cent, eu[["parcel_id", "Class", "parcel_area_m2", "geometry"]],
                   predicate="within", how="left")
    jj = jj[~jj.index.duplicated(keep="first")].sort_index()

    g["parcel_id"] = pd.array(jj["parcel_id"].to_numpy(), dtype="Int64")
    g["parcel_area_m2"] = np.nan_to_num(jj["parcel_area_m2"].to_numpy(), nan=0.0)

    master_cls = pd.to_numeric(g["euluc_class"], errors="coerce")
    join_cls = pd.to_numeric(jj["Class"], errors="coerce")
    both = master_cls.notna().to_numpy() & join_cls.notna().to_numpy()
    agree = float((master_cls.to_numpy()[both] == join_cls.to_numpy()[both]).mean())
    g.attrs["euluc_rejoin_agreement"] = agree

    pid = g["parcel_id"]
    cnt = pid.value_counts()
    g["n_bld_in_parcel"] = pid.map(cnt).fillna(0).astype(int)
    gfa_sum = pd.Series(g["gfa_m2"].to_numpy()).groupby(pid.to_numpy()).transform("sum")
    share = np.where(gfa_sum.to_numpy() > 0, g["gfa_m2"].to_numpy() / gfa_sum.to_numpy(), 0.0)
    g["gfa_share_parcel"] = np.where(pid.notna().to_numpy(), share, 0.0)
    g["in_parcel"] = (~g["euluc_out"].astype(bool)).astype(int)


NUMERIC_FEATURES = [
    "area_m2", "perimeter_m", "compactness", "aspect_ratio", "convexity",
    "floors_feat", "gfa_m2", "is_supertall_int",
    "n_bld_100m", "nbr_fp_med_m2", "nn_dist_m",
    "parcel_area_m2", "n_bld_in_parcel", "gfa_share_parcel", "in_parcel",
]


def build_feature_matrix(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """数值特征 + euluc_class/ep one-hot(含缺失类别 out/na)。"""
    X = g[NUMERIC_FEATURES].astype(float).copy()
    ec = pd.to_numeric(g["euluc_class"], errors="coerce")
    X = pd.concat([X, pd.get_dummies(ec, prefix="euluc", dummy_na=True, dtype=float)], axis=1)
    ep = pd.to_numeric(g["ep"], errors="coerce")
    X = pd.concat([X, pd.get_dummies(ep, prefix="ep", dummy_na=True, dtype=float)], axis=1)
    X.columns = [c.replace(".0", "") for c in X.columns]
    bad = X.columns[~np.isfinite(X.to_numpy()).all(axis=0)].tolist()
    assert not bad, f"特征矩阵存在 NaN/inf 列: {bad}"
    return X
