"""Module C — EnergyPlus simulation.

Generates one IDF template per archetype via ``eppy`` / ``geomeppy`` /
``honeybee-energy``. Batches simulations across (archetype x height-bin) cells
and parses ESO / SQL outputs into monthly EUI plus end-use breakdown.

See ``src/buildings_shanghai/simulation/README.md``.
"""

from __future__ import annotations


def run(area: str = "full_city") -> None:
    """Run Module C end-to-end for the given study area.

    TODO: implement. Should produce
    ``outputs/module_c_monthly_eui.csv`` and end-use breakdown.
    """
    raise NotImplementedError("Module C not yet implemented.")


__all__ = ["run"]
