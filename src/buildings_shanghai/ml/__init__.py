"""Module B — ML archetype inference.

Trains a Random Forest classifier on the high-confidence seeded labels from
Module A using shape features (footprint area, height, levels, perimeter,
aspect ratio, compactness, convexity). Uses SMOTE for class imbalance.

See ``src/buildings_shanghai/ml/README.md``.
"""

from __future__ import annotations


def run(area: str = "full_city") -> None:
    """Run Module B end-to-end for the given study area.

    TODO: implement. Should produce
    ``outputs/module_b_predictions.parquet``.
    """
    raise NotImplementedError("Module B not yet implemented.")


__all__ = ["run"]
