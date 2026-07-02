"""Validation-set curation (footprint → 200 annotation candidates).

This submodule builds the *working workbook* for validation set #9:
five 800–1500 m half-width windows across Shanghai (Lujiazui, Xujiahui,
Xinzhuang, Zhangjiang, Lingang), 40 buildings per window (200 total),
each pre-linked to a Baidu Maps pin for on-screen human annotation.

Design notes:

* The pipeline is deterministic given ``seed=42`` (all randomness flows
  through a single :class:`numpy.random.Generator`).
* The *output* to the human annotator MUST NOT expose any machine guess:
  no height, no floor estimate, no archetype prediction. That "blind
  test" rule is enforced in :mod:`workbook` and :mod:`kml`.
* ``candidates_internal.parquet`` retains height and source-row indices
  for later audit; it is written next to the deliverables but is *never*
  handed to the annotator.

Entry point: :func:`buildings_shanghai.validation.pipeline.run`.
"""

from __future__ import annotations

from .windows import WINDOWS, Window

__all__ = ["WINDOWS", "Window"]
