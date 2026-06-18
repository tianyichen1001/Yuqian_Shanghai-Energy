# Module C — EnergyPlus Simulation

Corresponds to the **EnergyPlus Simulation** section of the paper.

## Inputs

- `outputs/module_b_predictions.parquet` — archetype per building
- `config/archetypes.yaml`, `config/standards.yaml` — parameter defaults
- `templates/<archetype>.idf` — per-archetype IDF skeleton
- `weather/CHN_SH_Shanghai*.epw` — weather file (gitignored)

## Outputs

| Path | Format | Description |
|---|---|---|
| `outputs/sim_runs/<archetype>__<height_bin>/` | dir | EnergyPlus run outputs |
| `outputs/module_c_monthly_eui.csv` | CSV | archetype, height_bin, month, total + end-use EUI [kWh/m2] |

## Key sub-modules (to be implemented)

| File | Responsibility |
|---|---|
| `idf_builder.py` | Compose IDF per archetype via eppy / geomeppy |
| `schedules.py` | Inject schedules / internal gains from config |
| `hvac.py` | Inject HVAC templates (VAV, FCU+DOAS, VRF, split AC) |
| `runner.py` | Batch execution via subprocess + multiprocessing pool |
| `parser.py` | Read ESO / SQL outputs; aggregate to monthly EUI |

## Notes

- Pure-Python only — no Rhino, no Grasshopper.
- Each archetype is simulated as a 5-zone ASHRAE shoebox with per-orientation
  fenestration. Height bins are derived from the Taobao height distribution.
- The mixed_use archetype must have its own template — do not reuse `office`.
