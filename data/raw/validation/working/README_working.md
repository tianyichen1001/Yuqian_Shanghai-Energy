# Validation Set #9 — Working Workbook

Working directory for validation-set annotation. Owner does the labelling
in `annotation_workbook.xlsx`; the three files here are the *machine-
generated* pre-labelling assets. Do not overwrite them mid-labelling.

## Sampling frame

| window | centre (WGS84 lat, lon) | initial halfwidth | final halfwidth | V-id range |
|---|---|---|---|---|
| lujiazui (陆家嘴) | 31.2380, 121.5010 | 800 m | 800 m | V001–V040 |
| xujiahui (徐家汇) | 31.1940, 121.4360 | 800 m | 800 m | V041–V080 |
| xinzhuang (莘庄) | 31.1160, 121.3850 | 800 m | 800 m | V081–V120 |
| zhangjiang (张江) | 31.2030, 121.6040 | 900 m | 900 m | V121–V160 |
| lingang (临港) | 30.9120, 121.9180 | 1500 m | 1500 m | V161–V200 |

## Rules

- Metric CRS for windowing: **EPSG:4547** (CGCS2000 3-degree GK zone 40).
- Area floor: **100 m²**. No height/floor filter (calibration must see the
  natural distribution).
- Same-model dedup: `|Δarea|/max ≤ 5%` AND `|Δheight| ≤ 0.5 m` AND
  `distance ≤ 250 m`. Keep at most 3 buildings per cluster (lowest input
  row index).
- Halfwidth expansion: `+300 m` steps up to 3000 m; stop-and-report if
  the window can't yield 40 candidates at 3000 m.
- Random seed: **42** (`numpy.random.default_rng`).
- Baidu marker links use `coord_type=wgs84`.

## Deduplication tally

| window | duplicates dropped | cluster size histogram |
|---|---|---|
| lujiazui | 25 | 1: 308, 2: 21, 3: 4, 4-6: 7, 7+: 1 |
| xujiahui | 40 | 1: 655, 2: 69, 3: 21, 4-6: 8, 7+: 4 |
| xinzhuang | 50 | 1: 224, 2: 34, 3: 16, 4-6: 10, 7+: 5 |
| zhangjiang | 87 | 1: 386, 2: 46, 3: 16, 4-6: 19, 7+: 8 |
| lingang | 333 | 1: 352, 2: 64, 3: 28, 4-6: 17, 7+: 20 |

## Blind-test rule

The workbook and KML **must not** carry `height`, `estimated_floor`,
or any archetype prediction. The full internal candidates table lives
in `candidates_internal.parquet` alongside these files; it is *not*
to be shared with the annotator until labelling is complete.

## Generation date

2026-07-02
