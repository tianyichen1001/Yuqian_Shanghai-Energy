"""Emit ``validation_pins.kml`` for Google Earth review.

Structure:

    <kml>
      <Document>
        <name>Validation Set #9</name>
        <Folder><name>陆家嘴</name>
          <Placemark>
            <name>V001</name>
            <description><![CDATA[<a href="...baidu marker link...">百度定位</a>]]></description>
            <MultiGeometry>
              <Point><coordinates>lon,lat,0</coordinates></Point>
              <Polygon>...footprint outer ring...</Polygon>
            </MultiGeometry>
          </Placemark>
          ...
        </Folder>
        ...
      </Document>
    </kml>

Same blind-test rule as the workbook: names carry only the V-id and the
Baidu link. No height, no floor guess, no archetype.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon


_BLIND_FORBIDDEN_COLS = frozenset(
    {"height", "height_m", "estimated_floor", "storeys_pred",
     "archetype", "archetype_pred", "predicted_type"}
)


class BlindTestViolationError(RuntimeError):
    """Same rule as :mod:`workbook` — no machine hints in the KML either."""


def _check_blind_test(gdf: gpd.GeoDataFrame) -> None:
    leaked = _BLIND_FORBIDDEN_COLS & set(gdf.columns)
    if leaked:
        raise BlindTestViolationError(
            f"KML input carries forbidden columns: {sorted(leaked)}"
        )


def _polygon_coord_string(poly: Polygon) -> str:
    return " ".join(f"{lon:.7f},{lat:.7f},0" for lon, lat in poly.exterior.coords)


def _placemark_geometry(geom) -> str:
    """Return KML for a Point + Polygon MultiGeometry.

    Uses the geometry's representative_point for the pin. If ``geom`` is
    a MultiPolygon, only the largest ring is drawn (KML rendering in
    Google Earth prefers one ring per polygon block; drawing each part
    would clutter the folder for the annotator).
    """
    if isinstance(geom, MultiPolygon):
        largest = max(geom.geoms, key=lambda p: p.area)
    else:
        largest = geom
    rep = largest.representative_point()
    coords = _polygon_coord_string(largest)
    return (
        "<MultiGeometry>"
        f"<Point><coordinates>{rep.x:.7f},{rep.y:.7f},0</coordinates></Point>"
        "<Polygon><outerBoundaryIs><LinearRing>"
        f"<coordinates>{coords}</coordinates>"
        "</LinearRing></outerBoundaryIs></Polygon>"
        "</MultiGeometry>"
    )


def _placemark(vid: str, baidu_url: str, geom) -> str:
    desc_html = f'<![CDATA[<a href="{escape(baidu_url, quote=True)}">百度定位</a>]]>'
    return (
        "<Placemark>"
        f"<name>{xml_escape(vid)}</name>"
        f"<description>{desc_html}</description>"
        f"{_placemark_geometry(geom)}"
        "</Placemark>"
    )


def build_kml(picked_wgs84: gpd.GeoDataFrame, out_path: Path) -> Path:
    """Write ``validation_pins.kml`` at ``out_path``.

    Required columns on ``picked_wgs84``:
        编号, 片区, 百度直达链接, geometry (polygon in EPSG:4326).
    """
    _check_blind_test(picked_wgs84)

    required = {"编号", "片区", "百度直达链接", "geometry"}
    missing = required - set(picked_wgs84.columns)
    if missing:
        raise ValueError(f"KML input missing columns: {sorted(missing)}")

    if picked_wgs84.crs and str(picked_wgs84.crs).upper() not in ("EPSG:4326",):
        raise ValueError(f"KML input must be EPSG:4326, got {picked_wgs84.crs!s}")

    doc_parts: list[str] = []
    doc_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    doc_parts.append('<kml xmlns="http://www.opengis.net/kml/2.2">')
    doc_parts.append("<Document>")
    doc_parts.append("<name>Validation Set #9 — Shanghai UBEM</name>")

    # One folder per 片区, preserving the input order.
    for district in picked_wgs84["片区"].drop_duplicates().tolist():
        block = picked_wgs84[picked_wgs84["片区"] == district]
        doc_parts.append(f"<Folder><name>{xml_escape(str(district))}</name>")
        for _, row in block.iterrows():
            doc_parts.append(_placemark(row["编号"], row["百度直达链接"], row["geometry"]))
        doc_parts.append("</Folder>")

    doc_parts.append("</Document></kml>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(doc_parts), encoding="utf-8")
    return out_path


__all__ = ["BlindTestViolationError", "build_kml"]
