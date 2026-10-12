"""Internal data model.

The model is intentionally independent of both the loader (how the data was
read) and the viewer (how it is drawn). v0.2 will add a selection state and an
undo stack here; keeping a stable per-feature id and a reference back to the
original source element now makes that future work straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

# Attribute keys consulted for a height when the geometry itself has no z.
_HEIGHT_KEYS = ("height_m", "height", "HEIGHT", "z", "elevation", "YUKSEKLIK")

_POLYGON_TYPES = ("Polygon", "MultiPolygon")


@dataclass
class Feature:
    """A single map feature rendered as one or more polylines.

    A LineString has one part; a MultiLineString or a Polygon (whose rings are
    drawn as closed lines) has several. Each part is an ``(N, 3)`` float64 array
    of ``(x, y, z)`` points holding the source coordinates as read; z is 0 when
    the source is 2D. v0.1 renders every part in a flat plane (z forced to 0 at
    draw time) regardless of the stored z.
    """

    fid: str                       # stable id, unique within a Scene
    layer: str                     # originating layer / feature type, e.g. "roads"
    geom_type: str                 # "LineString" | "MultiLineString" | "Polygon"
    parts: List[np.ndarray]        # list of (N, 3) float64 vertex arrays
    attributes: Dict[str, str] = field(default_factory=dict)
    # Reference to the original parsed source (the XML element for the v0.1
    # loader). v0.2 export uses this to round-trip the feature unchanged.
    source_ref: Any = None
    # Document order among all feature elements (0-based). This is the stable
    # key v0.2 export uses to map a surviving feature back to its element in the
    # original tree; it is independent of the feature's position in any live,
    # edited list.
    order: int = -1

    @property
    def vertex_count(self) -> int:
        return int(sum(len(p) for p in self.parts))


@dataclass
class Scene:
    """All features loaded from one source, plus shared metadata."""

    features: List[Feature]
    crs: Optional[str]             # e.g. "EPSG:4326"; None if the source declared none
    source_path: str
    # Original parsed XML root and its prefix->URI namespace map, kept so v0.2
    # export can round-trip the document (schema, attributes, CRS) minus any
    # deleted features. None for scenes not built from a GML file.
    tree_root: Any = None
    nsmap: Dict[str, str] = field(default_factory=dict)
    # v0.5: the CRS features were reprojected into for display, and the source
    # EPSG they came from (None if undeclared / assumed lon/lat).
    working_crs: str = "EPSG:4326"
    source_epsg: Optional[int] = None

    @property
    def feature_count(self) -> int:
        return len(self.features)

    @property
    def vertex_count(self) -> int:
        return int(sum(f.vertex_count for f in self.features))

    def layer_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self.features:
            counts[f.layer] = counts.get(f.layer, 0) + 1
        return counts

    def bounds(self) -> Optional[tuple]:
        """Return (xmin, xmax, ymin, ymax, zmin, zmax) over all vertices.

        Returns None when there are no vertices to bound.
        """
        mins = None
        maxs = None
        for f in self.features:
            for part in f.parts:
                if len(part) == 0:
                    continue
                pmin = part.min(axis=0)
                pmax = part.max(axis=0)
                mins = pmin if mins is None else np.minimum(mins, pmin)
                maxs = pmax if maxs is None else np.maximum(maxs, pmax)
        if mins is None:
            return None
        return (mins[0], maxs[0], mins[1], maxs[1], mins[2], maxs[2])


def _feature_height_metres(feature: Feature) -> float:
    """Height of a feature in metres: prefer the geometry's z, else an attribute."""
    zmax = 0.0
    for part in feature.parts:
        if len(part):
            zmax = max(zmax, float(np.nanmax(part[:, 2])))
    if zmax > 0:
        return zmax
    for key in _HEIGHT_KEYS:
        val = feature.attributes.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.0


def scene_max_height_metres(scene: Scene, features=None) -> float:
    """Largest polygon height in metres among ``features`` (default: scene's)."""
    feats = scene.features if features is None else features
    h = 0.0
    for f in feats:
        if f.geom_type in _POLYGON_TYPES:
            h = max(h, _feature_height_metres(f))
    return h
