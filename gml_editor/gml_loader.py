"""Load line geometry from a GML file.

v0.1 parses GML directly with the standard-library XML parser. GML is XML, so
this fully covers the v0.1 goal (read and display lines) without a native GDAL
build. The public entry point is :func:`load_gml`, which returns a
:class:`~gml_editor.model.Scene`. Keeping this behind a single function means a
later GDAL/OGR-backed loader can replace it without touching the viewer or the
data model.

Supported geometry (everything is flattened to z = 0 polylines):
  * LineString                      -> one part
  * MultiLineString                 -> one part per member LineString
  * Polygon / LinearRing boundaries -> one closed part per ring

Both GML2 (``gml:coordinates``) and GML3 (``gml:posList`` / ``gml:pos``)
coordinate encodings are handled.
"""

from __future__ import annotations

import io
import os
import xml.etree.ElementTree as ET
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from .model import Feature, Scene


class GMLError(Exception):
    """Raised for a missing, unreadable, malformed, or empty GML source."""


# Local tag names we treat as geometry containers.
_GEOM_TAGS = {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}
_GEOM_WRAPPER_TAGS = {"geometryProperty", "geometry"} | _GEOM_TAGS

# Elements that wrap feature members.
_MEMBER_TAGS = {"featureMember", "featureMembers"}


def iter_feature_elements(root: ET.Element) -> Iterator[Tuple[ET.Element, ET.Element]]:
    """Yield ``(member_element, feature_element)`` in document order.

    This is the single traversal shared by loading (to assign each feature a
    stable ``order``) and export (to map a surviving feature back to its element
    in the tree). Both must enumerate features identically, so both go through
    here.
    """
    for member in root.iter():
        if _localname(member.tag) in _MEMBER_TAGS:
            for feature_elem in list(member):
                yield member, feature_elem


def _parse_namespaces(data: bytes) -> Dict[str, str]:
    """Extract the prefix -> URI namespace map declared in the document."""
    nsmap: Dict[str, str] = {}
    try:
        for event, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
            nsmap.setdefault(prefix, uri)
    except ET.ParseError:
        pass
    return nsmap


def _localname(tag: str) -> str:
    """Strip any ``{namespace}`` prefix from an ElementTree tag."""
    if tag and tag[0] == "{":
        return tag.split("}", 1)[1]
    return tag


def _parse_coordinates(text: str, cs: str = ",", ts: str = " ") -> List[List[float]]:
    """Parse a GML2 ``gml:coordinates`` text block into [[x, y, (z)], ...]."""
    tuples = []
    # Tuples are separated by the tuple separator (default whitespace); split on
    # any whitespace when ts is the default so newlines/tabs are tolerated.
    raw_tuples = text.split() if ts.isspace() else [t for t in text.split(ts) if t.strip()]
    for raw in raw_tuples:
        parts = [c for c in raw.split(cs) if c != ""]
        if len(parts) < 2:
            continue
        tuples.append([float(c) for c in parts])
    return tuples


def _parse_poslist(text: str, dim: int = 2) -> List[List[float]]:
    """Parse a GML3 ``gml:posList`` (flat whitespace-separated numbers)."""
    nums = [float(n) for n in text.split()]
    if dim < 2:
        dim = 2
    coords = []
    for i in range(0, len(nums) - dim + 1, dim):
        coords.append(nums[i:i + dim])
    return coords


def _to_xyz(coords: List[List[float]]) -> np.ndarray:
    """Turn a list of 2D/3D coordinates into an (N, 3) array with z defaulting to 0."""
    if not coords:
        return np.empty((0, 3), dtype=np.float64)
    arr = np.zeros((len(coords), 3), dtype=np.float64)
    for i, c in enumerate(coords):
        arr[i, 0] = c[0]
        arr[i, 1] = c[1]
        if len(c) >= 3:
            arr[i, 2] = c[2]
    return arr


def _coords_from_geom(elem: ET.Element) -> List[np.ndarray]:
    """Return the vertex arrays contained directly beneath a coordinate carrier.

    ``elem`` is a LineString or LinearRing (or anything that directly holds a
    ``gml:coordinates`` / ``gml:posList`` / ``gml:pos`` sequence).
    """
    parts: List[np.ndarray] = []
    for child in elem.iter():
        name = _localname(child.tag)
        if name == "coordinates" and child.text:
            cs = child.get("cs", ",")
            ts = child.get("ts", " ")
            parts.append(_to_xyz(_parse_coordinates(child.text, cs, ts)))
        elif name == "posList" and child.text:
            dim = int(child.get("srsDimension", "2") or "2")
            parts.append(_to_xyz(_parse_poslist(child.text, dim)))
    # gml:pos elements are single points; collect them into one part if no
    # coordinates/posList was found (rare for lines, but harmless).
    if not parts:
        pos_pts = []
        for child in elem.iter():
            if _localname(child.tag) == "pos" and child.text:
                nums = [float(n) for n in child.text.split()]
                if len(nums) >= 2:
                    pos_pts.append(nums)
        if pos_pts:
            parts.append(_to_xyz(pos_pts))
    return [p for p in parts if len(p) > 0]


def _extract_parts(geom: ET.Element) -> (str, List[np.ndarray]):
    """Extract (geom_type, parts) from a geometry element."""
    gtype = _localname(geom.tag)
    parts: List[np.ndarray] = []

    if gtype == "LineString":
        parts.extend(_coords_from_geom(geom))

    elif gtype == "MultiLineString":
        for ls in geom.iter():
            if _localname(ls.tag) == "LineString":
                parts.extend(_coords_from_geom(ls))

    elif gtype in ("Polygon", "MultiPolygon"):
        # Each LinearRing (outer or inner boundary) becomes one closed part.
        for ring in geom.iter():
            if _localname(ring.tag) == "LinearRing":
                parts.extend(_coords_from_geom(ring))

    return gtype, [p for p in parts if len(p) >= 2]


def _find_srs(root: ET.Element) -> Optional[str]:
    """Find the first srsName declared on any geometry element."""
    for elem in root.iter():
        if _localname(elem.tag) in _GEOM_TAGS:
            srs = elem.get("srsName")
            if srs:
                return srs
    return None


def _feature_attributes(feature_elem: ET.Element) -> dict:
    """Collect scalar attributes (non-geometry leaf text) of a feature element."""
    attrs = {}
    for child in feature_elem:
        name = _localname(child.tag)
        if name in _GEOM_WRAPPER_TAGS:
            continue
        # Only take simple leaf elements with text.
        if len(list(child)) == 0 and child.text and child.text.strip():
            attrs[name] = child.text.strip()
    # Carry the GML fid/id attribute too, if present.
    for key, val in feature_elem.attrib.items():
        if _localname(key) in ("fid", "id"):
            attrs.setdefault(_localname(key), val)
    return attrs


def _reproject_features(features, crs, src_crs=None, swap_xy=None):
    """Reproject every feature's vertices to WGS84 lon/lat in place.

    CRS and axis order come from the GML ``srsName`` (``crs``), overridable by
    ``src_crs`` (e.g. "EPSG:32636") and ``swap_xy`` (force/suppress lat,lon swap).
    Returns the EPSG that was applied. Raises :class:`GMLError` on unsupported CRS.
    """
    from .reproject import CRSError, parse_srs, to_wgs84_lonlat

    epsg, swap = parse_srs(src_crs if src_crs is not None else crs)
    if swap_xy is not None:
        swap = swap_xy
    try:
        for feature in features:
            for part in feature.parts:
                if swap:
                    part[:, [0, 1]] = part[:, [1, 0]]
                lon, lat = to_wgs84_lonlat(part[:, 0], part[:, 1], epsg)
                part[:, 0] = lon
                part[:, 1] = lat
    except CRSError as exc:
        raise GMLError(str(exc)) from exc
    return epsg


def load_gml(path: str, src_crs=None, swap_xy=None) -> Scene:
    """Read all line geometry from a GML file into a :class:`Scene`.

    Geometry is reprojected to WGS84 lon/lat (the working CRS). ``src_crs`` and
    ``swap_xy`` override the CRS / axis order detected from the GML ``srsName``.
    The original XML tree is kept untouched, so export round-trips source
    coordinates regardless of reprojection.

    Raises :class:`GMLError` on a missing / unreadable / malformed file, one that
    contains no usable line geometry, or an unsupported CRS.
    """
    if not os.path.exists(path):
        raise GMLError(f"File not found: {path}")
    if not os.path.isfile(path):
        raise GMLError(f"Not a file: {path}")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise GMLError(f"Could not read {path}: {exc}") from exc
    if not data.strip():
        raise GMLError(f"File is empty: {path}")

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise GMLError(f"Not valid XML/GML ({path}): {exc}") from exc

    crs = _find_srs(root)
    nsmap = _parse_namespaces(data)

    features: List[Feature] = []

    # `order` is the document index of every feature element (whether or not it
    # yields drawable geometry) so it stays aligned with the same traversal used
    # at export time.
    for order, (_member, feature_elem) in enumerate(iter_feature_elements(root)):
        geom = None
        for cand in feature_elem.iter():
            if _localname(cand.tag) in _GEOM_TAGS:
                geom = cand
                break
        if geom is None:
            continue  # feature with no (supported) geometry

        gtype, parts = _extract_parts(geom)
        if not parts:
            continue  # geometry present but no line vertices

        attrs = _feature_attributes(feature_elem)
        fid = attrs.get("fid") or attrs.get("id")
        if not fid:
            fid = f"{_localname(feature_elem.tag)}.{order}"

        features.append(
            Feature(
                fid=str(fid),
                layer=_localname(feature_elem.tag),
                geom_type=gtype,
                parts=parts,
                attributes=attrs,
                source_ref=feature_elem,
                order=order,
            )
        )

    if not features:
        raise GMLError(
            f"No line, multi-line, or polygon-boundary geometry found in {path}"
        )

    applied_epsg = _reproject_features(features, crs, src_crs=src_crs, swap_xy=swap_xy)

    return Scene(
        features=features,
        crs=crs,
        source_path=os.path.abspath(path),
        tree_root=root,
        nsmap=nsmap,
        working_crs="EPSG:4326",
        source_epsg=applied_epsg,
    )
