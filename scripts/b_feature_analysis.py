"""Feature-space analysis for ground-truth buildings: PCA/t-SNE + Fisher discriminant."""
import pandas as pd
import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from sklearn.preprocessing import StandardScaler
from sklearn.manifold import TSNE
from sklearn.decomposition import PCA
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from itertools import combinations
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
OUTFIG = f"{ROOT}/outputs/figures"
OUTTAB = f"{ROOT}/outputs/tables"

# ── 1. Load and match ──
print("Loading master.gpkg...")
master = gpd.read_file(f"{ROOT}/data/interim/module_a_master.gpkg")

val = pd.read_csv(f"{ROOT}/data/raw/validation/shanghai_validation_set_v0.csv")
val_ann = val[val["status"] == "annotated"].copy()

master_proj = master.to_crs(epsg=4547)
centroids = master_proj.geometry.centroid
tree = cKDTree(np.column_stack([centroids.x.values, centroids.y.values]))

val_gdf = gpd.GeoDataFrame(
    val_ann,
    geometry=gpd.points_from_xy(val_ann["lon"], val_ann["lat"]),
    crs="EPSG:4326",
).to_crs(epsg=4547)
dists, idxs = tree.query(
    np.column_stack([val_gdf.geometry.x.values, val_gdf.geometry.y.values]), k=1
)

matched = master_proj.iloc[idxs].copy().reset_index(drop=True)
matched["val_id"] = val_ann["val_id"].values
matched["gt_archetype"] = val_ann["archetype"].values
matched["match_dist_m"] = dists

# ── 2. Compute features ──
matched["building_footprint"] = matched.geometry.area
matched["perimeter"] = matched.geometry.length
matched["gross_floor_area"] = matched["building_footprint"] * matched["floors"]

mrr = matched.geometry.minimum_rotated_rectangle()
def aspect(r):
    b = r.bounds
    dx, dy = b[2]-b[0], b[3]-b[1]
    long, short = max(dx,dy), min(dx,dy)
    return long / max(short, 0.01)
matched["aspect_ratio"] = mrr.apply(aspect)
matched["compactness_ratio"] = 4 * np.pi * matched["building_footprint"] / (matched["perimeter"]**2)
matched["convexity_ratio"] = matched["building_footprint"] / matched.geometry.convex_hull.area

FEAT_COLS = [
    "building_footprint", "gross_floor_area", "height", "floors",
    "perimeter", "aspect_ratio", "compactness_ratio", "convexity_ratio",
]

# Drop rows with NaN features (supertall with NA floors)
feat_df = matched[["val_id", "gt_archetype"] + FEAT_COLS].dropna(subset=FEAT_COLS)
print(f"Feature matrix: {feat_df.shape[0]} buildings × {len(FEAT_COLS)} features")
print(f"Dropped {len(matched) - len(feat_df)} buildings with NaN features")

# Remove 'unclear' (n=1)
feat_df = feat_df[feat_df["gt_archetype"] != "unclear"].copy()
print(f"After removing unclear: {len(feat_df)} buildings")
print(f"Archetype counts:\n{feat_df['gt_archetype'].value_counts().to_string()}")

X = feat_df[FEAT_COLS].values
y = feat_df["gt_archetype"].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# ── 3. PCA ──
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X_scaled)
print(f"\nPCA explained variance: {pca.explained_variance_ratio_[0]:.3f}, {pca.explained_variance_ratio_[1]:.3f}")
print(f"PCA total: {sum(pca.explained_variance_ratio_[:2]):.3f}")

# PCA loadings
print("\nPCA loadings (PC1, PC2):")
for fname, l1, l2 in zip(FEAT_COLS, pca.components_[0], pca.components_[1]):
    print(f"  {fname:25s}  PC1={l1:+.3f}  PC2={l2:+.3f}")

# ── 4. t-SNE ──
tsne = TSNE(n_components=2, perplexity=min(30, len(X_scaled)-1), random_state=42, init="pca")
X_tsne = tsne.fit_transform(X_scaled)

# ── 5. Plots ──
ARCHETYPE_COLORS = {
    "residential": "#1f77b4",
    "office": "#ff7f0e",
    "shopping_mall": "#2ca02c",
    "education": "#d62728",
    "mixed_use": "#9467bd",
    "government_office": "#8c564b",
    "healthcare": "#e377c2",
    "culture": "#7f7f7f",
    "other_public": "#bcbd22",
}

archetypes = sorted(feat_df["gt_archetype"].unique())

fig, axes = plt.subplots(1, 2, figsize=(18, 8))

for ax, X_2d, title in [
    (axes[0], X_pca, f"PCA (var explained: {sum(pca.explained_variance_ratio_[:2]):.1%})"),
    (axes[1], X_tsne, "t-SNE (perplexity=30)"),
]:
    for arch in archetypes:
        mask = y == arch
        n = mask.sum()
        color = ARCHETYPE_COLORS.get(arch, "#333333")
        ax.scatter(X_2d[mask, 0], X_2d[mask, 1], label=f"{arch} (n={n})",
                   c=color, alpha=0.7, s=50, edgecolors="white", linewidth=0.5)
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Dim 1")
    ax.set_ylabel("Dim 2")

handles, labels = axes[1].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=9,
           bbox_to_anchor=(0.5, -0.02))
fig.suptitle("Feature-Space Separability of 155 Ground-Truth Buildings\n"
             "(8 shape features, EPSG:4547 projection)", fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/feature_space_pca_tsne.png", dpi=150, bbox_inches="tight")
print(f"\nSaved PCA+t-SNE figure to {OUTFIG}/feature_space_pca_tsne.png")

# ── 6. Fisher Discriminant Ratio ──
print(f"\n{'='*80}")
print("FISHER DISCRIMINANT RATIO (pairwise)")
print("FDR = (mu_A - mu_B)^2 / (var_A + var_B), averaged across features")
print(f"{'='*80}")

class_stats = {}
for arch in archetypes:
    mask = y == arch
    if mask.sum() < 2:
        continue
    class_stats[arch] = {
        "mean": X_scaled[mask].mean(axis=0),
        "var": X_scaled[mask].var(axis=0),
        "n": mask.sum(),
    }

fdr_results = []
for a, b in combinations(class_stats.keys(), 2):
    mu_diff_sq = (class_stats[a]["mean"] - class_stats[b]["mean"]) ** 2
    var_sum = class_stats[a]["var"] + class_stats[b]["var"]
    var_sum_safe = np.where(var_sum < 1e-10, 1e-10, var_sum)
    fdr_per_feat = mu_diff_sq / var_sum_safe
    fdr_avg = fdr_per_feat.mean()
    best_feat_idx = np.argmax(fdr_per_feat)
    fdr_results.append({
        "pair": f"{a} vs {b}",
        "fdr_avg": round(fdr_avg, 3),
        "n_a": class_stats[a]["n"],
        "n_b": class_stats[b]["n"],
        "best_feature": FEAT_COLS[best_feat_idx],
        "best_fdr": round(fdr_per_feat[best_feat_idx], 3),
    })

fdr_df = pd.DataFrame(fdr_results).sort_values("fdr_avg", ascending=True)

print("\n--- Most CONFUSED pairs (lowest FDR, hardest to separate) ---")
for _, r in fdr_df.head(10).iterrows():
    print(f"  FDR={r['fdr_avg']:.3f}  {r['pair']:45s}  n=({r['n_a']},{r['n_b']})  best: {r['best_feature']}={r['best_fdr']:.3f}")

print("\n--- Most SEPARABLE pairs (highest FDR) ---")
for _, r in fdr_df.tail(10).iterrows():
    print(f"  FDR={r['fdr_avg']:.3f}  {r['pair']:45s}  n=({r['n_a']},{r['n_b']})  best: {r['best_feature']}={r['best_fdr']:.3f}")

# Save full FDR table
fdr_df.to_csv(f"{OUTTAB}/fisher_discriminant_pairs.csv", index=False)
print(f"\nSaved Fisher table to {OUTTAB}/fisher_discriminant_pairs.csv")

# ── 7. Per-feature discriminability heatmap ──
fig2, ax2 = plt.subplots(figsize=(12, 8))
fdr_matrix = pd.DataFrame(index=sorted(class_stats.keys()), columns=sorted(class_stats.keys()), dtype=float)
for a, b in combinations(class_stats.keys(), 2):
    mu_diff_sq = (class_stats[a]["mean"] - class_stats[b]["mean"]) ** 2
    var_sum = class_stats[a]["var"] + class_stats[b]["var"]
    var_sum_safe = np.where(var_sum < 1e-10, 1e-10, var_sum)
    fdr_avg = (mu_diff_sq / var_sum_safe).mean()
    fdr_matrix.loc[a, b] = fdr_avg
    fdr_matrix.loc[b, a] = fdr_avg
np.fill_diagonal(fdr_matrix.values, 0)

im = ax2.imshow(fdr_matrix.values.astype(float), cmap="YlOrRd", aspect="auto")
ax2.set_xticks(range(len(fdr_matrix)))
ax2.set_xticklabels(fdr_matrix.columns, rotation=45, ha="right", fontsize=9)
ax2.set_yticks(range(len(fdr_matrix)))
ax2.set_yticklabels(fdr_matrix.index, fontsize=9)
for i in range(len(fdr_matrix)):
    for j in range(len(fdr_matrix)):
        v = fdr_matrix.values[i, j]
        if not np.isnan(v):
            ax2.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                     color="white" if v > fdr_matrix.values.max()*0.6 else "black")
plt.colorbar(im, ax=ax2, label="Fisher Discriminant Ratio")
ax2.set_title("Pairwise Fisher Discriminant Ratio\n(higher = more separable)", fontsize=13)
plt.tight_layout()
plt.savefig(f"{OUTFIG}/fisher_heatmap.png", dpi=150, bbox_inches="tight")
print(f"Saved Fisher heatmap to {OUTFIG}/fisher_heatmap.png")

# ── 8. Summary stats table ──
print(f"\n{'='*80}")
print("FEATURE DISTRIBUTIONS BY ARCHETYPE")
print(f"{'='*80}")
for feat in FEAT_COLS:
    stats = feat_df.groupby("gt_archetype")[feat].agg(["count", "median",
        lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)])
    stats.columns = ["n", "median", "Q25", "Q75"]
    stats = stats.round(1)
    print(f"\n--- {feat} ---")
    print(stats.to_string())

# Save feature table
feat_df.to_csv(f"{OUTTAB}/feature_space_156.csv", index=False)
print(f"\nSaved feature table to {OUTTAB}/feature_space_156.csv")
