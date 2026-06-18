"""Module E (calibration half) — dual-track NMBE calibration.

Track 1: public buildings vs. Wang et al. 2026 monthly matrix, |NMBE| <= 10 %.
Track 2: residential vs. Tsinghua / GB/T 51161 annual benchmarks,
|NMBE| <= 20 %.

See ``src/buildings_shanghai/calibration/README.md``.
"""

from __future__ import annotations


def run() -> None:
    """Run dual-track calibration.

    TODO: implement. Should produce ``outputs/module_e_calibration.json``.
    """
    raise NotImplementedError("Module E (calibration) not yet implemented.")


__all__ = ["run"]
