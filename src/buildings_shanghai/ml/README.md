# Module B — ML Archetype Inference

Corresponds to the **ML Archetype Inference** section of the paper.

## Inputs

- `outputs/geojson/module_a_master.geojson` — seeded high-confidence labels
- `config/archetypes.yaml` — canonical archetype list

## Outputs

| Path | Format | Description |
|---|---|---|
| `outputs/module_b_predictions.parquet` | Parquet | building_id, predicted_archetype, probability vector |
| `outputs/module_b_model.joblib` | joblib | Trained Random Forest pipeline |
| `outputs/module_b_metrics.json` | JSON | Per-class precision / recall / F1, confusion matrix |

## Features (shape only — no semantic leakage)

| Feature | Description |
|---|---|
| `footprint_area_m2` | Projected (UTM 51N) polygon area |
| `height_m` | From Taobao / CNBH |
| `levels` | Floor count |
| `perimeter_m` | Projected perimeter |
| `aspect_ratio` | Minimum-bounding-rectangle long / short side |
| `compactness` | 4 * pi * area / perimeter^2 |
| `convexity` | area / convex_hull_area |

## Key sub-modules (to be implemented)

| File | Responsibility |
|---|---|
| `features.py` | Compute shape features from geometries |
| `train.py` | SMOTE + Random Forest pipeline, hyperparameter search via Optuna |
| `predict.py` | Apply trained model to unlabeled buildings |
| `evaluate.py` | Cross-validation, confusion matrix, calibration plots |
