"""v0.2 tests: editing (select/delete/undo/redo), export round-trip, picking,
and an off-screen edit-loop smoke test.

Run:  python -m tests.test_v02   (from the project root)
"""

import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gml_editor.gml_loader import load_gml  # noqa: E402
from gml_editor.editing import EditSession  # noqa: E402
from gml_editor.export import default_output_path, export_gml, ExportError  # noqa: E402

SAMPLE = os.path.join(ROOT, "ankara_sample.gml")


def test_edit_session_delete_undo_redo():
    scene = load_gml(SAMPLE)
    session = EditSession(scene)
    original = [f.fid for f in session.features]
    assert len(original) == 11

    target = session.features[3]
    session.select(target)
    assert session.selected is target

    deleted = session.delete_selected()
    assert deleted is target
    assert session.selected is None
    assert target not in session.features
    assert len(session.features) == 10

    # Undo restores at the exact original position -> identical ordering.
    session.undo()
    assert [f.fid for f in session.features] == original

    # Redo re-deletes it.
    session.redo()
    assert target not in session.features
    assert len(session.features) == 10
    # A fresh delete clears the redo history.
    session.undo()
    session.select(session.features[0])
    session.delete_selected()
    assert not session.can_redo
    print("test_edit_session_delete_undo_redo: OK")


def test_delete_all_then_undo_all():
    scene = load_gml(SAMPLE)
    session = EditSession(scene)
    original = [f.fid for f in session.features]
    # Delete every feature.
    while session.features:
        session.select(session.features[0])
        session.delete_selected()
    assert session.features == []
    # Undo all the way back -> exact original state.
    while session.can_undo:
        session.undo()
    assert [f.fid for f in session.features] == original
    print("test_delete_all_then_undo_all: OK")


def test_export_preserves_and_drops():
    scene = load_gml(SAMPLE)
    session = EditSession(scene)

    # Delete the two highway roads (roads.1, roads.2) and one building.
    to_delete = [f for f in list(session.features)
                 if f.fid in ("roads.1", "roads.2", "buildings.1")]
    assert len(to_delete) == 3
    for f in to_delete:
        session.select(f)
        session.delete_selected()
    assert len(session.features) == 8

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "edited.gml")
        written = export_gml(scene, session.features, out)
        assert written == out and os.path.exists(out)

        # Re-open the exported file: correct feature count, deletions gone,
        # survivors keep attributes + CRS.
        reloaded = load_gml(out)
        assert reloaded.feature_count == 8, reloaded.feature_count
        assert reloaded.crs == "EPSG:4326", reloaded.crs
        fids = {f.fid for f in reloaded.features}
        assert "roads.1" not in fids and "buildings.1" not in fids
        road0 = next(f for f in reloaded.features if f.fid == "roads.0")
        assert road0.attributes.get("name") == "Ataturk Boulevard"
        bld0 = next(f for f in reloaded.features if f.fid == "buildings.0")
        assert bld0.attributes.get("height_m") == "40"
    print("test_export_preserves_and_drops: OK")


def test_export_never_overwrites_input():
    scene = load_gml(SAMPLE)
    session = EditSession(scene)
    try:
        export_gml(scene, session.features, SAMPLE)
    except ExportError as exc:
        print("test_export_never_overwrites_input: OK  (%s)" % exc)
        return
    raise AssertionError("export should refuse to overwrite the input file")


def test_export_empty_is_valid():
    scene = load_gml(SAMPLE)
    session = EditSession(scene)
    while session.features:
        session.select(session.features[0])
        session.delete_selected()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "empty.gml")
        export_gml(scene, session.features, out)
        # Still well-formed XML; it simply has no drawable features, so the
        # loader reports that clearly rather than crashing.
        import xml.etree.ElementTree as ET
        ET.parse(out)  # raises if malformed
    print("test_export_empty_is_valid: OK")


def test_default_output_path():
    assert default_output_path("/a/b/city.gml") == os.path.join("/a/b", "city_edited.gml") \
        or default_output_path("/a/b/city.gml").endswith("city_edited.gml")
    print("test_default_output_path: OK")


def test_offscreen_edit_loop_and_picking():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import GmlEditorView

    scene = load_gml(SAMPLE)
    view = GmlEditorView(scene, vexag=50.0, off_screen=True)
    view.plotter.show(auto_close=False)  # realize the render window for picking

    # Building pick: project a point on a building footprint to display coords,
    # then confirm the click resolves to that whole building feature.
    building = next(f for f in view.session.features if f.geom_type == "Polygon")
    centroid = building.parts[0][:, :3].mean(axis=0)
    centroid[2] = 0.0
    disp = view._world_to_display(np.array([centroid]))[0]
    picked = view.pick_at_display(disp[0], disp[1])
    assert picked is building, (picked.fid if picked else None, building.fid)

    # Line pick: midpoint of a road segment should resolve to that road.
    road = next(f for f in view.session.features if f.geom_type == "LineString")
    seg = road.parts[0]
    mid = (seg[0] + seg[1]) / 2.0
    mid[2] = 0.0
    dmid = view._world_to_display(np.array([mid]))[0]
    picked_line = view.pick_at_display(dmid[0], dmid[1])
    assert picked_line is road, (picked_line.fid if picked_line else None, road.fid)

    # Edit loop through the view: select -> delete -> undo.
    before = len(view.session.features)
    view.select_feature(building)
    view.delete_selected()
    assert len(view.session.features) == before - 1
    view.undo()
    assert len(view.session.features) == before

    # Export through the view.
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "via_view.gml")
        assert view.export(out) == out and os.path.exists(out)

    view.plotter.close()
    print("test_offscreen_edit_loop_and_picking: OK")


if __name__ == "__main__":
    test_edit_session_delete_undo_redo()
    test_delete_all_then_undo_all()
    test_export_preserves_and_drops()
    test_export_never_overwrites_input()
    test_export_empty_is_valid()
    test_default_output_path()
    test_offscreen_edit_loop_and_picking()
    print("\nALL v0.2 TESTS PASSED")
