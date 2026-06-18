# Module D — Embodied Carbon Monte Carlo

Corresponds to the **Embodied Carbon Monte Carlo** section of the paper.

## Inputs

- `data/raw/epd_oneclick/` — One Click LCA China EPD database extracts
- `data/raw/clcd/` — Chinese Life Cycle Database supplements
- `config/archetypes.yaml` — per-archetype material intensities (kg/m2)

## Outputs

| Path | Format | Description |
|---|---|---|
| `outputs/module_d_samples.parquet` | Parquet | 5,000 samples x archetype x material x stage |
| `outputs/module_d_embodied_distributions.parquet` | Parquet | mean, median, p05, p95 per archetype |

## Materials and lifecycle stages

| Material | Stages |
|---|---|
| Concrete | A1-A3 (product), A4 (transport), A5 (construction) |
| Steel | A1-A3, A4, A5 |
| Glass | A1-A3, A4, A5 |
| Aluminum | A1-A3, A4, A5 |
| Brick | A1-A3, A4, A5 |

## Key sub-modules (to be implemented)

| File | Responsibility |
|---|---|
| `pdfs.py` | Fit per-material PDFs from EPD samples |
| `intensity.py` | Per-archetype material intensity tables |
| `montecarlo.py` | Sample, sum stages, aggregate to per-archetype distribution |
