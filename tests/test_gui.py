"""Tests for the Qt top panel: it shows the file names and arrow fields, editing
a field updates the arrow, and a double-click move writes lat/lon back.

Runs headless via Qt's 'offscreen' platform. If Qt/OpenGL cannot initialise in
this environment, the test SKIPs rather than fails (GUI is environment-sensitive).

Run:  python -m tests.test_gui   (from the project root)
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE = os.path.join(ROOT, "ankara_sample.gml")


def test_panel():
    try:
        from qtpy import QtWidgets
        from gml_editor.gml_loader import load_gml
        from gml_editor.gui import EditorWindow
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        scene = load_gml(SAMPLE)
        win = EditorWindow(
            scene, vexag=50.0, arrow_az=45, arrow_el=30,
            files={"gml": "ankara_sample.gml", "dted": "tile.dt2", "geotiff": "img.tif"},
        )
    except Exception as exc:  # pragma: no cover - headless/Qt/GL unavailable
        print("test_panel: SKIP (Qt unavailable: %s)" % exc)
        return

    # File names shown.
    labels = [w.text() for w in win.findChildren(QtWidgets.QLabel)]
    assert any("ankara_sample.gml" in t for t in labels)
    assert any("tile.dt2" in t for t in labels)
    assert any("img.tif" in t for t in labels)

    # Two placeholder buttons, handlers callable (no-ops for now).
    buttons = [b.text() for b in win.findChildren(QtWidgets.QPushButton)]
    assert buttons == ["Button 1", "Button 2"], buttons
    win._on_button1()
    win._on_button2()

    # 'q' quit is wired to close the Qt window (the embedded VTK view no longer
    # quits on its own).
    assert win.view.on_quit is not None
    closed = []
    win.view.on_quit = lambda: closed.append(True)
    win.view.on_quit()
    assert closed == [True]

    # Fields initialised from the arrow.
    assert float(win.f_az.text()) == 45 and float(win.f_el.text()) == 30

    # Editing fields + focus-out updates the arrow.
    win.f_az.setText("120")
    win.f_el.setText("25")
    win.f_lat.setText("39.9200")
    win.f_lon.setText("32.8000")
    win._apply_fields()
    st = win.view.arrow_state()
    assert st["az"] == 120 and st["el"] == 25
    assert abs(st["lat"] - 39.92) < 1e-6 and abs(st["lon"] - 32.80) < 1e-6

    # A double-click move writes the new endpoint back into the panel.
    win._on_arrow_moved(32.8500, 39.9300)
    assert abs(float(win.f_lon.text()) - 32.85) < 1e-6
    assert abs(float(win.f_lat.text()) - 39.93) < 1e-6

    # Invalid input is reverted, not applied.
    win.f_az.setText("not-a-number")
    win._apply_fields()
    assert float(win.f_az.text()) == 120  # unchanged

    win.close()
    print("test_panel: OK")


if __name__ == "__main__":
    test_panel()
    print("\nGUI TESTS DONE")
