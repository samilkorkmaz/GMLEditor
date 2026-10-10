"""v0.3 tests: DTED reader, terrain draping, picking over terrain, and that
editing/export still preserve original coordinates.

Run:  python -m tests.test_v03   (from the project root)
"""

import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gml_editor.gml_loader import load_gml  # noqa: E402
from gml_editor.dted import load_dted, write_dted, VOID, DtedError  # noqa: E402
from gml_editor.terrain import Terrain, densify  # noqa: E402

SAMPLE = os.path.join(ROOT, "ankara_sample.gml")

# Synthetic DTED covering the sample extent (lon 32.75..~32.90, lat 39.85..~39.95)
# at 3 arc-second spacing (Level-1-like).
LON0, LAT0 = 32.75, 39.85
ARCSEC = 3.0
NCOL, NROW = 181, 121  # ~0.15 deg x 0.10 deg


def _make_dted(path, with_void=True):
    d = ARCSEC / 3600.0
    cols = np.arange(NCOL)
    rows = np.arange(NROW)
    lon = LON0 + cols * d
    lat = LAT0 + rows * d
    LON, LAT = np.meshgrid(lon, lat)  # (NROW, NCOL)
    # A smooth hill (~850 m base, +500 m peak near the city centre).
    Z = 850.0 + 500.0 * np.exp(-(((LON - 32.84) ** 2 + (LAT - 39.92) ** 2) / 0.0015))
    if with_void:
        Z[10, 20] = VOID
    write_dted(path, Z, LON0, LAT0, ARCSEC, ARCSEC)


def test_dted_roundtrip_and_sample():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "tile.dt1")
        _make_dted(p)
        g = load_dted(p)
        assert (g.nrow, g.ncol) == (NROW, NCOL), (g.nrow, g.ncol)
        assert abs(g.dlon * 3600 - ARCSEC) < 1e-6 and abs(g.dlat * 3600 - ARCSEC) < 1e-6
        assert abs(g.lon0 - LON0) < 1e-9 and abs(g.lat0 - LAT0) < 1e-9
        assert g.void_count == 1
        # Sampling at a grid node returns that node's (rounded) elevation.
        node = float(g.sample(g.lon0 + 50 * g.dlon, g.lat0 + 40 * g.dlat))
        assert np.isclose(node, g.elev[40, 50], atol=1e-3), (node, g.elev[40, 50])
        # Peak region is higher than the edges.
        peak = float(g.sample(32.84, 39.92))
        edge = float(g.sample(g.lon0, g.lat0))
        assert peak > edge + 100, (peak, edge)
    print("test_dted_roundtrip_and_sample: OK  (peak %.0f m, edge %.0f m)" % (peak, edge))


def test_bad_dted_errors():
    with tempfile.NamedTemporaryFile("wb", suffix=".dt1", delete=False) as fh:
        fh.write(b"NOTDTED" + b"\x00" * 100)
        path = fh.name
    try:
        load_dted(path)
    except DtedError as exc:
        print("test_bad_dted_errors: OK  (%s)" % exc)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected DtedError for non-DTED file")


def test_densify_subdivides():
    part = np.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0]])  # 0.1 deg long
    out = densify(part, 0.001)  # -> ~100 segments
    assert len(out) >= 100, len(out)
    # Endpoints preserved.
    assert np.allclose(out[0], part[0]) and np.allclose(out[-1], part[1])
    print("test_densify_subdivides: OK  (%d points)" % len(out))


def test_terrain_draping():
    from gml_editor.viewer import build_line_mesh, build_building_mesh

    scene = load_gml(SAMPLE)
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "tile.dt1")
        _make_dted(p)
        grid = load_dted(p)
        terrain = Terrain(grid, metres_per_unit=111320.0, vexag=50.0)

        # Lines: draped z must match the terrain surface (+ the small offset),
        # not 0, and densification yields more points than raw vertices.
        raw_line_verts = sum(len(part) for f in scene.features
                             if f.geom_type != "Polygon" for part in f.parts)
        lmesh, _ = build_line_mesh(scene, vexag=50.0, terrain=terrain)
        assert lmesh.n_points > raw_line_verts, (lmesh.n_points, raw_line_verts)
        pts = lmesh.points
        expect_z = terrain.elevation_display(pts[:, 0], pts[:, 1]) + terrain.line_offset_display
        assert np.allclose(pts[:, 2], expect_z, atol=1e-9)
        assert pts[:, 2].min() > 0  # sitting on elevated terrain

        # Buildings: base sits on the terrain at the footprint centroid.
        building = next(f for f in scene.features if f.geom_type == "Polygon")
        bmesh, _ = build_building_mesh(scene, vexag=50.0, features=[building], terrain=terrain)
        cen = building.parts[0][:, :2].mean(axis=0)
        base = float(terrain.elevation_display(cen[0], cen[1]))
        assert abs(float(bmesh.points[:, 2].min()) - base) < 1e-6, (bmesh.points[:, 2].min(), base)
        # Terrain mesh builds and carries elevation scalars.
        tmesh = terrain.build_mesh()
        assert tmesh.n_points > 0 and "elevation_m" in tmesh.point_data
    print("test_terrain_draping: OK  (line pts %d > raw %d)" % (lmesh.n_points, raw_line_verts if False else raw_line_verts))


def test_subset_crops_to_box():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "tile.dt1")
        _make_dted(p, with_void=False)
        g = load_dted(p)
        # Crop to a small central box.
        sub = g.subset(32.82, 39.90, 32.85, 39.92, margin_frac=0.0)
        assert sub.ncol < g.ncol and sub.nrow < g.nrow
        # Cropped window still covers the requested box...
        assert sub.lon0 <= 32.82 and sub.lon1 >= 32.85
        assert sub.lat0 <= 39.90 and sub.lat1 >= 39.92
        # ...and samples agree with the full grid inside the box.
        assert np.isclose(sub.sample(32.835, 39.91), g.sample(32.835, 39.91), atol=1e-6)
    print("test_subset_crops_to_box: OK  (%dx%d -> %dx%d)" % (g.nrow, g.ncol, sub.nrow, sub.ncol))


def test_terrain_downsampling():
    # A grid larger than max_dim is strided so the mesh stays light.
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "big.dt2")
        d = 1.0 / 3600.0
        Z = np.full((900, 900), 1000.0)
        write_dted(p, Z, 30.0, 40.0, 1.0, 1.0)
        grid = load_dted(p)
        terrain = Terrain(grid, 111320.0, vexag=1.0, max_dim=300)
        mesh = terrain.build_mesh()
        # 900 -> stride 3 -> 300 per axis -> 90000 points, not 810000.
        assert mesh.n_points <= 300 * 300, mesh.n_points
    print("test_terrain_downsampling: OK  (%d points from 900x900)" % mesh.n_points)


def test_picking_and_export_over_terrain():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import GmlEditorView, _displayed_line_parts, build_building_mesh
    from gml_editor.export import export_gml

    scene = load_gml(SAMPLE)
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "tile.dt1")
        _make_dted(p)
        terrain = Terrain(load_dted(p), 111320.0, vexag=50.0)

        view = GmlEditorView(scene, vexag=50.0, off_screen=True, terrain=terrain)
        view.plotter.show(auto_close=False)

        # Line pick over terrain: midpoint of a road's *drawn* (draped) geometry.
        road = next(f for f in view.session.features if f.geom_type == "LineString")
        road_idx = view.session.features.index(road)
        block = next(b for i, b in _displayed_line_parts(view.session.features,
                     view._z_factor, terrain) if i == road_idx)
        mid = block[len(block) // 2]
        dmid = view._world_to_display(np.array([mid]))[0]
        assert view.pick_at_display(dmid[0], dmid[1]) is road

        # Building pick over terrain: pick at the screen-centroid of the
        # building's actual (draped, extruded) geometry so the click is on-box.
        bld = next(f for f in view.session.features if f.geom_type == "Polygon")
        bmesh_one, _ = build_building_mesh(scene, vexag=50.0, features=[bld], terrain=terrain)
        dc = view._world_to_display(bmesh_one.points).mean(axis=0)
        assert view.pick_at_display(dc[0], dc[1]) is bld

        # Screenshot renders terrain + draped GML.
        shot = os.path.join(tmp, "shot.png")
        view.plotter.screenshot(shot)
        assert os.path.getsize(shot) > 0

        # Edit + export: draping is display-only, so exported coordinates are
        # unchanged from the source.
        view.select_feature(bld)
        view.delete_selected()
        out = os.path.join(tmp, "edited.gml")
        export_gml(scene, view.session.features, out)
        reloaded = load_gml(out)
        assert reloaded.feature_count == scene.feature_count - 1
        road0_before = next(f for f in scene.features if f.fid == "roads.0").parts[0]
        road0_after = next(f for f in reloaded.features if f.fid == "roads.0").parts[0]
        assert np.allclose(road0_before, road0_after)
        view.plotter.close()
    print("test_picking_and_export_over_terrain: OK")


if __name__ == "__main__":
    test_dted_roundtrip_and_sample()
    test_bad_dted_errors()
    test_densify_subdivides()
    test_subset_crops_to_box()
    test_terrain_draping()
    test_terrain_downsampling()
    test_picking_and_export_over_terrain()
    print("\nALL v0.3 TESTS PASSED")
