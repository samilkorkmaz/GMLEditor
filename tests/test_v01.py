"""v0.1 smoke tests: loader correctness, error handling, and offscreen render.

Run:  python -m tests.test_v01   (from the project root)
"""

import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gml_editor.gml_loader import GMLError, load_gml  # noqa: E402

SAMPLE = os.path.join(ROOT, "ankara_sample.gml")


def test_loads_sample():
    scene = load_gml(SAMPLE)
    # 8 road features (roads.0..7) + 3 buildings = 11.
    assert scene.feature_count == 11, scene.feature_count
    assert scene.crs == "EPSG:4326", scene.crs
    counts = scene.layer_counts()
    assert counts == {"roads": 8, "buildings": 3}, counts
    # MultiLineString roads.7 has two parts.
    multi = [f for f in scene.features if f.geom_type == "MultiLineString"]
    assert len(multi) == 1 and len(multi[0].parts) == 2
    # Polygons are drawn as one closed ring each.
    polys = [f for f in scene.features if f.geom_type == "Polygon"]
    assert len(polys) == 3
    for p in polys:
        ring = p.parts[0]
        # First and last vertex of a closed ring coincide.
        assert (ring[0] == ring[-1]).all()
    # Attributes carried through.
    road0 = next(f for f in scene.features if f.fid == "roads.0")
    assert road0.attributes.get("name") == "Ataturk Boulevard"
    print("test_loads_sample: OK  (features=%d, vertices=%d)"
          % (scene.feature_count, scene.vertex_count))


def test_missing_file():
    try:
        load_gml(os.path.join(ROOT, "does_not_exist.gml"))
    except GMLError as exc:
        print("test_missing_file: OK  (%s)" % exc)
        return
    raise AssertionError("expected GMLError for missing file")


def test_empty_file():
    with tempfile.NamedTemporaryFile("w", suffix=".gml", delete=False) as fh:
        path = fh.name
    try:
        load_gml(path)
    except GMLError as exc:
        print("test_empty_file: OK  (%s)" % exc)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected GMLError for empty file")


def test_no_geometry():
    xml = '<?xml version="1.0"?><root><note>hi</note></root>'
    with tempfile.NamedTemporaryFile("w", suffix=".gml", delete=False) as fh:
        fh.write(xml)
        path = fh.name
    try:
        load_gml(path)
    except GMLError as exc:
        print("test_no_geometry: OK  (%s)" % exc)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected GMLError for file with no geometry")


def test_line_mesh_excludes_polygons():
    from gml_editor.viewer import build_line_mesh
    scene = load_gml(SAMPLE)
    mesh, feat_ids = build_line_mesh(scene, vexag=0.0)
    assert mesh is not None
    # Lines only: 7 LineString roads + 1 MultiLineString (2 parts) = 9 cells.
    # The 3 polygons are rendered as buildings instead.
    assert mesh.n_cells == 9, mesh.n_cells
    assert len(feat_ids) == mesh.n_cells
    assert (mesh.points[:, 2] == 0).all(), "vexag=0 should flatten lines to z=0"
    print("test_line_mesh_excludes_polygons: OK")


def test_buildings_extruded():
    from gml_editor.viewer import build_building_mesh
    scene = load_gml(SAMPLE)

    # vexag=0: flat footprints (no vertical extent).
    flat, _ = build_building_mesh(scene, vexag=0.0)
    assert flat is not None
    assert float(np.ptp(flat.points[:, 2])) == 0.0, "vexag=0 buildings stay flat"

    # vexag>0: real 3D boxes. Tallest building (40 m) -> 40/111320*50 deg.
    solid, _ = build_building_mesh(scene, vexag=50.0)
    assert solid is not None
    zext = float(solid.points[:, 2].max())
    expected = 40.0 / 111320.0 * 50.0
    assert abs(zext - expected) < 1e-6, (zext, expected)
    # A box has volume; a flat footprint would not.
    assert solid.volume > 0, solid.volume
    # Base sits on the ground plane.
    assert float(solid.points[:, 2].min()) == 0.0
    print("test_buildings_extruded: OK  (box height=%.5f deg, volume=%.3g)"
          % (zext, solid.volume))


def test_offscreen_render():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import render_scene

    scene = load_gml(SAMPLE)
    plotter = render_scene(scene, off_screen=True, vexag=50.0)
    out = os.path.join(ROOT, "tests", "_render_check.png")
    plotter.screenshot(out)
    plotter.close()
    assert os.path.exists(out) and os.path.getsize(out) > 0
    print("test_offscreen_render: OK  (wrote %s, %d bytes)"
          % (out, os.path.getsize(out)))


if __name__ == "__main__":
    test_loads_sample()
    test_missing_file()
    test_empty_file()
    test_no_geometry()
    test_line_mesh_excludes_polygons()
    test_buildings_extruded()
    test_offscreen_render()
    print("\nALL v0.1 TESTS PASSED")
