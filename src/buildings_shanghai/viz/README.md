# Module E (viz) — Figure Generation

Produces all figures used in the paper.

## Inputs

- All previous-module outputs under `outputs/`.

## Outputs

| Path | Description |
|---|---|
| `outputs/figures/fig_archetype_map.png` | City-wide archetype map |
| `outputs/figures/fig_calibration_scatter.png` | Simulated vs. measured monthly EUI |
| `outputs/figures/fig_enduse_breakdown.png` | Per-archetype end-use stacked bars |
| `outputs/figures/fig_embodied_violins.png` | Embodied carbon distributions |
| `outputs/figures/fig_monthly_heatmap.png` | 12-archetype x 12-month EUI heatmap |

## Style conventions

- Use `matplotlib` + `seaborn`; only fall back to `plotly` for interactive HTML.
- Color palette: consistent across all figures, defined in `viz/style.py`.
- Save at 300 dpi PNG and SVG for vector figures.
