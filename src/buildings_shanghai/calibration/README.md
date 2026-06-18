# Module E (calibration) — Dual-Track NMBE Calibration

Corresponds to the **Calibration** section of the paper.

## Inputs

- `outputs/module_c_monthly_eui.csv` — simulated monthly EUI
- `config/calibration_targets.yaml` — Wang et al. 144-point matrix + residential

## Outputs

| Path | Format | Description |
|---|---|---|
| `outputs/module_e_calibration.json` | JSON | Per-archetype NMBE, pass / fail flag |
| `outputs/module_e_calibration_log.txt` | text | Iteration trace, adjustments applied |

## Metric

NMBE (Normalized Mean Bias Error), in percent:

    NMBE = sum(simulated - measured) / (n * mean(measured)) * 100

## Rules

- |NMBE| <= 10 % per public archetype (monthly).
- |NMBE| <= 20 % per residential archetype (annual).
- If a threshold is missed, surface the gap and log the offending archetype.
  Do NOT silently relax the threshold.
