"""End-to-end pipeline for validation-set #9 workbook generation.

Stages, per the task spec:

    extract   → read shp, run window-scan sampling, save
                candidates_internal.parquet + 5 footprint PNGs.
                *STOP for checkpoint 1 owner approval.*

    links-test → emit 3 test Baidu links for known landmarks (Shanghai
                Tower, Xujiahui Metro Station, Longyang Rd Station).
                *STOP for checkpoint 2 owner approval.*

    emit      → build annotation_workbook.xlsx, validation_pins.kml,
                README_working.md at the deliverable location.

All stages are idempotent given the same seed and input.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from .baidu import CoordType, marker_link
from .kml import build_kml
from .sampling import NotEnoughCandidatesError, sample_window
from .windows import WINDOWS, Window, format_id, id_range
from .workbook import build_workbook


LOG = logging.getLogger(__name__)

INPUT_CRS_EPSG: int = 4326
METRIC_CRS_EPSG: int = 4547  # CGCS2000 3-degree Gauss-Krüger zone 40
DEFAULT_SEED: int = 42


@dataclass(frozen=True)
class PipelinePaths:
    """Filesystem layout for one pipeline run.

    ``root`` is typically ``data/raw/validation/working/`` (final
    deliverables) but the extract stage will also write into
    ``root / "checkpoint1/"`` for the PNG previews and the internal parquet.
    """

    root: Path

    @property
    def candidates_internal_parquet(self) -> Path:
        return self.root / "candidates_internal.parquet"

    @property
    def workbook_xlsx(self) -> Path:
        return self.root / "annotation_workbook.xlsx"

    @property
    def kml(self) -> Path:
        return self.root / "validation_pins.kml"

    @property
    def readme(self) -> Path:
        return self.root / "README_working.md"

    @property
    def checkpoint1_dir(self) -> Path:
        return self.root / "checkpoint1"

    def preview_png(self, window_key: str) -> Path:
        return self.checkpoint1_dir / f"{window_key}_footprints.png"

    def sampling_summary_json(self) -> Path:
        return self.checkpoint1_dir / "sampling_summary.json"


def load_footprints(shp_path: Path) -> gpd.GeoDataFrame:
    """Read the 2026 Shanghai footprint shapefile.

    Attribute encoding is UTF-8, declared by the sidecar ``.cpg`` — pass no
    ``encoding`` override so pyogrio honours it. (Forcing ``gbk`` garbles
    ``district``: 浦东新区 → 娴︿笢鏂板尯.)

    Sanity checks:
        - CRS is EPSG:4326
        - Feature count is ~843,063 (within 0.5% for future re-cuts)
        - Columns ``height``, ``Area``, ``district`` present.
    """
    LOG.info("reading footprints: %s", shp_path)
    gdf = gpd.read_file(shp_path)

    crs_str = str(gdf.crs)
    if gdf.crs is None or gdf.crs.to_epsg() != INPUT_CRS_EPSG:
        raise ValueError(
            f"footprint CRS mismatch: got {crs_str}, expected EPSG:{INPUT_CRS_EPSG}"
        )

    for col in ("height", "Area", "district"):
        if col not in gdf.columns:
            raise ValueError(f"footprint shp missing column: {col}")

    n = len(gdf)
    # Loose tolerance in case owner re-cuts the dataset later.
    if not 838_000 <= n <= 850_000:
        LOG.warning(
            "feature count %d is outside the expected ~843,063 band; "
            "double-check the source zip",
            n,
        )

    LOG.info("loaded %d features, crs=%s", n, gdf.crs)
    return gdf


def to_metric(gdf_wgs84: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject to EPSG:4547 and add ``x_m``, ``y_m`` representative-point columns."""
    LOG.info("reprojecting to EPSG:%d", METRIC_CRS_EPSG)
    gdf_metric = gdf_wgs84.to_crs(METRIC_CRS_EPSG).copy()
    rep = gdf_metric.geometry.representative_point()
    gdf_metric["x_m"] = rep.x
    gdf_metric["y_m"] = rep.y
    return gdf_metric


def project_centre(lat: float, lon: float) -> tuple[float, float]:
    """Return the WGS84 ``(lat, lon)`` projected into EPSG:4547 as ``(x, y)``."""
    from shapely.geometry import Point

    point = gpd.GeoSeries([Point(lon, lat)], crs=INPUT_CRS_EPSG)
    projected = point.to_crs(METRIC_CRS_EPSG).iloc[0]
    return projected.x, projected.y


def _cluster_note(size: int) -> str:
    return f"同款约 {size} 栋(自动识别)" if size >= 2 else ""


@dataclass
class WindowRun:
    """Result of one window's extraction, ready for downstream stages."""

    window: Window
    final_halfwidth_m: int
    #: WGS84 GeoDataFrame with the 40 rows for this window, plus:
    #: 编号, 片区, 抽样方式, lat_wgs84, lon_wgs84, 备注, cluster_id, cluster_size
    picked_wgs84: gpd.GeoDataFrame
    cluster_sizes: dict[int, int]
    dropped_count: int


def run_extract(
    shp_path: Path,
    paths: PipelinePaths,
    *,
    seed: int = DEFAULT_SEED,
) -> list[WindowRun]:
    """Extract → dedup → sample 200 candidates across 5 windows.

    Also writes:
        - ``paths.candidates_internal_parquet`` (internal, has ``height``)
        - ``paths.checkpoint1_dir / "sampling_summary.json"``
        - ``paths.preview_png(window)`` for each window

    Returns the list of ``WindowRun`` so :func:`run_emit` can consume it.
    """
    paths.checkpoint1_dir.mkdir(parents=True, exist_ok=True)

    gdf_wgs84 = load_footprints(shp_path)
    gdf_metric = to_metric(gdf_wgs84)

    rng = np.random.default_rng(seed)

    all_runs: list[WindowRun] = []
    counter = 1
    summary = {
        "seed": seed,
        "input_shp": str(shp_path),
        "input_feature_count": int(len(gdf_wgs84)),
        "windows": [],
    }

    for w in WINDOWS:
        cx, cy = project_centre(w.lat, w.lon)
        LOG.info("sampling window=%s centre_metric=(%.1f, %.1f)", w.key, cx, cy)
        try:
            res = sample_window(
                gdf_metric,
                w,
                centre_x=cx,
                centre_y=cy,
                rng=rng,
            )
        except NotEnoughCandidatesError as exc:
            LOG.error("%s", exc)
            raise

        picked_metric = res.picked
        picked_wgs = _picked_metric_to_wgs84(picked_metric, w, counter, res.cluster_sizes)
        counter += w.quota

        all_runs.append(
            WindowRun(
                window=w,
                final_halfwidth_m=res.final_halfwidth_m,
                picked_wgs84=picked_wgs,
                cluster_sizes=res.cluster_sizes,
                dropped_count=len(res.dropped_duplicates),
            )
        )

        _render_preview(
            gdf_wgs84,
            w,
            cx=cx,
            cy=cy,
            halfwidth_m=res.final_halfwidth_m,
            picked_wgs84=picked_wgs,
            out_path=paths.preview_png(w.key),
        )

        low, high = id_range(w.key)
        summary["windows"].append(
            {
                "key": w.key,
                "label_cn": w.label_cn,
                "centre_wgs84": [w.lat, w.lon],
                "initial_halfwidth_m": w.halfwidth_m,
                "final_halfwidth_m": res.final_halfwidth_m,
                "id_range": [format_id(low), format_id(high)],
                "candidates_kept": int(len(res.all_kept)),
                "dropped_duplicates": int(len(res.dropped_duplicates)),
                "cluster_size_histogram": _histogram(res.cluster_sizes),
                "final_bbox_metric_epsg4547": [
                    cx - res.final_halfwidth_m,
                    cy - res.final_halfwidth_m,
                    cx + res.final_halfwidth_m,
                    cy + res.final_halfwidth_m,
                ],
            }
        )

    combined_internal = _build_internal_parquet(all_runs)
    paths.candidates_internal_parquet.parent.mkdir(parents=True, exist_ok=True)
    combined_internal.to_parquet(paths.candidates_internal_parquet, index=False)

    paths.sampling_summary_json().write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    LOG.info("checkpoint 1 assets written under %s", paths.checkpoint1_dir)
    return all_runs


def _picked_metric_to_wgs84(
    picked_metric: gpd.GeoDataFrame,
    window: Window,
    start_counter: int,
    cluster_sizes: dict[int, int],
) -> gpd.GeoDataFrame:
    """Re-project the picked rows back to EPSG:4326 and attach annotation columns.

    NOTE: this GeoDataFrame is the *internal* one; it still carries
    ``height`` and source row indices. Downstream stages that produce
    annotator-visible artefacts must strip those columns first.
    """
    gdf = picked_metric.to_crs(INPUT_CRS_EPSG).copy()
    rep_wgs = gdf.geometry.representative_point()
    gdf["lat_wgs84"] = rep_wgs.y
    gdf["lon_wgs84"] = rep_wgs.x
    gdf["片区"] = window.label_cn
    gdf["抽样方式"] = "窗口扫描"
    gdf["备注"] = [
        _cluster_note(cluster_sizes.get(int(cid), 1)) for cid in gdf["cluster_id"]
    ]
    gdf["编号"] = [
        format_id(start_counter + i) for i in range(len(gdf))
    ]
    return gdf


def _build_internal_parquet(runs: list[WindowRun]) -> pd.DataFrame:
    """Combined internal candidates table (KEEPS height + cluster info).

    Not for annotators. Committed only because §5 rule (e) requires the
    编号 ↔ source row link to be reproducible.
    """
    frames = []
    for run in runs:
        df = run.picked_wgs84.copy()
        df["window_key"] = run.window.key
        df["final_halfwidth_m"] = run.final_halfwidth_m
        frames.append(pd.DataFrame(df.drop(columns=["geometry"])))
    combined = pd.concat(frames, ignore_index=True)
    return combined


def _histogram(cluster_sizes: dict[int, int]) -> dict[str, int]:
    """Bucket cluster sizes into ``1``, ``2``, ``3``, ``4-6``, ``7+``."""
    buckets = {"1": 0, "2": 0, "3": 0, "4-6": 0, "7+": 0}
    for size in cluster_sizes.values():
        if size == 1:
            buckets["1"] += 1
        elif size == 2:
            buckets["2"] += 1
        elif size == 3:
            buckets["3"] += 1
        elif 4 <= size <= 6:
            buckets["4-6"] += 1
        else:
            buckets["7+"] += 1
    return buckets


def _cjk_font_or_none() -> str | None:
    """Return the first installed CJK-capable font, or ``None``.

    Kept as a per-call lookup so the pipeline stays portable across
    environments without CJK fonts (matplotlib will then render only
    the ASCII part of the title, which is still informative).
    """
    import matplotlib.font_manager as fm

    candidates = (
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Source Han Sans SC",
        "WenQuanYi Zen Hei",
        "WenQuanYi Micro Hei",
        "SimHei",
        "PingFang SC",
    )
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            return name
    return None


def _render_preview(
    all_footprints_wgs84: gpd.GeoDataFrame,
    window: Window,
    *,
    cx: float,
    cy: float,
    halfwidth_m: int,
    picked_wgs84: gpd.GeoDataFrame,
    out_path: Path,
) -> None:
    """Draw one window preview PNG for the owner's checkpoint-1 review.

    Everything in EPSG:4326 for lat/lon axis labels the owner recognises.
    The window rectangle is projected back from the metric square, so it
    is *not* an exact rectangle in lat/lon — that's expected and matches
    the sampler's behaviour.
    """
    from shapely.geometry import box

    cjk_font = _cjk_font_or_none()
    if cjk_font:
        plt.rcParams["font.sans-serif"] = [cjk_font, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(6.5, 6.5), dpi=150)

    metric_box = box(cx - halfwidth_m, cy - halfwidth_m, cx + halfwidth_m, cy + halfwidth_m)
    wgs_box = gpd.GeoSeries([metric_box], crs=METRIC_CRS_EPSG).to_crs(INPUT_CRS_EPSG).iloc[0]

    # Loose lat/lon bounding rectangle for plot bounds + neighbour clip.
    minx, miny, maxx, maxy = wgs_box.bounds
    pad = 0.005
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)

    # Grab every footprint whose centroid falls inside the padded plot area
    # (cheap approximation — plotting all 843k features would blow the PNG).
    reps = all_footprints_wgs84.geometry.representative_point()
    m = (
        (reps.x >= minx - pad)
        & (reps.x <= maxx + pad)
        & (reps.y >= miny - pad)
        & (reps.y <= maxy + pad)
    )
    nearby = all_footprints_wgs84.loc[m]
    nearby.plot(ax=ax, color="#CCCCCC", edgecolor="#888888", linewidth=0.2)

    # Highlight picked buildings.
    picked_wgs84.plot(
        ax=ax, color="#F2C94C", edgecolor="#8A6D00", linewidth=0.4
    )

    # Window rectangle (drawn from the projected polygon so it matches sampler).
    gpd.GeoSeries([wgs_box]).boundary.plot(
        ax=ax, color="#E03131", linewidth=1.5
    )

    ax.set_title(
        f"{window.label_cn} ({window.key})  "
        f"final halfwidth = {halfwidth_m} m  "
        f"picked = {len(picked_wgs84)}",
        fontsize=10,
    )
    ax.set_xlabel("lon (WGS84)")
    ax.set_ylabel("lat (WGS84)")
    ax.set_aspect("equal", adjustable="box")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    LOG.info("wrote preview: %s", out_path)


# ---------------------------------------------------------------------------
# Checkpoint 2 — links test
# ---------------------------------------------------------------------------

#: 3 well-known Shanghai landmarks for the checkpoint-2 link sanity check.
#: True WGS84. The original values here were GCJ-02 mislabelled as WGS84
#: (checkpoint 2, 2026-07-02: every pin landed ~500 m off, on-road). Fixed by
#: iterative inverse-GCJ of those values; cross-checked against the 2026
#: dataset's Jin Mao footprint (3 m) and Wikipedia WGS84 refs (~18 m).
#: Chinese map sources publish GCJ-02 — do not "refresh" these from Amap/Baidu.
LINK_TEST_LANDMARKS: list[tuple[str, float, float]] = [
    ("Shanghai Tower 上海中心", 31.23572, 121.50097),
    ("Xujiahui Metro Station 徐家汇地铁站", 31.19647, 121.43238),
    ("Longyang Rd Metro Station 龙阳路地铁站", 31.20707, 121.55304),
]


def run_links_test(coord_type: CoordType = "wgs84") -> list[dict[str, str]]:
    """Emit 3 baidu marker links for owner verification (checkpoint 2)."""
    return [
        {
            "name": name,
            "lat_wgs84": f"{lat:.5f}",
            "lon_wgs84": f"{lon:.5f}",
            "coord_type": coord_type,
            "url": marker_link(lat, lon, title=name, coord_type=coord_type),
        }
        for (name, lat, lon) in LINK_TEST_LANDMARKS
    ]


# ---------------------------------------------------------------------------
# Emit stage
# ---------------------------------------------------------------------------

_WORKBOOK_COLUMNS = ["编号", "百度直达链接", "片区", "抽样方式", "备注", "lat_wgs84", "lon_wgs84"]


def run_emit(
    runs: list[WindowRun],
    paths: PipelinePaths,
    *,
    coord_type: CoordType = "wgs84",
    seed: int = DEFAULT_SEED,
    run_date: date | None = None,
) -> dict[str, Path]:
    """Build the 3 deliverables from a completed extract stage.

    Blind-test filtering happens *here*: ``height`` and internal columns
    are stripped from the annotator-facing artefacts before they are
    written.
    """
    combined = _combine_runs_for_delivery(runs, coord_type)

    # Blind-test cleanup: keep only the columns the annotator/kml need.
    annotator_df = combined[_WORKBOOK_COLUMNS].copy()
    kml_gdf = combined[[c for c in ["编号", "片区", "百度直达链接", "geometry"]]].copy()

    xlsx = build_workbook(annotator_df, paths.workbook_xlsx)
    kml = build_kml(gpd.GeoDataFrame(kml_gdf, geometry="geometry", crs=INPUT_CRS_EPSG), paths.kml)
    readme = _write_readme(paths, runs, seed=seed, run_date=run_date, coord_type=coord_type)

    return {"workbook": xlsx, "kml": kml, "readme": readme}


def _combine_runs_for_delivery(
    runs: list[WindowRun],
    coord_type: CoordType,
) -> gpd.GeoDataFrame:
    frames = []
    for run in runs:
        df = run.picked_wgs84.copy()
        df["百度直达链接"] = [
            marker_link(lat, lon, title=vid, coord_type=coord_type)
            for vid, lat, lon in zip(df["编号"], df["lat_wgs84"], df["lon_wgs84"])
        ]
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs=INPUT_CRS_EPSG)


def _write_readme(
    paths: PipelinePaths,
    runs: list[WindowRun],
    *,
    seed: int,
    run_date: date | None,
    coord_type: CoordType,
) -> Path:
    stamp = (run_date or date.today()).isoformat()

    lines: list[str] = []
    lines.append("# Validation Set #9 — Working Workbook\n")
    lines.append(
        "Working directory for validation-set annotation. Owner does the labelling\n"
        "in `annotation_workbook.xlsx`; the three files here are the *machine-\n"
        "generated* pre-labelling assets. Do not overwrite them mid-labelling.\n"
    )

    lines.append("## Sampling frame\n")
    lines.append("| window | centre (WGS84 lat, lon) | initial halfwidth | final halfwidth | V-id range |")
    lines.append("|---|---|---|---|---|")
    for run in runs:
        low, high = id_range(run.window.key)
        lines.append(
            f"| {run.window.key} ({run.window.label_cn}) "
            f"| {run.window.lat:.4f}, {run.window.lon:.4f} "
            f"| {run.window.halfwidth_m} m "
            f"| {run.final_halfwidth_m} m "
            f"| {format_id(low)}–{format_id(high)} |"
        )
    lines.append("")

    lines.append("## Rules\n")
    lines.append(
        "- Metric CRS for windowing: **EPSG:4547** (CGCS2000 3-degree GK zone 40).\n"
        "- Area floor: **100 m²**. No height/floor filter (calibration must see the\n"
        "  natural distribution).\n"
        "- Same-model dedup: `|Δarea|/max ≤ 5%` AND `|Δheight| ≤ 0.5 m` AND\n"
        "  `distance ≤ 250 m`. Keep at most 3 buildings per cluster (lowest input\n"
        "  row index).\n"
        "- Halfwidth expansion: `+300 m` steps up to 3000 m; stop-and-report if\n"
        "  the window can't yield 40 candidates at 3000 m.\n"
        f"- Random seed: **{seed}** (`numpy.random.default_rng`).\n"
        f"- Baidu marker links use `coord_type={coord_type}`.\n"
    )

    lines.append("## Deduplication tally\n")
    lines.append("| window | duplicates dropped | cluster size histogram |")
    lines.append("|---|---|---|")
    for run in runs:
        hist = _histogram(run.cluster_sizes)
        hist_str = ", ".join(f"{k}: {v}" for k, v in hist.items())
        lines.append(f"| {run.window.key} | {run.dropped_count} | {hist_str} |")
    lines.append("")

    lines.append("## Blind-test rule\n")
    lines.append(
        "The workbook and KML **must not** carry `height`, `estimated_floor`,\n"
        "or any archetype prediction. The full internal candidates table lives\n"
        "in `candidates_internal.parquet` alongside these files; it is *not*\n"
        "to be shared with the annotator until labelling is complete.\n"
    )

    lines.append(f"## Generation date\n\n{stamp}\n")

    txt = "\n".join(lines)
    paths.readme.write_text(txt, encoding="utf-8")
    return paths.readme


__all__ = [
    "DEFAULT_SEED",
    "INPUT_CRS_EPSG",
    "METRIC_CRS_EPSG",
    "LINK_TEST_LANDMARKS",
    "PipelinePaths",
    "WindowRun",
    "load_footprints",
    "to_metric",
    "project_centre",
    "run_extract",
    "run_links_test",
    "run_emit",
]
