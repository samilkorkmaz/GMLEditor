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

import logging
from typing import List, Optional

import numpy as np
import pyvista as pv
import vtk

from .editing import EditSession
from .model import Feature, Scene
from .terrain import densify

log = logging.getLogger("gml_editor.viewer")

# Rendering constants.
_LINE_COLOR = "#4da3ff"
_LINE_WIDTH = 2
_BUILDING_COLOR = "#c98a5e"
_BUILDING_EDGE = "#f0e0d0"
_BACKGROUND = "#101418"
_AXES_LABEL_COLOR = "#f0f0f0"

# Selection highlight.
_HL_LINE_COLOR = "#ffd24d"
_HL_LINE_WIDTH = 5
_HL_BUILDING_COLOR = "#ffd24d"
_PICK_THRESHOLD_PX = 12.0

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


def scene_max_height_metres(scene: Scene, features=None) -> float:
    """Largest polygon height in metres among ``features`` (default: scene's)."""
    feats = scene.features if features is None else features
    h = 0.0
    for f in feats:
        if f.geom_type in _POLYGON_TYPES:
            h = max(h, _feature_height_metres(f))
    return h


def _displayed_line_parts(feats, z_factor: float, terrain=None):
    """Yield ``(feature_index, (M,3) display points)`` for each line part.

    This is the single source of truth for where a line is *drawn*: flat/scaled
    z when there is no terrain, or densified + draped onto the surface when there
    is. Both :func:`build_line_mesh` and the viewer's screen-space picker use it,
    so the picked geometry always matches the rendered geometry.
    """
    for f_index, feature in enumerate(feats):
        if feature.geom_type in _POLYGON_TYPES:
            continue
        for part in feature.parts:
            if len(part) < 2:
                continue
            if terrain is None:
                block = part.astype(np.float64, copy=True)
                block[:, 2] = block[:, 2] * z_factor  # scale any line z; 0 -> flat
            else:
                block = densify(part, terrain.cell_deg)
                block[:, 2] = (terrain.elevation_display(block[:, 0], block[:, 1])
                               + terrain.line_offset_display)
            yield f_index, block


def build_line_mesh(scene: Scene, vexag: float = 1.0, features=None, terrain=None):
    """Combine every *line* feature's polylines into one :class:`pyvista.PolyData`.

    ``features`` defaults to ``scene.features`` but may be the live, edited list
    so the mesh can be rebuilt after deletes/undo. When ``terrain`` is given,
    lines are densified and draped onto the surface. ``feature_index`` cell data
    indexes into whichever list is passed. Returns ``(mesh, feature_ids)``
    parallel to the mesh cells, or ``(None, [])`` if there are no line features.
    """
    feats = scene.features if features is None else features
    point_blocks: List[np.ndarray] = []
    lines: List[int] = []
    feature_ids: List[int] = []
    offset = 0

    z_factor = (vexag / _metres_per_horizontal_unit(scene.crs)) if vexag and vexag > 0 else 0.0

    for f_index, block in _displayed_line_parts(feats, z_factor, terrain):
        n = len(block)
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


def _extrude_ring(ring_xyz: np.ndarray, height: float, base_z: float = 0.0) -> Optional["pv.PolyData"]:
    """Build a capped prism from a footprint ring extruded ``base_z`` -> ``base_z+height``.

    ``ring_xyz`` is an (N, 3) closed ring (first vertex repeated at the end).
    ``base_z`` sets the ground plane (terrain height when draping). Returns a flat
    filled polygon when ``height <= 0``, or None if degenerate.
    """
    pts2d = ring_xyz[:, :2]
    if len(pts2d) >= 2 and np.allclose(pts2d[0], pts2d[-1]):
        pts2d = pts2d[:-1]  # VTK polygons must not repeat the closing vertex
    m = len(pts2d)
    if m < 3:
        return None

    base = np.column_stack([pts2d, np.full(m, base_z)]).astype(np.float64)
    faces = np.hstack([[m], np.arange(m)]).astype(np.int64)
    poly = pv.PolyData(base, faces=faces)
    if height and height > 0:
        return poly.extrude((0.0, 0.0, float(height)), capping=True)
    return poly


def build_building_mesh(scene: Scene, vexag: float = 1.0, features=None, terrain=None):
    """Extrude polygon features into one combined solid mesh.

    ``features`` defaults to ``scene.features``. When ``terrain`` is given, each
    building's base is set to the terrain height at its footprint centroid so it
    sits on the surface. ``feature_index`` cell data indexes into whichever list
    is passed. Returns ``(mesh, None)``, or ``(None, None)`` if no polygons.
    """
    feats = scene.features if features is None else features
    mpu = _metres_per_horizontal_unit(scene.crs)
    blocks = []
    for f_index, feature in enumerate(feats):
        if feature.geom_type not in _POLYGON_TYPES:
            continue
        height_m = _feature_height_metres(feature)
        height = (height_m / mpu * vexag) if (vexag and vexag > 0) else 0.0
        for ring in feature.parts:
            base_z = 0.0
            if terrain is not None:
                cen = ring[:, :2].mean(axis=0)
                base_z = float(terrain.elevation_display(cen[0], cen[1]))
            prism = _extrude_ring(ring, height, base_z=base_z)
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


def _point_segment_distance(p, a, b) -> float:
    """2D distance from point ``p`` to segment ``a``-``b`` (all (x, y))."""
    p = np.asarray(p, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    ab = b - a
    denom = float(ab @ ab)
    if denom == 0.0:
        return float(np.hypot(*(p - a)))
    t = float((p - a) @ ab) / denom
    t = max(0.0, min(1.0, t))
    proj = a + t * ab
    return float(np.hypot(*(p - proj)))


class GmlEditorView:
    """Interactive 3D editor: select, delete, undo/redo, export (v0.2).

    All edit operations are plain methods so they can be driven both from GUI
    events (wired in :meth:`_wire_events`) and directly from tests. The meshes
    are rebuilt from the live edited feature list after every mutation; the
    camera is fitted once at startup and left alone so the view stays put.
    """

    def __init__(
        self,
        scene: Scene,
        vexag: float = 1.0,
        off_screen: bool = False,
        window_title: str = None,
        terrain=None,
    ):
        self.scene = scene
        self.vexag = vexag
        self.off_screen = off_screen
        self.terrain = terrain
        self.session = EditSession(scene)

        if not self.session.features:
            raise ValueError("Scene has no features to edit")

        self._mpu = _metres_per_horizontal_unit(scene.crs)
        self._z_factor = (vexag / self._mpu) if (vexag and vexag > 0) else 0.0

        title = window_title or f"GML Editor v0.3 — {scene.source_path}"
        self.plotter = pv.Plotter(off_screen=off_screen, title=title)
        self.plotter.set_background(_BACKGROUND)
        self.plotter.add_axes(color=_AXES_LABEL_COLOR)

        # Terrain is static; add it once beneath the (editable) GML actors.
        if terrain is not None:
            self.plotter.add_mesh(
                terrain.build_mesh(), scalars="elevation_m", cmap="gist_earth",
                show_scalar_bar=False, name="gml_terrain", pickable=False,
                lighting=True,
            )

        self._line_mesh = None
        self._building_mesh = None
        self._line_actor = None
        self._building_actor = None

        self._rebuild_meshes()
        has_relief = bool(
            terrain is not None
            or (self._z_factor > 0 and scene_max_height_metres(scene, self.session.features) > 0)
        )
        _configure_camera(self.plotter, has_relief)

        if not off_screen:
            self._wire_events()

    # -- mesh construction -------------------------------------------------

    def _rebuild_meshes(self) -> None:
        """Rebuild line and building actors from the current feature list."""
        for name in ("gml_lines", "gml_buildings"):
            self.plotter.remove_actor(name)
        feats = self.session.features

        self._line_mesh, _ = build_line_mesh(self.scene, self.vexag, features=feats, terrain=self.terrain)
        self._building_mesh, _ = build_building_mesh(self.scene, self.vexag, features=feats, terrain=self.terrain)
        self._line_actor = None
        self._building_actor = None

        if self._line_mesh is not None:
            self._line_actor = self.plotter.add_mesh(
                self._line_mesh, color=_LINE_COLOR, line_width=_LINE_WIDTH,
                name="gml_lines", pickable=True,
            )
        if self._building_mesh is not None:
            self._building_actor = self.plotter.add_mesh(
                self._building_mesh, color=_BUILDING_COLOR, show_edges=True,
                edge_color=_BUILDING_EDGE, name="gml_buildings", pickable=True,
            )
        self._update_highlight()

    def _update_highlight(self) -> None:
        """Redraw the highlight overlay for the current selection."""
        for name in ("gml_hl_line", "gml_hl_bldg"):
            self.plotter.remove_actor(name)
        feature = self.session.selected
        if feature is None:
            return
        if feature.geom_type in _POLYGON_TYPES:
            mesh, _ = build_building_mesh(self.scene, self.vexag, features=[feature], terrain=self.terrain)
            if mesh is not None:
                self.plotter.add_mesh(
                    mesh, color=_HL_BUILDING_COLOR, show_edges=True,
                    edge_color=_HL_LINE_COLOR, name="gml_hl_bldg", pickable=False,
                )
        else:
            mesh, _ = build_line_mesh(self.scene, self.vexag, features=[feature], terrain=self.terrain)
            if mesh is not None:
                self.plotter.add_mesh(
                    mesh, color=_HL_LINE_COLOR, line_width=_HL_LINE_WIDTH,
                    name="gml_hl_line", pickable=False,
                )

    def _render(self) -> None:
        if not self.off_screen:
            self.plotter.render()

    # -- picking -----------------------------------------------------------

    def _world_to_display(self, pts: np.ndarray) -> np.ndarray:
        ren = self.plotter.renderer
        out = np.empty((len(pts), 2), dtype=np.float64)
        for i, p in enumerate(pts):
            ren.SetWorldPoint(float(p[0]), float(p[1]), float(p[2]), 1.0)
            ren.WorldToDisplay()
            d = ren.GetDisplayPoint()
            out[i, 0] = d[0]
            out[i, 1] = d[1]
        return out

    def _cell_pick(self, x: float, y: float):
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        picker.Pick(x, y, 0, self.plotter.renderer)
        return picker.GetActor(), picker.GetCellId()

    def _building_at(self, x: float, y: float) -> Optional[Feature]:
        if self._building_actor is None:
            return None
        actor, cid = self._cell_pick(x, y)
        if actor is not self._building_actor or cid is None or cid < 0:
            return None
        idx_arr = self._building_mesh.cell_data.get("feature_index")
        if idx_arr is None or cid >= len(idx_arr):
            return None
        fidx = int(idx_arr[cid])
        if 0 <= fidx < len(self.session.features):
            return self.session.features[fidx]
        return None

    def _nearest_line(self, x: float, y: float,
                      threshold: float = _PICK_THRESHOLD_PX) -> Optional[Feature]:
        best = None
        best_d = threshold
        click = (x, y)
        feats = self.session.features
        # Use the exact draped/densified points that were drawn, so picking lines
        # up with the rendered geometry even at angled views over terrain.
        for f_index, block in _displayed_line_parts(feats, self._z_factor, self.terrain):
            disp = self._world_to_display(block)
            for i in range(len(disp) - 1):
                d = _point_segment_distance(click, disp[i], disp[i + 1])
                if d < best_d:
                    best_d = d
                    best = feats[f_index]
        return best

    def pick_at_display(self, x: float, y: float) -> Optional[Feature]:
        """Resolve a click at display coords to a feature (buildings first)."""
        feature = self._building_at(x, y)
        if feature is None:
            feature = self._nearest_line(x, y)
        return feature

    # -- edit operations (also the GUI callbacks) --------------------------

    def select_feature(self, feature: Optional[Feature]) -> None:
        self.session.select(feature)
        if feature is not None:
            log.info("Selected %s (%s, %s)", feature.fid, feature.layer, feature.geom_type)
        self._update_highlight()
        self._render()

    def select_at_display(self, x: float, y: float) -> None:
        self.select_feature(self.pick_at_display(x, y))

    def delete_selected(self) -> None:
        feature = self.session.delete_selected()
        if feature is None:
            return
        log.info("Deleted %s  (%d remaining, %d undoable)",
                 feature.fid, len(self.session.features), self.session.deleted_count)
        self._rebuild_meshes()
        self._render()

    def undo(self) -> None:
        feature = self.session.undo()
        if feature is None:
            log.info("Nothing to undo")
            return
        log.info("Restored %s  (%d features)", feature.fid, len(self.session.features))
        self._rebuild_meshes()
        self._render()

    def redo(self) -> None:
        feature = self.session.redo()
        if feature is None:
            log.info("Nothing to redo")
            return
        log.info("Re-deleted %s", feature.fid)
        self._rebuild_meshes()
        self._render()

    def export(self, out_path: str = None) -> Optional[str]:
        from .export import ExportError, export_gml
        try:
            path = export_gml(self.scene, self.session.features, out_path)
        except ExportError as exc:
            log.error("Export failed: %s", exc)
            return None
        log.info("Exported %d features to %s", len(self.session.features), path)
        return path

    # -- event wiring ------------------------------------------------------

    def _wire_events(self) -> None:
        iren = getattr(self.plotter, "iren", None)
        interactor = getattr(iren, "interactor", None) if iren is not None else None
        if interactor is None:
            return

        def on_left_press(obj, _event):
            px, py = interactor.GetEventPosition()
            self.select_at_display(px, py)

        def on_key(obj, _event):
            sym = (interactor.GetKeySym() or "").lower()
            ctrl = bool(interactor.GetControlKey())
            if sym in ("delete", "backspace"):
                self.delete_selected()
            elif ctrl and sym == "z":
                self.undo()
            elif ctrl and sym == "y":
                self.redo()
            elif ctrl and sym == "s":
                self.export()

        interactor.AddObserver("LeftButtonPressEvent", on_left_press, 1.0)
        interactor.AddObserver("KeyPressEvent", on_key, 1.0)

    def show(self) -> None:
        self.plotter.show()


def render_scene(
    scene: Scene,
    off_screen: bool = False,
    window_title: str = None,
    vexag: float = 1.0,
    terrain=None,
):
    """Open the interactive editor on ``scene``.

    When ``terrain`` is given, the GML is draped onto it. With
    ``off_screen=True`` the view is built but not shown (used for tests and
    ``--screenshot``). Returns the :class:`pyvista.Plotter` so callers can take a
    screenshot; the :class:`GmlEditorView` is reachable via ``plotter._gml_view``.
    """
    view = GmlEditorView(scene, vexag=vexag, off_screen=off_screen,
                         window_title=window_title, terrain=terrain)
    # Stash so --screenshot / tests can reach edit methods if needed.
    view.plotter._gml_view = view
    if not off_screen:
        view.show()
    return view.plotter
