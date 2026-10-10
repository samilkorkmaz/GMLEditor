"""Terrain surface and draping helpers (v0.3).

Wraps a :class:`~gml_editor.dted.DtedGrid` with the display-space scaling used by
the rest of the app (metres -> horizontal units * vertical exaggeration) and
builds the renderable terrain mesh. The viewer uses :meth:`Terrain.elevation_display`
to drape GML geometry onto the surface.

``metres_per_unit`` is passed in by the caller (computed from the working CRS)
to avoid a circular import with the viewer.
"""

from __future__ import annotations

import math

import numpy as np
import pyvista as pv

from .dted import DtedGrid


class Terrain:
    def __init__(self, grid: DtedGrid, metres_per_unit: float, vexag: float,
                 line_offset_m: float = 2.0, max_dim: int = 400):
        self.grid = grid
        self.mpu = metres_per_unit
        self.vexag = vexag
        # metres -> display units (same formula as building heights in viewer.py)
        self.zscale = (vexag / metres_per_unit) if (vexag and vexag > 0) else 0.0
        # small lift so draped lines don't z-fight with the surface
        self.line_offset_display = line_offset_m * self.zscale
        self.max_dim = max_dim
        # densify GML segments to roughly one terrain cell so lines follow relief
        self.cell_deg = min(grid.dlon, grid.dlat)

    def elevation_display(self, lon, lat) -> np.ndarray:
        """Display-space z of the terrain surface at lon/lat (no line offset)."""
        return self.grid.sample(lon, lat) * self.zscale

    def build_mesh(self) -> "pv.StructuredGrid":
        """Build the terrain surface mesh, downsampled so large tiles stay responsive.

        A full DTED Level 2 tile is 3601x3601 (~13M points); striding to at most
        ``max_dim`` per axis keeps the mesh light enough for interactive use while
        preserving the overall shape. Carries an ``elevation_m`` scalar for coloring.
        """
        g = self.grid
        step_c = max(1, math.ceil(g.ncol / self.max_dim))
        step_r = max(1, math.ceil(g.nrow / self.max_dim))
        cols = np.arange(0, g.ncol, step_c)
        rows = np.arange(0, g.nrow, step_r)
        lon = g.lon0 + cols * g.dlon
        lat = g.lat0 + rows * g.dlat
        LON, LAT = np.meshgrid(lon, lat)
        Z = g.elev[np.ix_(rows, cols)]
        mesh = pv.StructuredGrid(LON, LAT, Z * self.zscale)
        # Attach elevation by sampling at the realized points so the scalar order
        # matches regardless of how StructuredGrid lays out its points.
        pts = mesh.points
        mesh["elevation_m"] = g.sample(pts[:, 0], pts[:, 1])
        return mesh


def densify(part: np.ndarray, max_seg_deg: float) -> np.ndarray:
    """Subdivide a polyline so no segment is longer than ``max_seg_deg`` (in x/y).

    Returns an ``(M, 3)`` array; the z column is interpolated but is overwritten
    by draping, so only x/y matter here.
    """
    if len(part) < 2 or max_seg_deg <= 0:
        return part.astype(np.float64, copy=True)
    out = [part[0].astype(np.float64)]
    for i in range(len(part) - 1):
        a = part[i].astype(np.float64)
        b = part[i + 1].astype(np.float64)
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(math.ceil(dist / max_seg_deg)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * (k / n))
    return np.asarray(out, dtype=np.float64)
