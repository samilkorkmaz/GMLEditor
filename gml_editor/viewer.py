"""3D rendering of a :class:`~gml_editor.model.Scene` with PyVista/VTK.

Display-only. Line features (roads, paths) are combined into a single line mesh
for fast rendering; polygon features that carry a height are extruded into 3D
solids (a box for a rectangular footprint). The camera auto-fits the data and
the default VTK trackball interactor provides pan, zoom (wheel), and rotate.

Vertical scale
--------------
Source geometry may carry a z value (e.g. building height in metres) while x/y
are in a different unit (lon/lat in degrees). Drawing metres directly against
degrees makes a 40 m building ~40 "degrees" tall and destroys the view, so
heights are converted into horizontal units and multiplied by a vertical
exaggeration factor:

    display_height = height_metres / metres_per_horizontal_unit * vexag

``vexag = 0`` flattens everything (buildings collapse to their footprint);
``vexag = 1`` is true geographic scale; ``vexag > 1`` exaggerates relief so
small heights are visible. Real CRS reprojection is deferred to v0.5; this is a
lightweight metres->degrees approximation.

Per-feature cell-id mapping is attached to every mesh (``feature_index`` cell
data) so v0.2 can resolve a clicked cell back to its feature.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pyvista as pv

from .model import Feature, Scene

# Rendering constants.
_LINE_COLOR = "#4da3ff"
_LINE_WIDTH = 2
_BUILDING_COLOR = "#c98a5e"
_BUILDING_EDGE = "#f0e0d0"
_BACKGROUND = "#101418"
_AXES_LABEL_COLOR = "#f0f0f0"

# Approximate length of one degree of latitude, in metres.
_METRES_PER_DEGREE = 111_320.0

# Attribute keys consulted for a height when the geometry itself has no z.
_HEIGHT_KEYS = ("height_m", "height", "HEIGHT", "z", "elevation")

_POLYGON_TYPES = ("Polygon", "MultiPolygon")


def _metres_per_horizontal_unit(crs) -> float:
    """Metres represented by one unit of the x/y coordinates (degrees vs metres)."""
    if crs is None:
        return _METRES_PER_DEGREE  # our GML sample is lon/lat degrees
    c = str(crs).upper()
    if any(tag in c for tag in ("4326", "4269", "CRS84", "WGS84", "WGS 84")):
        return _METRES_PER_DEGREE
    return 1.0


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


def scene_max_height_metres(scene: Scene) -> float:
    """Largest polygon height in the scene, in source metres (0 if none)."""
    h = 0.0
    for f in scene.features:
        if f.geom_type in _POLYGON_TYPES:
            h = max(h, _feature_height_metres(f))
    return h


def build_line_mesh(scene: Scene, vexag: float = 1.0):
    """Combine every *line* feature's polylines into one :class:`pyvista.PolyData`.

    Polygon features are handled by :func:`build_building_mesh` instead. Returns
    ``(mesh, feature_ids)`` with ``feature_ids`` parallel to the mesh cells, or
    ``(None, [])`` if there are no line features.
    """
    point_blocks: List[np.ndarray] = []
    lines: List[int] = []
    feature_ids: List[int] = []
    offset = 0

    z_factor = (vexag / _metres_per_horizontal_unit(scene.crs)) if vexag and vexag > 0 else 0.0

    for f_index, feature in enumerate(scene.features):
        if feature.geom_type in _POLYGON_TYPES:
            continue
        for part in feature.parts:
            n = len(part)
            if n < 2:
                continue
            block = part.copy()
            block[:, 2] = block[:, 2] * z_factor  # scale any line z; 0 -> flat
            point_blocks.append(block)
            lines.append(n)
            lines.extend(range(offset, offset + n))
            feature_ids.append(f_index)
            offset += n

    if not point_blocks:
        return None, []

    mesh = pv.PolyData()
    mesh.points = np.vstack(point_blocks)
    mesh.lines = np.asarray(lines, dtype=np.int64)
    mesh.cell_data["feature_index"] = np.asarray(feature_ids, dtype=np.int64)
    return mesh, feature_ids


def _extrude_ring(ring_xyz: np.ndarray, height: float) -> Optional["pv.PolyData"]:
    """Build a capped prism from a footprint ring extruded from z=0 to ``height``.

    ``ring_xyz`` is an (N, 3) closed ring (first vertex repeated at the end).
    Returns a flat filled polygon when ``height <= 0``, or None if degenerate.
    """
    pts2d = ring_xyz[:, :2]
    if len(pts2d) >= 2 and np.allclose(pts2d[0], pts2d[-1]):
        pts2d = pts2d[:-1]  # VTK polygons must not repeat the closing vertex
    m = len(pts2d)
    if m < 3:
        return None

    base = np.column_stack([pts2d, np.zeros(m)]).astype(np.float64)
    faces = np.hstack([[m], np.arange(m)]).astype(np.int64)
    poly = pv.PolyData(base, faces=faces)
    if height and height > 0:
        return poly.extrude((0.0, 0.0, float(height)), capping=True)
    return poly


def build_building_mesh(scene: Scene, vexag: float = 1.0):
    """Extrude polygon features into one combined solid mesh.

    Returns ``(mesh, None)`` where the mesh carries a ``feature_index`` cell
    array, or ``(None, None)`` if there are no polygon features.
    """
    mpu = _metres_per_horizontal_unit(scene.crs)
    blocks = []
    for f_index, feature in enumerate(scene.features):
        if feature.geom_type not in _POLYGON_TYPES:
            continue
        height_m = _feature_height_metres(feature)
        height = (height_m / mpu * vexag) if (vexag and vexag > 0) else 0.0
        for ring in feature.parts:
            prism = _extrude_ring(ring, height)
            if prism is None or prism.n_cells == 0:
                continue
            prism.cell_data["feature_index"] = np.full(prism.n_cells, f_index, dtype=np.int64)
            blocks.append(prism)

    if not blocks:
        return None, None

    combined = blocks[0]
    for blk in blocks[1:]:
        combined = combined.merge(blk)
    return combined, None


def _configure_camera(plotter: "pv.Plotter", has_relief: bool) -> None:
    """Fit the data; tilt to isometric when there is relief, else look straight down."""
    if has_relief:
        plotter.view_isometric()
    else:
        plotter.view_xy()
    plotter.reset_camera()


def render_scene(
    scene: Scene,
    off_screen: bool = False,
    window_title: str = None,
    vexag: float = 1.0,
):
    """Render ``scene`` in an interactive 3D window.

    ``vexag`` sets vertical exaggeration (see module docstring). With
    ``off_screen=True`` the plotter is created but not shown. Returns the
    :class:`pyvista.Plotter`.
    """
    line_mesh, _ = build_line_mesh(scene, vexag=vexag)
    building_mesh, _ = build_building_mesh(scene, vexag=vexag)
    if line_mesh is None and building_mesh is None:
        raise ValueError("Scene has no drawable geometry")

    title = window_title or f"GML Editor v0.1 — {scene.source_path}"
    plotter = pv.Plotter(off_screen=off_screen, title=title)
    plotter.set_background(_BACKGROUND)

    if line_mesh is not None:
        plotter.add_mesh(
            line_mesh,
            color=_LINE_COLOR,
            line_width=_LINE_WIDTH,
            name="gml_lines",
        )
    if building_mesh is not None:
        plotter.add_mesh(
            building_mesh,
            color=_BUILDING_COLOR,
            show_edges=True,
            edge_color=_BUILDING_EDGE,
            name="gml_buildings",
        )

    # Light label text so the X/Y/Z marks are legible on the dark background.
    plotter.add_axes(color=_AXES_LABEL_COLOR)

    has_relief = bool(vexag and vexag > 0 and scene_max_height_metres(scene) > 0)
    _configure_camera(plotter, has_relief)

    if not off_screen:
        plotter.show()
    return plotter
