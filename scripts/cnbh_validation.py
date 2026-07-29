"""
CNBH-10m satellite height vs commercial building height cross-validation.

Uses centroid sampling for speed (10m raster ≈ building footprint scale).
Also runs zonal_stats (max) on a random 10k subset for comparison.
"""

import sys
import time
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import rowcol
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
plt.rcParams.update({
    "figure.dpi": 150,
    "font.size": 10,
    "axes.titlesize": 12,
    "figure.facecolor": "white",
})

CNBH_PATH = Path("/home/user/cnbh10m_shanghai_2020.tif")
MASTER_PATH = Path("/home/user/module_a_master.gpkg")
OUT_DIR = Path("/home/user/Yuqian_Shanghai-Energy/outputs/figures/cnbh_validation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CNBH_SATURATION = 43.0
COMMERCIAL_HEIGHT_MAX = 30.0


def load_and_sample():
    print("Loading master.gpkg...")
    t0 = time.time()
    gdf = gpd.read_file(MASTER_PATH)
    print(f"  Loaded {len(gdf):,} buildings in {time.time()-t0:.1f}s")

    print("Reprojecting to EPSG:32651 (UTM 51N, matching CNBH)...")
    t0 = time.time()
    gdf = gdf.to_crs(epsg=32651)
    print(f"  Done in {time.time()-t0:.1f}s")

    print("Computing centroids and sampling CNBH raster...")
    t0 = time.time()
    centroids = gdf.geometry.centroid
    cx = centroids.x.values
    cy = centroids.y.values

    with rasterio.open(CNBH_PATH) as src:
        data = src.read(1)
        transform = src.transform
        nodata = src.nodata

        rows, cols = rowcol(transform, cx, cy)
        rows = np.array(rows)
        cols = np.array(cols)

        h, w = data.shape
        in_bounds = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)

        cnbh_values = np.full(len(gdf), np.nan)
        valid_idx = np.where(in_bounds)[0]
        sampled = data[rows[valid_idx], cols[valid_idx]]

        mask = (sampled != nodata) & (~np.isnan(sampled)) & (sampled > 0)
        cnbh_values[valid_idx[mask]] = sampled[mask]

    gdf["cnbh_centroid"] = cnbh_values

    has_val = ~np.isnan(cnbh_values)
    print(f"  Sampled {has_val.sum():,} / {len(gdf):,} buildings with valid CNBH ({has_val.mean()*100:.1f}%)")
    print(f"  Time: {time.time()-t0:.1f}s")

    return gdf


def zonal_comparison(gdf, n=10000):
    """Run zonal_stats on a subset to compare centroid vs polygon max."""
    from rasterstats import zonal_stats as zs

    sample = gdf[gdf["cnbh_centroid"].notna()].sample(n=min(n, len(gdf)), random_state=42)
    print(f"\nRunning zonal_stats (max) on {len(sample):,} buildings for comparison...")
    t0 = time.time()

    results = zs(sample, str(CNBH_PATH), stats=["max", "median"],
                 nodata=-9999.0, all_touched=True)

    zonal_max = np.array([r["max"] if r["max"] is not None else np.nan for r in results])
    zonal_med = np.array([r["median"] if r["median"] is not None else np.nan for r in results])
    centroid_vals = sample["cnbh_centroid"].values

    valid = ~np.isnan(zonal_max) & ~np.isnan(centroid_vals)
    diff = centroid_vals[valid] - zonal_max[valid]
    diff_med = centroid_vals[valid] - zonal_med[valid]
    r2 = np.corrcoef(centroid_vals[valid], zonal_max[valid])[0, 1] ** 2

    print(f"  Zonal stats done in {time.time()-t0:.1f}s")
    print(f"  Centroid vs zonal_max: R²={r2:.4f}, MAE={np.mean(np.abs(diff)):.2f}m, "
          f"bias={np.mean(diff):+.2f}m")
    print(f"  Centroid vs zonal_median: MAE={np.mean(np.abs(diff_med)):.2f}m, "
          f"bias={np.mean(diff_med):+.2f}m")
    print(f"  -> Centroid sampling is {'adequate' if r2 > 0.9 else 'rough'} proxy for zonal max")

    return zonal_max, zonal_med, sample


def filter_comparison_set(df, cnbh_col="cnbh_centroid"):
    print("\n=== FILTERING COMPARISON SET ===")
    n_total = len(df)

    has_cnbh = df[cnbh_col].notna() & (df[cnbh_col] > 0)
    print(f"  Has CNBH > 0: {has_cnbh.sum():,} / {n_total:,}")

    below_sat = has_cnbh & (df[cnbh_col] < CNBH_SATURATION)
    print(f"  CNBH < {CNBH_SATURATION}m (below saturation): {below_sat.sum():,}")

    height_ok = df["height"] <= COMMERCIAL_HEIGHT_MAX
    print(f"  Commercial height <= {COMMERCIAL_HEIGHT_MAX}m: {height_ok.sum():,}")

    mask = below_sat & height_ok
    comp = df[mask].copy()
    print(f"  Final comparison set: {len(comp):,} buildings")
    print(f"  Proportion of total: {len(comp)/n_total*100:.1f}%")

    return comp


def compute_statistics(comp, cnbh_col="cnbh_centroid"):
    print("\n=== STATISTICAL SUMMARY ===")

    h_commercial = comp["height"].values.astype(float)
    h_cnbh = comp[cnbh_col].values

    residual = h_commercial - h_cnbh
    valid = ~np.isnan(h_cnbh) & ~np.isnan(h_commercial)
    r = residual[valid]
    hc = h_commercial[valid]
    hs = h_cnbh[valid]

    mae = np.mean(np.abs(r))
    rmse = np.sqrt(np.mean(r**2))
    bias = np.mean(r)
    r2 = np.corrcoef(hc, hs)[0, 1] ** 2

    print(f"\n  N = {valid.sum():,}")
    print(f"  MAE  = {mae:.2f} m")
    print(f"  RMSE = {rmse:.2f} m")
    print(f"  Bias = {bias:+.2f} m (commercial - satellite)")
    print(f"  R²   = {r2:.4f}")
    print(f"  Pearson r = {np.corrcoef(hc, hs)[0,1]:.4f}")

    floors = comp["floors"].values if "floors" in comp.columns else np.round(h_commercial / 4).astype(int)

    print("\n  --- By floor band ---")
    bands = [(1, 1), (2, 2), (3, 3), (4, 6), (7, 10)]
    band_data = {}
    for lo, hi in bands:
        mask_band = (floors >= lo) & (floors <= hi) & valid
        n_band = mask_band.sum()
        if n_band == 0:
            continue
        res_band = residual[mask_band]
        band_data[(lo, hi)] = res_band
        label = f"{lo}" if lo == hi else f"{lo}-{hi}"
        print(f"  Floors {label}: n={n_band:,}, "
              f"MAE={np.mean(np.abs(res_band)):.2f}m, "
              f"bias={np.mean(res_band):+.2f}m, "
              f"RMSE={np.sqrt(np.mean(res_band**2)):.2f}m, "
              f"median_res={np.median(res_band):+.2f}m")

    # CNBH minimum detection limit analysis
    print("\n  --- CNBH detection limit analysis ---")
    print(f"  CNBH value range in comparison set: {hs.min():.2f} - {hs.max():.2f} m")
    print(f"  CNBH p5={np.percentile(hs, 5):.1f}, p10={np.percentile(hs, 10):.1f}, "
          f"p25={np.percentile(hs, 25):.1f}, p50={np.percentile(hs, 50):.1f}m")

    # Filter for CNBH >= 12m (above minimum detection noise)
    print("\n  --- Restricted to CNBH >= 12m (above detection floor) ---")
    above_floor = hs >= 12
    if above_floor.sum() > 100:
        r_above = r[valid][above_floor]
        hc_above = hc[above_floor]
        hs_above = hs[above_floor]
        r2_above = np.corrcoef(hc_above, hs_above)[0, 1] ** 2
        print(f"  N = {above_floor.sum():,}")
        print(f"  MAE  = {np.mean(np.abs(r_above)):.2f} m")
        print(f"  RMSE = {np.sqrt(np.mean(r_above**2)):.2f} m")
        print(f"  Bias = {np.mean(r_above):+.2f} m")
        print(f"  R²   = {r2_above:.4f}")

    return h_commercial, h_cnbh, floors, valid


def plot_scatter(hc, hs, valid, out_path):
    fig, ax = plt.subplots(figsize=(8, 7))

    x = hs[valid]
    y = hc[valid]

    hb = ax.hexbin(x, y, gridsize=60, cmap="YlOrRd", mincnt=1)
    plt.colorbar(hb, ax=ax, label="Count")

    lim = max(x.max(), y.max()) + 2
    ax.plot([0, lim], [0, lim], "k--", alpha=0.5, lw=1.5, label="1:1 line")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("CNBH-10m satellite height (m)")
    ax.set_ylabel("Commercial height (= 4m x floors, synthetic)")
    ax.set_title(f"CNBH Satellite vs Commercial Building Height\n"
                 f"n={valid.sum():,} buildings (height <= 30m, CNBH < 43m)")

    residual = y - x
    stats_text = (f"MAE = {np.mean(np.abs(residual)):.2f} m\n"
                  f"RMSE = {np.sqrt(np.mean(residual**2)):.2f} m\n"
                  f"Bias = {np.mean(residual):+.2f} m\n"
                  f"R² = {np.corrcoef(x, y)[0,1]**2:.4f}")
    ax.text(0.03, 0.97, stats_text, transform=ax.transAxes, va="top", fontsize=10,
            bbox=dict(boxstyle="round", fc="white", alpha=0.8))
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out_path}")
    plt.close(fig)


def plot_residual_histogram(hc, hs, valid, out_path):
    fig, ax = plt.subplots(figsize=(8, 5))

    residual = hc[valid] - hs[valid]
    ax.hist(residual, bins=120, edgecolor="black", linewidth=0.3, alpha=0.8, color="#4C72B0")
    ax.axvline(0, color="red", ls="--", lw=1.5, label="Zero")
    ax.axvline(np.mean(residual), color="orange", ls="-", lw=1.5,
               label=f"Mean = {np.mean(residual):+.2f} m")
    ax.axvline(np.median(residual), color="green", ls="-.", lw=1.5,
               label=f"Median = {np.median(residual):+.2f} m")
    ax.set_xlabel("Residual: Commercial height - CNBH height (m)")
    ax.set_ylabel("Count")
    ax.set_title(f"Residual Distribution (n={valid.sum():,})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out_path}")
    plt.close(fig)


def plot_band_boxplot(hc, hs, floors, valid, out_path):
    fig, ax = plt.subplots(figsize=(9, 5))

    residual = hc - hs
    bands = [(1, 1), (2, 2), (3, 3), (4, 6), (7, 10)]
    data = []
    labels = []
    for lo, hi in bands:
        mask = valid & (floors >= lo) & (floors <= hi)
        res = residual[mask]
        res = res[~np.isnan(res)]
        if len(res) == 0:
            continue
        data.append(res)
        label = f"{lo}" if lo == hi else f"{lo}-{hi}"
        labels.append(f"{label} fl\n(n={len(res):,})")

    bp = ax.boxplot(data, showfliers=False, patch_artist=True,
                    medianprops=dict(color="red", linewidth=2))
    ax.set_xticklabels(labels)
    colors = ["#A1C9F4", "#8DE5A1", "#FFB482", "#D0BBFF", "#FFFEA3"]
    for patch, color in zip(bp["boxes"], colors[:len(data)]):
        patch.set_facecolor(color)

    ax.axhline(0, color="black", ls="--", lw=0.8)
    ax.set_ylabel("Residual: Commercial - CNBH (m)")
    ax.set_title("Residual Distribution by Floor Band")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out_path}")
    plt.close(fig)


def plot_synthetic_signature(hc, hs, valid, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    ax.hist(hc[valid], bins=np.arange(0, 33, 1), edgecolor="black",
            linewidth=0.5, alpha=0.8, color="#E74C3C", label="Commercial height")
    for mult in range(4, 32, 4):
        ax.axvline(mult, color="blue", ls="--", alpha=0.5, lw=1)
    ax.set_xlabel("Height (m)")
    ax.set_ylabel("Count")
    ax.set_title("Commercial height: discrete 4m grid\n(blue lines at 4, 8, 12, ... 28m)")
    ax.legend()

    ax = axes[1]
    ax.hist(hs[valid], bins=120, edgecolor="black", linewidth=0.3,
            alpha=0.8, color="#3498DB", label="CNBH satellite height")
    ax.set_xlabel("Height (m)")
    ax.set_ylabel("Count")
    ax.set_title("CNBH satellite height: continuous distribution\n(no artificial grid)")
    ax.legend()

    fig.suptitle("Synthetic Height Fingerprint: 4m-multiple grid vs continuous satellite measurement",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out_path}")
    plt.close(fig)


def plot_scatter_grid(hc, hs, valid, out_path):
    fig, ax = plt.subplots(figsize=(8, 7))

    x = hs[valid]
    y = hc[valid]
    hb = ax.hexbin(x, y, gridsize=60, cmap="YlOrRd", mincnt=1)
    plt.colorbar(hb, ax=ax, label="Count")

    for mult in range(4, 32, 4):
        ax.axhline(mult, color="blue", ls="--", alpha=0.3, lw=0.8)

    lim = max(x.max(), y.max()) + 2
    ax.plot([0, lim], [0, lim], "k--", alpha=0.5, lw=1.5, label="1:1 line")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("CNBH-10m satellite height (m)")
    ax.set_ylabel("Commercial height (= 4m x floors)")
    ax.set_title("Synthetic 4m-Grid Fingerprint\n"
                 "Horizontal bands at 4, 8, 12, 16, 20, 24, 28m confirm discrete encoding")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out_path}")
    plt.close(fig)


def main():
    gdf = load_and_sample()

    # Zonal stats comparison on subset
    zonal_comparison(gdf, n=10000)

    # Filter and analyze
    comp = filter_comparison_set(gdf)
    if len(comp) == 0:
        print("ERROR: No buildings in comparison set!")
        sys.exit(1)

    hc, hs, floors, valid = compute_statistics(comp)

    # Synthetic fingerprint check
    print("\n=== SYNTHETIC HEIGHT FINGERPRINT ===")
    unique_h = np.sort(comp["height"].unique())
    print(f"  Unique commercial height values (<=30m): {unique_h}")
    n_div4 = (comp["height"] % 4 == 0).sum()
    print(f"  Buildings with height divisible by 4: {n_div4:,} / {len(comp):,} "
          f"({n_div4/len(comp)*100:.1f}%)")

    # Archetype breakdown
    if "archetype" in comp.columns:
        print("\n=== BY ARCHETYPE ===")
        for arch, grp in comp.groupby("archetype"):
            n_arch = len(grp)
            if n_arch < 50:
                continue
            res = grp["height"].values.astype(float) - grp["cnbh_centroid"].values
            res = res[~np.isnan(res)]
            if len(res) == 0:
                continue
            print(f"  {arch}: n={n_arch:,}, MAE={np.mean(np.abs(res)):.2f}m, "
                  f"bias={np.mean(res):+.2f}m")

    # Plots
    print("\n=== GENERATING PLOTS ===")
    plot_scatter(hc, hs, valid, OUT_DIR / "scatter_cnbh_vs_commercial.png")
    plot_residual_histogram(hc, hs, valid, OUT_DIR / "residual_histogram.png")
    plot_band_boxplot(hc, hs, floors, valid, OUT_DIR / "band_boxplot.png")
    plot_synthetic_signature(hc, hs, valid, OUT_DIR / "synthetic_signature.png")
    plot_scatter_grid(hc, hs, valid, OUT_DIR / "scatter_grid_fingerprint.png")

    # Save comparison table
    cols = ["height", "floors", "cnbh_centroid"]
    if "archetype" in comp.columns:
        cols.append("archetype")
    comp_out = comp[cols].copy()
    comp_out["residual"] = comp_out["height"] - comp_out["cnbh_centroid"]
    comp_out.to_csv(OUT_DIR / "cnbh_comparison_table.csv", index=False)
    print(f"  Table saved: {OUT_DIR / 'cnbh_comparison_table.csv'}")

    print("\n" + "="*60)
    print("DONE")
    print("="*60)


if __name__ == "__main__":
    main()
