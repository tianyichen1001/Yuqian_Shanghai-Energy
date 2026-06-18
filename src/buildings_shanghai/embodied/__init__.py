"""Module D — embodied-carbon Monte Carlo.

Samples per-material probability density functions (concrete, steel, glass,
aluminum, brick) from the One Click LCA China EPD database and produces
A1-A5 lifecycle embodied-carbon distributions per archetype. 5,000 samples
per archetype.

See ``src/buildings_shanghai/embodied/README.md``.
"""

from __future__ import annotations


def run(n_samples: int = 5000) -> None:
    """Run Module D end-to-end.

    TODO: implement. Should produce
    ``outputs/module_d_embodied_distributions.parquet``.
    """
    raise NotImplementedError("Module D not yet implemented.")


__all__ = ["run"]
