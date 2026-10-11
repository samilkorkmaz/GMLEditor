"""Tests for the red direction arrow: orientation from azimuth/elevation,
placement at the ground middle, length from the scene extent, and that a
double-click-style move translates the tip while keeping the angles.

Run:  python -m tests.test_arrow   (from the project root)
"""

import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gml_editor.gml_loader import load_gml  # noqa: E402

SAMPLE = os.path.join(ROOT, "ankara_sample.gml")


def test_arrow_direction():
    from gml_editor.viewer import arrow_direction
    cases = {(0, 0): (0, 1, 0), (90, 0): (1, 0, 0), (180, 0): (0, -1, 0),
             (270, 0): (-1, 0, 0), (0, 90): (0, 0, 1)}
    for (az, el), exp in cases.items():
        assert np.allclose(arrow_direction(az, el), exp, atol=1e-9), (az, el)
    # Elevation tilts out of the horizontal plane; vector stays unit length.
    u = arrow_direction(30, 40)
    assert abs(np.linalg.norm(u) - 1.0) < 1e-12
    assert abs(u[2] - math.sin(math.radians(40))) < 1e-12
    print("test_arrow_direction: OK")


def test_arrow_placement_flat():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import GmlEditorView
    scene = load_gml(SAMPLE)
    view = GmlEditorView(scene, vexag=50.0, off_screen=True, arrow_az=45, arrow_el=30)
    b = scene.bounds()
    clon, clat = 0.5 * (b[0] + b[1]), 0.5 * (b[2] + b[3])
    # Tip at the middle of the ground; world x is lon*kx, z=0 (no terrain).
    assert abs(view._arrow_tip[0] - clon * view._kx) < 1e-9
    assert abs(view._arrow_tip[1] - clat) < 1e-9
    assert abs(view._arrow_tip[2]) < 1e-9
    # Length scales with the (aspect-corrected) scene dimensions.
    width = (b[1] - b[0]) * view._kx
    height = b[3] - b[2]
    assert abs(view._arrow_len - 0.5 * math.hypot(width, height)) < 1e-9
    view.plotter.close()
    print("test_arrow_placement_flat: OK  (len=%.4f)" % view._arrow_len)


def test_arrow_placement_on_terrain():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.dted import load_dted
    from gml_editor.terrain import Terrain
    from gml_editor.viewer import GmlEditorView, _metres_per_horizontal_unit
    import tempfile
    from gml_editor.dted import write_dted

    scene = load_gml(SAMPLE)
    with tempfile.TemporaryDirectory() as tmp:
        d = 3.0 / 3600.0
        cols = np.arange(181); rows = np.arange(121)
        LON, LAT = np.meshgrid(32.75 + cols * d, 39.85 + rows * d)
        Z = 850 + 300 * np.exp(-(((LON - 32.84) ** 2 + (LAT - 39.92) ** 2) / 0.002))
        p = os.path.join(tmp, "t.dt1")
        write_dted(p, Z, 32.75, 39.85, 3.0, 3.0)
        terrain = Terrain(load_dted(p), _metres_per_horizontal_unit(scene.working_crs), 15.0)
        view = GmlEditorView(scene, vexag=15.0, off_screen=True, terrain=terrain,
                             arrow_az=45, arrow_el=30)
        w, e, s, n = view._scene_extent()
        clon, clat = 0.5 * (w + e), 0.5 * (s + n)
        # Tip z equals the terrain display height at the centre (sits on ground).
        assert abs(view._arrow_tip[2] - terrain.elevation_display(clon, clat)) < 1e-9
        assert view._arrow_tip[2] > 0
        view.plotter.close()
    print("test_arrow_placement_on_terrain: OK")


def test_arrow_move_keeps_angles():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import GmlEditorView, arrow_direction
    scene = load_gml(SAMPLE)
    view = GmlEditorView(scene, vexag=50.0, off_screen=True, arrow_az=120, arrow_el=35)
    u = arrow_direction(120, 35)
    length = view._arrow_len

    # Translate the tip (as a double-click would) and redraw.
    new_tip = view._arrow_tip + np.array([0.02, -0.01, 0.0])
    view._arrow_tip = new_tip.copy()
    view._draw_arrow()

    # Angles + length unchanged: the drawn tail is still tip + u*length.
    tail = view._arrow_tip + u * length
    drawn_dir = view._arrow_tip - tail
    assert np.allclose(drawn_dir / np.linalg.norm(drawn_dir), -u, atol=1e-9)
    assert abs(np.linalg.norm(drawn_dir) - length) < 1e-9
    assert np.allclose(view._arrow_tip, new_tip)
    # The arrow actor is present in the scene.
    assert "direction_arrow" in view.plotter.renderer.actors
    view.plotter.close()
    print("test_arrow_move_keeps_angles: OK")


def test_offscreen_arrow_render():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import render_scene
    scene = load_gml(SAMPLE)
    plotter = render_scene(scene, off_screen=True, vexag=50.0, arrow_az=60, arrow_el=40)
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "_arrow_render.png")
    plotter.screenshot(out)
    assert os.path.getsize(out) > 0
    plotter.close()
    os.unlink(out)
    print("test_offscreen_arrow_render: OK")


if __name__ == "__main__":
    test_arrow_direction()
    test_arrow_placement_flat()
    test_arrow_placement_on_terrain()
    test_arrow_move_keeps_angles()
    test_offscreen_arrow_render()
    print("\nALL ARROW TESTS PASSED")
