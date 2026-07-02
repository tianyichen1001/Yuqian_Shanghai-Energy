"""Baidu Maps deep-link generation for the annotation workbook.

The template requested by the owner is::

    https://api.map.baidu.com/marker?location={lat},{lng}&title={V-id}
        &content=UBEM&coord_type=wgs84&output=html&src=ubem.validation

Baidu's public *marker* endpoint accepts ``coord_type=wgs84`` and does
the server-side conversion, so the "happy path" is: emit the WGS84 lat/lon
and let Baidu convert. If that ever stops resolving correctly at the
annotator's screen (verified via the 3-link test in checkpoint 2), the
fallback here re-runs the query with ``coord_type=bd09ll`` and a client-
side WGS84 → GCJ-02 → BD09 conversion.

The GCJ-02 and BD09 formulas below are the published "China datum shift"
polynomials used by every open-source implementation (eviltransform,
coordtransform, gcoord, …). No dependency, so this stays reproducible in
a devcontainer.
"""

from __future__ import annotations

import math
from typing import Literal
from urllib.parse import urlencode


CoordType = Literal["wgs84", "bd09ll"]

_BAIDU_MARKER_URL = "https://api.map.baidu.com/marker"

# China ellipsoid constants used by the GCJ-02 datum shift.
_A = 6378245.0
_EE = 0.00669342162296594323
_PI = math.pi
_X_PI = _PI * 3000.0 / 180.0


def _is_out_of_china(lat: float, lon: float) -> bool:
    """Return ``True`` if a point lies outside the China GCJ-02 region.

    Roughly bounded by (lat 0.83 – 55.83, lon 72.004 – 137.8347). Points
    outside are treated as WGS84-identical to GCJ-02 (the published
    algorithm's convention).
    """
    if lon < 72.004 or lon > 137.8347:
        return True
    if lat < 0.8293 or lat > 55.8271:
        return True
    return False


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320.0 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """WGS84 → GCJ-02 ("Mars coordinates").

    Used by Amap and Tencent Maps. This is *not* Baidu-native; Baidu adds
    one more step (see :func:`gcj02_to_bd09`).
    """
    if _is_out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * _PI
    magic = math.sin(rad_lat)
    magic = 1.0 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrt_magic) * _PI)
    dlon = (dlon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * _PI)
    return lat + dlat, lon + dlon


def gcj02_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    """GCJ-02 → BD09 (Baidu's internal datum)."""
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * _X_PI)
    bd_lon = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return bd_lat, bd_lon


def wgs84_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    """WGS84 → BD09 (used when Baidu's server-side conversion is unreliable)."""
    gcj_lat, gcj_lon = wgs84_to_gcj02(lat, lon)
    return gcj02_to_bd09(gcj_lat, gcj_lon)


def marker_link(
    lat_wgs84: float,
    lon_wgs84: float,
    title: str,
    *,
    coord_type: CoordType = "wgs84",
    content: str = "UBEM",
    src: str = "ubem.validation",
) -> str:
    """Build the Baidu marker URL for one pin.

    When ``coord_type == "wgs84"``, the raw WGS84 lat/lon is passed and
    Baidu converts server-side. When ``coord_type == "bd09ll"``, the
    coordinate is pre-converted to BD09 client-side (workbook checkpoint 2
    fallback path).
    """
    if coord_type == "wgs84":
        lat, lon = lat_wgs84, lon_wgs84
    elif coord_type == "bd09ll":
        lat, lon = wgs84_to_bd09(lat_wgs84, lon_wgs84)
    else:  # pragma: no cover — mypy narrows before reaching here
        raise ValueError(f"unsupported coord_type: {coord_type}")

    query = urlencode(
        {
            "location": f"{lat:.7f},{lon:.7f}",
            "title": title,
            "content": content,
            "coord_type": coord_type,
            "output": "html",
            "src": src,
        }
    )
    return f"{_BAIDU_MARKER_URL}?{query}"


__all__ = [
    "CoordType",
    "wgs84_to_gcj02",
    "gcj02_to_bd09",
    "wgs84_to_bd09",
    "marker_link",
]
