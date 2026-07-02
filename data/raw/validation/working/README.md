# `data/raw/validation/working/` — Validation Set #9 Working Directory

This is where the machine-generated pre-labelling assets for validation set #9
land. The three deliverables are:

| File | Purpose |
|---|---|
| `annotation_workbook.xlsx` | 200-row workbook with 4 pre-filled columns (编号 / 百度直达链接 / 片区 / 抽样方式 / 备注 / 经纬度) + 8 blank annotator columns with dropdown validation. |
| `validation_pins.kml` | Google-Earth import: 5 folders × 40 pins, polygon outline + representative point per pin. |
| `README_working.md` | This run's parameters: five window bounds, seed, dedup tallies, generation date. Becomes the paper's Methods §sampling-frame text. |

Alongside these, the extract stage writes:

| File | Purpose |
|---|---|
| `candidates_internal.parquet` | Internal 200-row table linking 编号 ↔ source-row / geometry / height / area / district / final window bounds. **Not for the annotator** — carries `height`, which the blind-test rule (CLAUDE.md project spec §5) forbids in the deliverables. |
| `checkpoint1/*.png` | Five footprint previews (one per window) used for owner sign-off on the sampling frame before the deliverables are built. |
| `checkpoint1/sampling_summary.json` | Structured summary of each window's centre, halfwidth (initial + final), candidates kept / dropped, cluster-size histogram. |

## How to reproduce

```bash
# Stage 1 — extract + 5 preview PNGs; owner reviews checkpoint 1.
python scripts/build_validation_workbook.py extract \
    --shp <path to 2026 Building.shp>

# Stage 2 — 3 baidu link sanity test; owner clicks each.
python scripts/build_validation_workbook.py links-test          # WGS84
python scripts/build_validation_workbook.py links-test --bd09ll # fallback path

# Stage 3 — build the three deliverables.
python scripts/build_validation_workbook.py emit \
    --shp <path to 2026 Building.shp>
```

Seed is hard-coded to `42` (per task spec); pass `--seed N` to override for
sensitivity studies. Metric CRS for windowing is **EPSG:4547** (CGCS2000
3-degree Gauss-Krüger zone 40).

## Ignore rules

Everything in this directory except this README, the workbook, the KML, and
`README_working.md` is gitignored via the top-level `/data/raw/*` rule.
`candidates_internal.parquet` and the checkpoint1 previews stay in the
working tree but never reach the repo (per §5 blind-test rule + SOP).
