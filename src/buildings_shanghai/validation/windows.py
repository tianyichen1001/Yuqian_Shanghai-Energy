"""Five WGS84 windows around the study areas of validation set #9.

Half-widths are in *metres*, measured on a local metric CRS
(EPSG:4547, CGCS2000 3-degree Gauss-Krüger zone 40, matches Shanghai).
The value stored here is the *initial* half-width — the sampler may
expand it in +300 m steps up to 3000 m if the window does not yield
40 candidates after dedup.

Never edit these coordinates without owner sign-off; they are the
paper's sampling frame and are also referenced verbatim in
``data/raw/validation/working/README_working.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Window:
    """A rectangular sampling window centred on ``(lat, lon)`` in WGS84.

    ``halfwidth_m`` is applied symmetrically in both x and y after
    projection to EPSG:4547, so the sampling box is a metric square,
    not a lat/lon rectangle (which would be skewed at Shanghai's
    latitude).
    """

    key: str
    label_cn: str
    lat: float
    lon: float
    halfwidth_m: int
    quota: int = 40


WINDOWS: Final[tuple[Window, ...]] = (
    Window("lujiazui", "陆家嘴", 31.238, 121.501, 800),
    Window("xujiahui", "徐家汇", 31.194, 121.436, 800),
    Window("xinzhuang", "莘庄", 31.116, 121.385, 800),
    Window("zhangjiang", "张江", 31.203, 121.604, 900),
    Window("lingang", "临港", 30.912, 121.918, 1500),
)

#: Contiguous 40-per-window numbering scheme.
#: V001–V040 lujiazui, V041–V080 xujiahui, V081–V120 xinzhuang,
#: V121–V160 zhangjiang, V161–V200 lingang.
WINDOW_ORDER: Final[tuple[str, ...]] = tuple(w.key for w in WINDOWS)


def id_range(window_key: str) -> tuple[int, int]:
    """1-based inclusive V-id range for the given window key."""
    idx = WINDOW_ORDER.index(window_key)
    return idx * 40 + 1, (idx + 1) * 40


def format_id(n: int) -> str:
    """Format a 1-based counter as ``V001`` – ``V200``."""
    if not 1 <= n <= 200:
        raise ValueError(f"validation id out of range: {n}")
    return f"V{n:03d}"


__all__ = ["Window", "WINDOWS", "WINDOW_ORDER", "id_range", "format_id"]
