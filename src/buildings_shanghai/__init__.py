"""Buildings.Shanghai — Shanghai UBEM pipeline.

This package extends the Buildings.city framework (Lyu et al., Computers,
Environment and Urban Systems, 2026) to a Chinese hot-summer / cold-winter
megacity. It is organized as five sequential modules:

    A. data         — building / POI / land-use acquisition and CRS unification
    B. ml           — Random Forest archetype inference with SMOTE rebalancing
    C. simulation   — per-archetype EnergyPlus IDF generation and execution
    D. embodied     — Monte Carlo embodied-carbon estimation (A1-A5)
    E. calibration  — dual-track NMBE calibration against Wang et al. 2026
    + viz           — figure generation for the paper
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"


def project_root() -> Path:
    """Return the absolute path of the repository root.

    Resolved from this file's location so callers do not need to hardcode
    paths. All `config/`, `data/`, `outputs/` look-ups should go through
    this helper.
    """
    return Path(__file__).resolve().parents[2]


__all__ = ["__version__", "project_root"]
