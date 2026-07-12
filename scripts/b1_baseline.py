"""B1 基线版 — Module B ML archetype 推断(摸底,不是考试)。

工作令 2026-07-12(brief 由 claude.ai 下发):
  1) 真值 = validation 156 annotated,复用 A6 validation↔master 匹配逻辑
     (within → 10m 最近邻兜底),口径对齐 annotated 156 / in-parcel 136,
     对不齐立即停止;V009/V096/V141 剔出训练真值(待改判)。
  2) 特征 = 仅 master + EULUC,零 POI 特征(src/buildings_shanghai/ml/features.py)。
  3) RandomForest class_weight='balanced',无 SMOTE;~5km 网格 GroupKFold
     空间 CV;bootstrap 95% CI。
  4) 双分母评估:(a) 全匹配真值集(156 与 153 两个口径都报);
     (b) in-parcel n=136 同分母 vs 规则 52.2% / EULUC-only 54.4%。
  5) 全市 843,062 栋推断仅诊断:预测 parquet 落 --out-dir(不 commit、不落
     master);只出汇总 CSV(置信度分布 + 临港/张江 vs 全市)。
  6) B2 补标清单 100-150 栋分层抽样(seed=20260712)。

运行:
  python scripts/b1_baseline.py --data-dir ~/b1_data
输入(--data-dir 下,不入 git):
  module_a_master.gpkg / euluc_shanghai_2022.gpkg / "2026 Building/2026 Building.shp"
产出:
  data/reference/b1_*.csv(汇总,commit)
  data/raw/validation/b2_annotation_list_v0.csv(commit)
  <out-dir>/b1_citywide_predictions.parquet + b1_model.joblib(不 commit)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from buildings_shanghai.ml import features as F                      # noqa: E402
from buildings_shanghai.validation.baidu import wgs84_to_bd09        # noqa: E402
from buildings_shanghai.validation.windows import WINDOWS            # noqa: E402

REF_DIR = PROJECT_ROOT / "data" / "reference"
VAL_DIR = PROJECT_ROOT / "data" / "raw" / "validation"
VAL_CSV = VAL_DIR / "shanghai_validation_set_v0.csv"


def _log(msg: str) -> None:
    print(f"[b1] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# 真值匹配(复用 A6 diagnostics 的匹配逻辑)                                     #
# --------------------------------------------------------------------------- #
def match_validation(g: gpd.GeoDataFrame, cfg: dict) -> pd.DataFrame:
    epsg = cfg["metric_epsg"]
    maxd = cfg["truth"]["match_max_distance_m"]
    val = pd.read_csv(VAL_CSV)
    val = val[val.status == "annotated"].rename(columns={"archetype": "truth_arch"}).copy()
    pts = gpd.GeoDataFrame(val, geometry=gpd.points_from_xy(val.lon, val.lat), crs=4326)
    gm = gpd.GeoDataFrame({"row": np.arange(len(g))}, geometry=g.geometry, crs=g.crs)
    w = gpd.sjoin(pts, gm, predicate="within", how="left")
    w = w[~w.index.duplicated(keep="first")]
    miss = w.index[w["row"].isna()]
    if len(miss):
        nn = gpd.sjoin_nearest(pts.loc[miss].to_crs(epsg), gm.to_crs(epsg),
                               max_distance=maxd, how="left")
        nn = nn[~nn.index.duplicated(keep="first")]
        w.loc[miss, "row"] = nn["row"]
    val["row"] = w["row"].to_numpy()
    matched = val[val.row.notna()].copy()
    matched["row"] = matched["row"].astype(int)

    n_exp, p_exp = cfg["truth"]["expected_matched"], cfg["truth"]["expected_in_parcel"]
    in_parcel = int(g["euluc_class"].iloc[matched["row"]].notna().sum())
    _log(f"真值匹配: annotated={len(val)} matched={len(matched)} in_parcel={in_parcel} "
         f"(既有口径 {n_exp}/{p_exp})")
    if len(matched) != n_exp or in_parcel != p_exp:
        raise SystemExit(f"[b1][STOP] 匹配口径对不齐:matched={len(matched)} (期望 {n_exp}), "
                         f"in_parcel={in_parcel} (期望 {p_exp})。按工作令停止,先报告。")
    return matched


# --------------------------------------------------------------------------- #
# 评估工具                                                                      #
# --------------------------------------------------------------------------- #
def _boot_ci(correct: np.ndarray, weights: np.ndarray | None, n_boot: int,
             rng: np.random.Generator) -> tuple[float, float]:
    n = len(correct)
    idx = rng.integers(0, n, size=(n_boot, n))
    if weights is None:
        accs = correct[idx].mean(axis=1)
    else:
        w = weights[idx]
        accs = (correct[idx] * w).sum(axis=1) / w.sum(axis=1)
    return float(np.percentile(accs, 2.5)), float(np.percentile(accs, 97.5))


def eval_denominator(name: str, truth: np.ndarray, pred: np.ndarray, gfa: np.ndarray,
                     n_boot: int, rng: np.random.Generator) -> list[dict]:
    correct = (truth == pred).astype(float)
    acc = float(correct.mean())
    lo, hi = _boot_ci(correct, None, n_boot, rng)
    wacc = float((correct * gfa).sum() / gfa.sum())
    wlo, whi = _boot_ci(correct, gfa, n_boot, rng)
    _log(f"评估[{name}] n={len(truth)} acc={acc:.3f} [{lo:.3f},{hi:.3f}] "
         f"GFA加权={wacc:.3f} [{wlo:.3f},{whi:.3f}]")
    return [
        {"denominator": name, "metric": "accuracy", "value": round(acc * 100, 1),
         "ci95_lo": round(lo * 100, 1), "ci95_hi": round(hi * 100, 1), "n": len(truth)},
        {"denominator": name, "metric": "gfa_weighted_accuracy", "value": round(wacc * 100, 1),
         "ci95_lo": round(wlo * 100, 1), "ci95_hi": round(whi * 100, 1), "n": len(truth)},
    ]


# --------------------------------------------------------------------------- #
# 窗口掩码(临港/张江;windows.py 语义:EPSG:4547 下的米制方框)                 #
# --------------------------------------------------------------------------- #
def window_masks(g: gpd.GeoDataFrame) -> dict[str, np.ndarray]:
    from pyproj import Transformer
    tr = Transformer.from_crs(4326, 4547, always_xy=True)
    rp = g.geometry.representative_point()
    bx, by = tr.transform(rp.x.to_numpy(), rp.y.to_numpy())
    masks = {}
    for wname in ("lingang", "zhangjiang"):
        wdef = next(w for w in WINDOWS if w.key == wname)
        cx, cy = tr.transform(wdef.lon, wdef.lat)
        h = wdef.halfwidth_m
        masks[wname] = (np.abs(bx - cx) <= h) & (np.abs(by - cy) <= h)
    return masks


# --------------------------------------------------------------------------- #
# B2 补标清单                                                                   #
# --------------------------------------------------------------------------- #
def build_b2_list(g: gpd.GeoDataFrame, matched: pd.DataFrame, cfg: dict,
                  masks: dict[str, np.ndarray], rng: np.random.Generator) -> pd.DataFrame:
    b2 = cfg["b2"]
    taken: set[int] = set()
    val_rows = set(matched["row"].tolist())          # 避开 validation 既有源行
    conf = g["pred_confidence"].to_numpy()
    rows: list[tuple[int, str]] = []

    def _grab(pool: np.ndarray, k: int, stratum: str) -> None:
        pool = np.array([r for r in pool if r not in taken and r not in val_rows])
        k = min(k, len(pool))
        sel = rng.choice(pool, size=k, replace=False) if k else np.array([], int)
        taken.update(sel.tolist())
        rows.extend((int(r), stratum) for r in sel)

    # 改判三栋置顶(validation 源行,不受避让约束)
    for vid in cfg["truth"]["exclude_val_ids"]:
        r = int(matched.loc[matched.val_id == vid, "row"].iloc[0])
        rows.append((r, f"reassess_{vid}"))
        taken.add(r)

    # hotel 层:规则 hotel 命中池,模型高/低置信各半
    pool = np.flatnonzero((g["archetype"] == "hotel").to_numpy())
    q1, q2 = np.percentile(conf[pool], [33.3, 66.7])
    _grab(pool[conf[pool] >= q2], b2["hotel_n"] // 2, "hotel_high_conf")
    _grab(pool[conf[pool] <= q1], b2["hotel_n"] - b2["hotel_n"] // 2, "hotel_low_conf")

    # sport_culture 层:Class 9 捆绑池,footprint 四分位分层(供拆分)
    pool = np.flatnonzero(g["bundled_label"].astype(bool).to_numpy())
    qs = np.percentile(g["area_m2"].to_numpy()[pool], [25, 50, 75])
    fp = g["area_m2"].to_numpy()
    parts = [pool[fp[pool] <= qs[0]], pool[(fp[pool] > qs[0]) & (fp[pool] <= qs[1])],
             pool[(fp[pool] > qs[1]) & (fp[pool] <= qs[2])], pool[fp[pool] > qs[2]]]
    sc_n = b2["sport_culture_n"]
    base, rem = divmod(sc_n, 4)
    quota = [base + (1 if i < rem else 0) for i in range(4)]
    for i, (p, k) in enumerate(zip(parts, quota), 1):
        _grab(p, k, f"sport_culture_fp_q{i}")

    # 楼层分层(兼层数验证):floors NA(supertall 未配)不入箱
    floors = pd.to_numeric(g["floors"], errors="coerce").to_numpy()
    edges = b2["floors_bins"] + [np.inf]
    for lo, hi in zip(edges[:-1], edges[1:]):
        p = np.flatnonzero((floors >= lo) & (floors < hi))
        tag = f"floors_{lo:g}plus" if np.isinf(hi) else f"floors_{lo:g}_{hi - 1:g}"
        _grab(p, b2["floors_per_bin"], tag)

    # 低置信度层:临港/张江配额(窗口内底部三分位)+ 全市底部十分位跨类
    for wname in ("lingang", "zhangjiang"):
        p = np.flatnonzero(masks[wname])
        thr = np.percentile(conf[p], 33.3)
        _grab(p[conf[p] <= thr], b2[f"low_conf_quota_{wname}"], f"low_conf_{wname}")
    thr10 = np.percentile(conf, 10)
    pool = np.flatnonzero((conf <= thr10) & ~masks["lingang"] & ~masks["zhangjiang"])
    by_class = pd.Series(g["pred_class"].to_numpy()[pool], index=pool)
    classes = sorted(by_class.unique())
    k_city, picked = b2["low_conf_n_citywide"], 0
    ci = 0
    class_pools = {c: rng.permutation(by_class.index[by_class == c].to_numpy()).tolist()
                   for c in classes}
    while picked < k_city and any(class_pools.values()):
        c = classes[ci % len(classes)]
        ci += 1
        while class_pools[c]:
            r = int(class_pools[c].pop())
            if r not in taken and r not in val_rows:
                rows.append((r, "low_conf_citywide"))
                taken.add(r)
                picked += 1
                break

    idx = np.array([r for r, _ in rows])
    out = g.iloc[idx][["bid", "district", "label_rule", "euluc_class", "floors",
                       "area_m2", "pred_class", "pred_confidence"]].copy()
    out["stratum"] = [s for _, s in rows]
    rp = g.geometry.iloc[idx].representative_point()
    out["lat_wgs84"] = rp.y.round(7).to_numpy()
    out["lon_wgs84"] = rp.x.round(7).to_numpy()
    bd = [wgs84_to_bd09(la, lo) for la, lo in zip(rp.y, rp.x)]
    out["lat_bd09"] = [round(b[0], 7) for b in bd]
    out["lon_bd09"] = [round(b[1], 7) for b in bd]
    for c in ("actual_class", "actual_floors", "notes"):
        out[c] = ""
    out = out.rename(columns={"area_m2": "footprint_m2"})
    cols = ["bid", "district", "lat_wgs84", "lon_wgs84", "lat_bd09", "lon_bd09",
            "label_rule", "euluc_class", "floors", "footprint_m2",
            "pred_class", "pred_confidence", "stratum",
            "actual_class", "actual_floors", "notes"]
    out = out[cols]
    out["pred_confidence"] = out["pred_confidence"].round(3)
    out["footprint_m2"] = out["footprint_m2"].round(1)
    return out


# --------------------------------------------------------------------------- #
# 主流程                                                                        #
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True,
                    help="master/euluc/2026 shp 所在目录(不入 git)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="大文件产出目录,默认 <data-dir>/b1_out")
    args = ap.parse_args()
    out_dir = args.out_dir or args.data_dir / "b1_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "b1_baseline.yaml"))
    seed = cfg["seed"]
    rng = np.random.default_rng(seed)
    epsg = cfg["metric_epsg"]

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
    from sklearn.model_selection import GroupKFold

    # ---- 1. 载入 + 特征 -----------------------------------------------------
    _log("载入 master…")
    g = F.load_master(args.data_dir / "module_a_master.gpkg")
    F.attach_vendor_fields(g, args.data_dir / "2026 Building" / "2026 Building.shp")
    _log(f"master {len(g):,} 栋;形状系…")
    gm = F.shape_features(g, epsg, cfg["features"]["aspect_ratio_min_side_m"])
    F.scale_features(g)
    _log(f"邻域系(r={cfg['features']['neighborhood_radius_m']}m)…")
    xy = F.neighborhood_features(g, gm, cfg["features"]["neighborhood_radius_m"],
                                 cfg["features"]["no_neighbor_fill"])
    del gm
    _log("parcel 系…")
    F.parcel_features(g, args.data_dir / "euluc_shanghai_2022.gpkg", epsg)
    _log(f"euluc 复联一致率 {g.attrs['euluc_rejoin_agreement']:.4f} | "
         f"supertall floors 特征回填 {g.attrs['supertall_floors_imputed_n']} 栋 "
         f"(值={g.attrs['supertall_floors_impute_value']:.0f}) | "
         f"aspect 退化 {g.attrs['aspect_degenerate_n']} 栋")
    X = F.build_feature_matrix(g)
    _log(f"特征矩阵 {X.shape[0]:,} × {X.shape[1]}(零 POI,无 district)")

    # ---- 2. 真值 -------------------------------------------------------------
    matched = match_validation(g, cfg)
    excl = set(cfg["truth"]["exclude_val_ids"])
    train = matched[~matched.val_id.isin(excl)].copy()
    _log(f"训练真值 n={len(train)}(剔出 {sorted(excl)});类分布:")
    cls_n = train["truth_arch"].value_counts()
    for c, n in cls_n.items():
        flag = "" if n >= cfg["truth"]["min_learnable_n"] else "  <-- 不可学,待 B2 补样"
        _log(f"  {c:20s} {n:3d}{flag}")

    # ---- 3. 空间分组 CV(~5km 网格 GroupKFold)-------------------------------
    grid = cfg["cv"]["grid_size_m"]
    rows_tr = train["row"].to_numpy()
    cells = (np.floor(xy[rows_tr, 0] / grid).astype(int) * 100000
             + np.floor(xy[rows_tr, 1] / grid).astype(int))
    _log(f"空间 CV:{len(np.unique(cells))} 个 {grid / 1000:g}km 网格组,"
         f"{cfg['cv']['n_splits']} 折 GroupKFold")
    y_tr = train["truth_arch"].to_numpy()
    X_tr = X.iloc[rows_tr].to_numpy()
    rf_kw = dict(n_estimators=cfg["model"]["n_estimators"],
                 max_depth=cfg["model"]["max_depth"],
                 min_samples_leaf=cfg["model"]["min_samples_leaf"],
                 class_weight=cfg["model"]["class_weight"],
                 random_state=seed, n_jobs=-1)
    oof = np.empty(len(train), dtype=object)
    for k, (itr, ite) in enumerate(GroupKFold(cfg["cv"]["n_splits"]).split(X_tr, y_tr, cells)):
        m = RandomForestClassifier(**rf_kw).fit(X_tr[itr], y_tr[itr])
        oof[ite] = m.predict(X_tr[ite])
        _log(f"  fold {k}: test={len(ite)} 组={sorted(set(cells[ite]))}")

    # ---- 4. 终模型 + 全市推断(仅诊断)---------------------------------------
    _log("终模型(全训练真值)+ 全市 843,062 栋推断…")
    model = RandomForestClassifier(**rf_kw).fit(X_tr, y_tr)
    proba = model.predict_proba(X.to_numpy())
    g["pred_class"] = model.classes_[np.argmax(proba, axis=1)]
    g["pred_confidence"] = proba.max(axis=1)
    del proba
    import joblib
    joblib.dump(model, out_dir / "b1_model.joblib")
    g[["bid", "pred_class", "pred_confidence"]].to_parquet(
        out_dir / "b1_citywide_predictions.parquet", index=False)
    _log(f"预测 parquet + model 落 {out_dir}(不 commit)")

    # ---- 5. 双分母评估 --------------------------------------------------------
    n_boot = cfg["evaluation"]["bootstrap_n"]
    gfa_all = g["gfa_m2"].to_numpy()
    # 156 全匹配:153 用 OOF,3 栋待改判用终模型(其从未进训练)
    pred156 = pd.Series(index=matched.index, dtype=object)
    pred156.loc[train.index] = oof
    excl_rows = matched[matched.val_id.isin(excl)]
    pred156.loc[excl_rows.index] = g["pred_class"].iloc[excl_rows["row"]].to_numpy()
    truth156 = matched["truth_arch"].to_numpy()
    gfa156 = gfa_all[matched["row"].to_numpy()]
    inpar = g["euluc_class"].iloc[matched["row"]].notna().to_numpy()

    metrics: list[dict] = []
    metrics += eval_denominator("train_truth_153_oof", y_tr, np.array(list(oof)),
                                gfa_all[rows_tr], n_boot, rng)
    metrics += eval_denominator("full_matched_156", truth156, pred156.to_numpy(),
                                gfa156, n_boot, rng)
    metrics += eval_denominator("in_parcel_136", truth156[inpar],
                                pred156.to_numpy()[inpar], gfa156[inpar], n_boot, rng)
    rb = cfg["evaluation"]["rule_baselines"]
    metrics += [{"denominator": "in_parcel_136", "metric": "rule_full_baseline_a6",
                 "value": rb["full_rule_in_parcel_pct"], "ci95_lo": None, "ci95_hi": None, "n": 136},
                {"denominator": "in_parcel_136", "metric": "rule_euluc_only_baseline_a6",
                 "value": rb["euluc_only_pct"], "ci95_lo": None, "ci95_hi": None, "n": 136}]

    # ---- 6. 逐类表 / 混淆矩阵 / 特征重要性 ------------------------------------
    classes = sorted(cls_n.index)
    oof_arr = np.array(list(oof))
    p, r, f1, sup = precision_recall_fscore_support(y_tr, oof_arr, labels=classes,
                                                    zero_division=0)
    per_class = pd.DataFrame({
        "class": classes, "n_truth_train": [int(cls_n[c]) for c in classes],
        "precision": p.round(3), "recall": r.round(3), "f1": f1.round(3),
        "learnable": [cls_n[c] >= cfg["truth"]["min_learnable_n"] for c in classes],
        "note": ["" if cls_n[c] >= cfg["truth"]["min_learnable_n"]
                 else "不可学,待 B2 补样" for c in classes]})
    cm = pd.DataFrame(confusion_matrix(y_tr, oof_arr, labels=classes),
                      index=pd.Index(classes, name="truth"), columns=classes)
    imp = pd.DataFrame({"feature": X.columns, "importance": model.feature_importances_})
    imp = imp.sort_values("importance", ascending=False).reset_index(drop=True)
    imp["rank"] = imp.index + 1
    imp["top10"] = imp["rank"] <= 10
    imp["importance"] = imp["importance"].round(5)

    # ---- 7. 全市诊断汇总(置信度分布 + 临港/张江)------------------------------
    conf = g["pred_confidence"].to_numpy()
    bw = cfg["evaluation"]["confidence_bin_width"]
    bins = np.arange(0, 1 + bw, bw)
    hist, _ = np.histogram(conf, bins=bins)
    conf_rows = [{"scope": "citywide", "item": f"conf_[{lo:.1f},{hi:.1f})",
                  "n": int(n), "share_pct": round(100 * n / len(g), 2)}
                 for lo, hi, n in zip(bins[:-1], bins[1:], hist)]
    for c in classes:
        m = g["pred_class"].to_numpy() == c
        if m.any():
            conf_rows.append({"scope": f"pred_{c}", "item": "n_conf_mean_median",
                              "n": int(m.sum()),
                              "share_pct": round(float(np.mean(conf[m])), 3),
                              "extra": round(float(np.median(conf[m])), 3)})
    masks = window_masks(g)
    diag_rows = []
    for scope, m in [("citywide", np.ones(len(g), bool))] + list(masks.items()):
        sub_pred, sub_conf = g["pred_class"].to_numpy()[m], conf[m]
        base = {"scope": scope, "n": int(m.sum()),
                "conf_mean": round(float(sub_conf.mean()), 3),
                "conf_median": round(float(np.median(sub_conf)), 3),
                "euluc_out_share_pct": round(100 * float(g["euluc_out"].to_numpy()[m].mean()), 1)}
        for c in classes:
            base[f"share_{c}_pct"] = round(100 * float((sub_pred == c).mean()), 1)
        diag_rows.append(base)

    # ---- 8. B2 清单 -----------------------------------------------------------
    b2 = build_b2_list(g, matched, cfg, masks, rng)
    _log(f"B2 清单 {len(b2)} 栋;分层构成:")
    for s, n in b2["stratum"].value_counts().items():
        _log(f"  {s:25s} {n}")

    # ---- 9. 落盘 --------------------------------------------------------------
    REF_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(metrics).to_csv(REF_DIR / "b1_metrics.csv", index=False)
    per_class.to_csv(REF_DIR / "b1_per_class_metrics.csv", index=False)
    cm.to_csv(REF_DIR / "b1_confusion_matrix.csv")
    imp.to_csv(REF_DIR / "b1_feature_importance.csv", index=False)
    pd.DataFrame(conf_rows).to_csv(REF_DIR / "b1_confidence_distribution.csv", index=False)
    pd.DataFrame(diag_rows).to_csv(REF_DIR / "b1_district_diagnostics.csv", index=False)

    hdr = (f"# B2 补标清单 v0 — 分层抽样 seed={seed}(2026-07-12,B1 基线版产出)\n"
           f"# 分母口径: 抽样总体 = master 843,062 栋剔除 validation 156 匹配源行;"
           f"floors NA(28 栋 supertall 未配)不入楼层箱\n"
           f"# 分层: reassess_V009/V096/V141 置顶(§6 改判后门)| hotel 规则命中池高/低置信 "
           f"| sport_culture 捆绑池 footprint 四分位 | 楼层 6 箱(兼层数验证)"
           f"| 低置信(临港/张江窗口配额 + 全市底部十分位跨类)\n"
           f"# 预测列 = B1 基线 RF(零 POI 特征)仅诊断参考,标注以实地/影像为准;"
           f"BD-09 供百度检索,WGS84 贴 Google 卫星图,勿混用\n"
           f"# actual_class / actual_floors / notes 由 owner 填写\n")
    with open(VAL_DIR / "b2_annotation_list_v0.csv", "w", encoding="utf-8-sig") as fh:
        fh.write(hdr)
        b2.to_csv(fh, index=False)
    _log("汇总 CSV → data/reference/b1_*.csv;B2 清单 → data/raw/validation/"
         "b2_annotation_list_v0.csv")
    _log("完成。")


if __name__ == "__main__":
    main()
