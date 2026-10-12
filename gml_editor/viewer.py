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
small heights are visible. x is scaled by cos(latitude) at the actor level
(v0.5) so east-west proportions are correct while mesh coordinates stay lon/lat.

Per-feature cell-id mapping is attached to every mesh (``feature_index`` cell
data) so v0.2 can resolve a clicked cell back to its feature.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

import numpy as np
import pyvista as pv
import vtk

from .editing import EditSession
from .model import (_POLYGON_TYPES, Feature, Scene, _feature_height_metres,
                    scene_max_height_metres)
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

# Neutral fill shown where a GeoTIFF does not cover the terrain.
_NEUTRAL_RGB = (58, 62, 68)
_NO_TEXTURE_TERRAIN = "#6b7a5e"

# Direction arrow.
_ARROW_COLOR = "#e23b3b"
_ARROW_OPACITY = 0.5
# Opaque triangle at the arrow tip, as fractions of the arrow length.
_ARROW_HEAD_LENGTH = 0.06
_ARROW_HEAD_HALF_WIDTH = 0.025


def arrow_direction(az_deg: float, el_deg: float) -> np.ndarray:
    """Unit vector toward the source defined by azimuth (from True North,
    clockwise) and elevation (above the horizon), in (east, north, up)."""
    az = math.radians(az_deg)
    el = math.radians(el_deg)
    return np.array([
        math.sin(az) * math.cos(el),   # east  (x)
        math.cos(az) * math.cos(el),   # north (y)
        math.sin(el),                  # up    (z)
    ], dtype=np.float64)

# Approximate length of one degree of latitude, in metres.
_METRES_PER_DEGREE = 111_320.0

def _metres_per_horizontal_unit(crs) -> float:
    """Metres represented by one unit of the x/y coordinates (degrees vs metres)."""
    if crs is None:
        return _METRES_PER_DEGREE  # our GML sample is lon/lat degrees
    c = str(crs).upper()
    if any(tag in c for tag in ("4326", "4269", "CRS84", "WGS84", "WGS 84")):
        return _METRES_PER_DEGREE
    return 1.0


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

    z_factor = (vexag / _metres_per_horizontal_unit(scene.working_crs)) if vexag and vexag > 0 else 0.0

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
    mpu = _metres_per_horizontal_unit(scene.working_crs)
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


def _build_texture(geoimage, pad_px: int = 2):
    """Return ``(pv.Texture, (west, east, south, north))`` for a GeoImage.

    The image is padded with a neutral border so terrain outside the imagery's
    footprint samples a neutral colour rather than stretched edge pixels (the
    partial-overlap case). Texture coordinates are later clamped to [0, 1], so
    anything beyond the padded extent also resolves to the neutral border.
    """
    rgb = geoimage.rgb
    h, w = rgb.shape[:2]
    padded = np.empty((h + 2 * pad_px, w + 2 * pad_px, 3), dtype=np.uint8)
    padded[:] = _NEUTRAL_RGB
    padded[pad_px:pad_px + h, pad_px:pad_px + w] = rgb
    west = geoimage.west - pad_px * geoimage.dx
    north = geoimage.north + pad_px * geoimage.dy
    east = geoimage.east + pad_px * geoimage.dx
    south = geoimage.south - pad_px * geoimage.dy
    # VTK maps texture coordinate v=1 to array row 0, and our v = (lat-south)/
    # (north-south) sends north -> v=1. Image row 0 is already the north edge,
    # so no vertical flip is needed for north to land on row 0.
    tex = pv.Texture(np.ascontiguousarray(padded))
    # Mipmapping + interpolation keep imagery smooth when zoomed out / sharp when
    # zoomed in (v0.5 performance/quality).
    try:
        tex.mipmap = True
        tex.interpolate = True
    except Exception:
        pass
    return tex, (west, east, south, north)


def _texture_coords(points: np.ndarray, extent) -> np.ndarray:
    """Per-point (u, v) from lon/lat into a (west, east, south, north) box, clamped."""
    west, east, south, north = extent
    u = (points[:, 0] - west) / (east - west)
    v = (points[:, 1] - south) / (north - south)
    uv = np.column_stack([u, v])
    return np.clip(uv, 0.0, 1.0)


def _flat_plane(extent, z: float = 0.0) -> "pv.StructuredGrid":
    """A flat quad covering (west, east, south, north) at height ``z``."""
    west, east, south, north = extent
    xs = np.array([west, east], dtype=np.float64)
    ys = np.array([south, north], dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)
    return pv.StructuredGrid(X, Y, np.full_like(X, z))


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
        geoimage=None,
        texture_on: bool = True,
        arrow_az=None,
        arrow_el=None,
        plotter=None,
    ):
        self.scene = scene
        self.vexag = vexag
        self.off_screen = off_screen
        self.terrain = terrain
        self.geoimage = geoimage
        self.session = EditSession(scene)
        self._arrow_az = arrow_az
        self._arrow_el = arrow_el
        self._arrow_tip = None
        self._arrow_len = 0.0
        # Called with (lon, lat) whenever the arrow tip moves (e.g. a GUI panel
        # updates its fields).
        self.on_arrow_moved = None
        # Called when the user presses 'q' (lets a host window close itself; the
        # standalone plotter already quits on 'q' via VTK's default binding).
        self.on_quit = None

        if not self.session.features:
            raise ValueError("Scene has no features to edit")

        self._mpu = _metres_per_horizontal_unit(scene.working_crs)
        self._z_factor = (vexag / self._mpu) if (vexag and vexag > 0) else 0.0

        # Longitude-aspect correction (v0.5): one degree of longitude is shorter
        # than one of latitude by cos(latitude). Scaling x by that factor (as an
        # actor transform, so mesh coordinates stay true lon/lat) gives correct
        # east-west proportions. The same factor is applied to picking.
        if terrain is not None:
            lat0 = 0.5 * (terrain.grid.lat0 + terrain.grid.lat1)
        else:
            b = scene.bounds()
            lat0 = 0.5 * (b[2] + b[3]) if b is not None else 0.0
        self._kx = math.cos(math.radians(lat0)) or 1.0

        # Use an externally supplied plotter (e.g. a pyvistaqt QtInteractor
        # embedded in a window) when given, otherwise create our own.
        title = window_title or f"GML Editor — {scene.source_path}"
        self._owns_plotter = plotter is None
        self.plotter = plotter if plotter is not None else pv.Plotter(off_screen=off_screen, title=title)
        self.plotter.set_background(_BACKGROUND)
        self._orient_axes_ned()

        # Build the static ground surface once: the DTED terrain if present,
        # else a flat plane only when there is imagery to drape on it.
        self._ground_mesh = None
        self._texture = None
        self._has_elevation = False
        self._textured = bool(geoimage is not None and texture_on)
        if terrain is not None:
            self._ground_mesh = terrain.build_mesh()
            self._has_elevation = True
        elif geoimage is not None:
            self._ground_mesh = _flat_plane(geoimage.extent, z=0.0)
        if geoimage is not None and self._ground_mesh is not None:
            self._texture, tex_extent = _build_texture(geoimage)
            self._ground_mesh.active_texture_coordinates = _texture_coords(
                self._ground_mesh.points, tex_extent)
        self._add_ground_actor()

        self._line_mesh = None
        self._building_mesh = None
        self._line_actor = None
        self._building_actor = None

        self._rebuild_meshes()
        if arrow_az is not None and arrow_el is not None:
            self._init_arrow()
        has_relief = bool(
            terrain is not None
            or (self._z_factor > 0 and scene_max_height_metres(scene, self.session.features) > 0)
        )
        _configure_camera(self.plotter, has_relief)

        if not off_screen:
            self._wire_events()

    def _orient_axes_ned(self) -> None:
        """Add a right-handed NED orientation gizmo.

        The data is ENU (x=East, y=North, z=Up). A right-handed NED gizmo labels
        the arrows N, E, D pointing North (+y), East (+x), Down (-z); mapping the
        axes actor's local x,y,z arrows there is a proper rotation (det +1), so
        N x E = D as the right-hand rule requires.
        """
        try:
            axes = pv.create_axes_marker(
                xlabel="N", ylabel="E", zlabel="D", label_color=_AXES_LABEL_COLOR,
            )
            m = vtk.vtkMatrix4x4()  # identity
            m.SetElement(0, 0, 0.0); m.SetElement(0, 1, 1.0)   # N -> +y, E -> +x
            m.SetElement(1, 0, 1.0); m.SetElement(1, 1, 0.0)
            m.SetElement(2, 2, -1.0)                            # D -> -z (down)
            tr = vtk.vtkTransform()
            tr.SetMatrix(m)
            axes.SetUserTransform(tr)
            self.plotter.add_orientation_widget(axes, interactive=False)
        except Exception:  # pragma: no cover - older pyvista/vtk
            self.plotter.add_axes(color=_AXES_LABEL_COLOR,
                                  xlabel="N", ylabel="E", zlabel="D")

    def _add_mesh(self, mesh, **kwargs):
        """add_mesh, then apply the longitude-aspect scale to the actor.

        Never resets the camera: the view is fitted once at startup and left
        alone, so edits/toggles that re-add actors don't disturb it.
        """
        kwargs.setdefault("reset_camera", False)
        actor = self.plotter.add_mesh(mesh, **kwargs)
        try:
            actor.scale = (self._kx, 1.0, 1.0)
        except Exception:  # pragma: no cover - older pyvista
            actor.SetScale(self._kx, 1.0, 1.0)
        return actor

    # -- ground surface (terrain / textured plane) -------------------------

    def _add_ground_actor(self) -> None:
        """(Re)add the ground actor, textured or plain per ``self._textured``.

        The ground is pickable so a double-click can resolve the point on it (for
        moving the direction arrow); feature selection ignores it by actor identity.
        """
        self._ground_actor = None
        if self._ground_mesh is None:
            return
        self.plotter.remove_actor("gml_terrain")
        if self._textured and self._texture is not None:
            self._ground_actor = self._add_mesh(
                self._ground_mesh, texture=self._texture, name="gml_terrain",
                pickable=True, lighting=True,
            )
        elif self._has_elevation:
            self._ground_actor = self._add_mesh(
                self._ground_mesh, scalars="elevation_m", cmap="gist_earth",
                show_scalar_bar=False, name="gml_terrain", pickable=True,
                lighting=True,
            )
        else:
            self._ground_actor = self._add_mesh(
                self._ground_mesh, color=_NO_TEXTURE_TERRAIN, name="gml_terrain",
                pickable=True, lighting=True,
            )

    # -- direction arrow ---------------------------------------------------

    def _scene_extent(self):
        """(west, east, south, north) in lon/lat of the (cropped) scene."""
        if self.terrain is not None:
            g = self.terrain.grid
            return (g.lon0, g.lon1, g.lat0, g.lat1)
        if self.geoimage is not None:
            return self.geoimage.extent
        b = self.scene.bounds()
        return (b[0], b[1], b[2], b[3]) if b is not None else (0.0, 1.0, 0.0, 1.0)

    def _ground_z_display(self, lon, lat) -> float:
        """Display-space z of the ground at lon/lat (terrain height, else 0)."""
        if self.terrain is not None:
            return float(self.terrain.elevation_display(lon, lat))
        return 0.0

    def _arrow_length(self) -> float:
        """Arrow length from the (aspect-corrected, cropped) scene dimensions."""
        w, e, s, n = self._scene_extent()
        return 0.5 * math.hypot((e - w) * self._kx, n - s)

    def _ground_center(self):
        w, e, s, n = self._scene_extent()
        clon, clat = 0.5 * (w + e), 0.5 * (s + n)
        return clon, clat

    def _init_arrow(self) -> None:
        """Place the arrow tip at the middle of the ground; length from the extent."""
        self.set_arrow()

    def set_arrow(self, az=None, el=None, lon=None, lat=None) -> None:
        """Create/update the arrow. Missing angles default (az=0, el=45); missing
        endpoint keeps the current tip, or the ground middle if there is none."""
        if az is not None:
            self._arrow_az = az
        if el is not None:
            self._arrow_el = el
        if self._arrow_az is None:
            self._arrow_az = 0.0
        if self._arrow_el is None:
            self._arrow_el = 45.0
        if not self._arrow_len:
            self._arrow_len = self._arrow_length()
        if lon is not None and lat is not None:
            self._arrow_tip = np.array([lon * self._kx, lat, self._ground_z_display(lon, lat)])
        elif self._arrow_tip is None:
            clon, clat = self._ground_center()
            self._arrow_tip = np.array([clon * self._kx, clat, self._ground_z_display(clon, clat)])
        self._draw_arrow()
        self._render()

    def arrow_state(self):
        """Current ``(az, el, lon, lat)`` of the arrow, or None if no arrow."""
        if self._arrow_tip is None:
            return None
        return {
            "az": self._arrow_az,
            "el": self._arrow_el,
            "lon": float(self._arrow_tip[0] / self._kx),
            "lat": float(self._arrow_tip[1]),
        }

    def _draw_arrow(self) -> None:
        """(Re)draw the red arrow pointing to ``self._arrow_tip`` from (az, el)."""
        if self._arrow_tip is None:
            return
        u = arrow_direction(self._arrow_az, self._arrow_el)
        tail = self._arrow_tip + u * self._arrow_len   # up toward the source
        direction = self._arrow_tip - tail             # points down to the ground
        self.plotter.remove_actor("direction_arrow")
        self.plotter.remove_actor("direction_arrow_head")
        arrow = pv.Arrow(
            start=tail, direction=direction, scale=float(np.linalg.norm(direction)),
            tip_length=0.02, tip_radius=0.005, shaft_radius=0.002,
        )
        # Built directly in world space, so it is NOT aspect-scaled like the
        # others. reset_camera=False so moving the arrow doesn't jump the view.
        self.plotter.add_mesh(arrow, color=_ARROW_COLOR, opacity=_ARROW_OPACITY,
                              name="direction_arrow",
                              pickable=False, lighting=False, reset_camera=False)

        # Flat triangle with its apex on the tip, lying in the arrow's vertical
        # plane (spanned by the arrow and the up axis) so it reads as a head.
        d = direction / np.linalg.norm(direction)
        az = math.radians(self._arrow_az)
        normal = np.array([math.cos(az), -math.sin(az), 0.0])  # horizontal, off-plane
        side = np.cross(d, normal)
        base = self._arrow_tip - d * (self._arrow_len * _ARROW_HEAD_LENGTH)
        half = side * (self._arrow_len * _ARROW_HEAD_HALF_WIDTH)
        head = pv.PolyData(np.array([self._arrow_tip, base + half, base - half]),
                           faces=np.array([3, 0, 1, 2]))
        self.plotter.add_mesh(head, color=_ARROW_COLOR, name="direction_arrow_head",
                              pickable=False, lighting=False, reset_camera=False)

    def _ray_plane(self, x, y, z0):
        """World point where the pick ray through display (x, y) meets plane z=z0."""
        ren = self.plotter.renderer
        eye = np.array(ren.GetActiveCamera().GetPosition(), dtype=np.float64)
        ren.SetDisplayPoint(float(x), float(y), 0.0)
        ren.DisplayToWorld()
        w = ren.GetWorldPoint()
        near = np.array(w[:3], dtype=np.float64) / (w[3] if w[3] != 0 else 1.0)
        d = near - eye
        if abs(d[2]) < 1e-12:
            return self._arrow_tip
        t = (z0 - eye[2]) / d[2]
        return eye + t * d

    def _ground_pick(self, x, y):
        """World point on the ground under display (x, y) (cell pick, else ray/plane)."""
        if self._ground_actor is not None:
            picker = vtk.vtkCellPicker()
            picker.SetTolerance(0.005)
            picker.PickFromListOn()
            picker.GetPickList().RemoveAllItems()
            picker.AddPickList(self._ground_actor)
            picker.Pick(float(x), float(y), 0.0, self.plotter.renderer)
            if picker.GetCellId() >= 0:
                return np.array(picker.GetPickPosition(), dtype=np.float64)
        z0 = float(self._arrow_tip[2]) if self._arrow_tip is not None else 0.0
        return self._ray_plane(x, y, z0)

    def move_arrow_to_display(self, x, y) -> None:
        """Translate the arrow so its tip is the ground point under (x, y)."""
        if self._arrow_tip is None:
            return
        pt = self._ground_pick(x, y)
        if pt is None:
            return
        self._arrow_tip = np.asarray(pt, dtype=np.float64)
        self._draw_arrow()
        lon, lat = float(self._arrow_tip[0] / self._kx), float(self._arrow_tip[1])
        log.info("Arrow tip -> lon %.5f, lat %.5f", lon, lat)
        if self.on_arrow_moved is not None:
            self.on_arrow_moved(lon, lat)
        self._render()

    def toggle_texture(self) -> None:
        """Show/hide the GeoTIFF imagery on the ground surface."""
        if self._texture is None:
            return
        self._textured = not self._textured
        self._add_ground_actor()
        log.info("Texture %s", "on" if self._textured else "off")
        self._render()

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
            self._line_actor = self._add_mesh(
                self._line_mesh, color=_LINE_COLOR, line_width=_LINE_WIDTH,
                name="gml_lines", pickable=True,
            )
        if self._building_mesh is not None:
            self._building_actor = self._add_mesh(
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
                self._add_mesh(
                    mesh, color=_HL_BUILDING_COLOR, show_edges=True,
                    edge_color=_HL_LINE_COLOR, name="gml_hl_bldg", pickable=False,
                )
        else:
            mesh, _ = build_line_mesh(self.scene, self.vexag, features=[feature], terrain=self.terrain)
            if mesh is not None:
                self._add_mesh(
                    mesh, color=_HL_LINE_COLOR, line_width=_HL_LINE_WIDTH,
                    name="gml_hl_line", pickable=False,
                )

    def _render(self) -> None:
        if not self.off_screen:
            self.plotter.render()

    # -- picking -----------------------------------------------------------

    def _world_to_display(self, pts: np.ndarray) -> np.ndarray:
        # Actors are scaled by kx in x, so a mesh vertex at lon is at world x =
        # lon * kx. Apply the same here so picking matches the rendered geometry.
        ren = self.plotter.renderer
        out = np.empty((len(pts), 2), dtype=np.float64)
        for i, p in enumerate(pts):
            ren.SetWorldPoint(float(p[0]) * self._kx, float(p[1]), float(p[2]), 1.0)
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
        # Works for both pv.Plotter and pyvistaqt.QtInteractor.
        rw = getattr(self.plotter, "render_window", None)
        interactor = rw.GetInteractor() if rw is not None else None
        if interactor is None:
            iren = getattr(self.plotter, "iren", None)
            interactor = getattr(iren, "interactor", None) if iren is not None else None
        if interactor is None:
            return

        def on_left_press(obj, _event):
            px, py = interactor.GetEventPosition()
            # A double-click (RepeatCount > 0) translates the direction arrow;
            # a single click selects a feature.
            if interactor.GetRepeatCount() and self._arrow_tip is not None:
                self.move_arrow_to_display(px, py)
            else:
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
            elif sym == "t":
                self.toggle_texture()
            elif sym == "q" and self.on_quit is not None:
                self.on_quit()

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
    geoimage=None,
    texture_on: bool = True,
    arrow_az=None,
    arrow_el=None,
):
    """Open the interactive editor on ``scene``.

    When ``terrain`` is given, the GML is draped onto it; when ``geoimage`` is
    given, it is draped as a texture over the terrain (or a flat plane). When
    ``arrow_az``/``arrow_el`` are given, a red direction arrow is drawn to the
    middle of the ground (double-click moves its tip). With ``off_screen=True``
    the view is built but not shown. Returns the :class:`pyvista.Plotter`; the
    :class:`GmlEditorView` is reachable via ``plotter._gml_view``.
    """
    view = GmlEditorView(scene, vexag=vexag, off_screen=off_screen,
                         window_title=window_title, terrain=terrain,
                         geoimage=geoimage, texture_on=texture_on,
                         arrow_az=arrow_az, arrow_el=arrow_el)
    # Stash so --screenshot / tests can reach edit methods if needed.
    view.plotter._gml_view = view
    if not off_screen:
        view.show()
    return view.plotter
