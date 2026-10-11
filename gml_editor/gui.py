"""Qt front-end: a top panel + the embedded 3D editor.

The panel shows the loaded file names and the direction arrow's azimuth,
elevation, and endpoint (lat/lon), all editable; editing a field and leaving it
(Enter or focus-out) updates the arrow. Double-clicking the scene moves the
arrow tip and writes the new lat/lon back into the panel. Two placeholder
buttons are wired to stub handlers for later.

Uses ``qtpy`` so it works with either PyQt5 or PySide6, and ``pyvistaqt``'s
``QtInteractor`` to embed the VTK render window as a widget.
"""

from __future__ import annotations

import logging
import os

from qtpy import QtWidgets

from .viewer import GmlEditorView

log = logging.getLogger("gml_editor.gui")

_DEFAULT_AZ = 0.0
_DEFAULT_EL = 45.0


class _FloatField(QtWidgets.QLineEdit):
    """A fixed-width line edit for a numeric field."""

    def __init__(self, width=90):
        super().__init__()
        self.setFixedWidth(width)
        self.setClearButtonEnabled(False)


class EditorWindow(QtWidgets.QMainWindow):
    """Main window: top panel over the embedded 3D editor."""

    def __init__(self, scene, *, vexag=1.0, terrain=None, geoimage=None,
                 texture_on=True, arrow_az=None, arrow_el=None, files=None):
        super().__init__()
        from pyvistaqt import QtInteractor

        files = files or {}
        self.setWindowTitle("3D Terrain GML Editor")

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(self._build_panel(files))

        # Embedded 3D view.
        self._interactor = QtInteractor(central)
        vbox.addWidget(self._interactor, stretch=1)

        # Build the editor on the embedded plotter.
        self.view = GmlEditorView(
            scene, vexag=vexag, terrain=terrain, geoimage=geoimage,
            texture_on=texture_on, arrow_az=arrow_az, arrow_el=arrow_el,
            plotter=self._interactor,
        )
        # Ensure an arrow exists so the panel fields are always meaningful.
        if self.view.arrow_state() is None:
            self.view.set_arrow(az=_DEFAULT_AZ, el=_DEFAULT_EL)
        self.view.on_arrow_moved = self._on_arrow_moved
        # 'q' in the 3D view (VTK's usual quit key) closes the window; Ctrl+Q
        # quits from anywhere (even when a panel field has focus).
        self.view.on_quit = self.close
        from qtpy.QtGui import QKeySequence
        QtWidgets.QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

        self._refresh_fields()
        self._connect_fields()

    # -- panel construction ------------------------------------------------

    def _build_panel(self, files) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame()
        panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(4)

        def _name(p):
            return os.path.basename(p) if p else "—"

        # Row 1: file names.
        row1 = QtWidgets.QHBoxLayout()
        for label, path in (("GML", files.get("gml")),
                            ("DTED", files.get("dted")),
                            ("TIFF", files.get("geotiff"))):
            row1.addWidget(QtWidgets.QLabel(f"<b>{label}:</b> {_name(path)}"))
            row1.addSpacing(10)
        row1.addStretch(1)
        outer.addLayout(row1)

        # Row 2: arrow fields (azimuth, elevation, endpoint lat/lon).
        row2 = QtWidgets.QHBoxLayout()
        self.f_az = _FloatField()
        self.f_el = _FloatField()
        self.f_lat = _FloatField(110)
        self.f_lon = _FloatField(110)
        for label, field in (("Az", self.f_az), ("El", self.f_el),
                            ("Lat", self.f_lat), ("Lon", self.f_lon)):
            row2.addWidget(QtWidgets.QLabel(label))
            row2.addWidget(field)
            row2.addSpacing(6)
        row2.addStretch(1)
        outer.addLayout(row2)

        # Row 3: buttons.
        row3 = QtWidgets.QHBoxLayout()
        self.btn1 = QtWidgets.QPushButton("Button 1")
        self.btn2 = QtWidgets.QPushButton("Button 2")
        self.btn1.clicked.connect(self._on_button1)
        self.btn2.clicked.connect(self._on_button2)
        row3.addWidget(self.btn1)
        row3.addWidget(self.btn2)
        row3.addStretch(1)
        outer.addLayout(row3)

        return panel

    # -- field <-> arrow sync ---------------------------------------------

    def _connect_fields(self):
        for field in (self.f_az, self.f_el, self.f_lat, self.f_lon):
            field.editingFinished.connect(self._apply_fields)

    def _refresh_fields(self):
        """Populate the fields from the current arrow state (without re-applying)."""
        st = self.view.arrow_state()
        if st is None:
            return
        for field, text in ((self.f_az, f"{st['az']:g}"),
                            (self.f_el, f"{st['el']:g}"),
                            (self.f_lat, f"{st['lat']:.6f}"),
                            (self.f_lon, f"{st['lon']:.6f}")):
            field.blockSignals(True)
            field.setText(text)
            field.blockSignals(False)

    def _apply_fields(self):
        """Editing finished on any field: push all four values to the arrow."""
        try:
            az = float(self.f_az.text())
            el = float(self.f_el.text())
            lat = float(self.f_lat.text())
            lon = float(self.f_lon.text())
        except ValueError:
            self._refresh_fields()  # revert bad input
            return
        self.view.set_arrow(az=az, el=el, lon=lon, lat=lat)
        self._refresh_fields()  # normalise formatting / clamp

    def _on_arrow_moved(self, lon, lat):
        """Arrow dragged by double-click: write the new endpoint into the panel."""
        for field, val in ((self.f_lat, lat), (self.f_lon, lon)):
            field.blockSignals(True)
            field.setText(f"{val:.6f}")
            field.blockSignals(False)

    # -- button stubs (handlers to be implemented later) -------------------

    def _on_button1(self):
        log.info("Button 1 clicked (handler not implemented yet)")

    def _on_button2(self):
        log.info("Button 2 clicked (handler not implemented yet)")

    def closeEvent(self, event):  # noqa: N802 (Qt signature)
        try:
            self._interactor.close()
        except Exception:
            pass
        super().closeEvent(event)


def launch(scene, *, vexag=1.0, terrain=None, geoimage=None, texture_on=True,
           arrow_az=None, arrow_el=None, files=None) -> int:
    """Open the Qt editor window and run the event loop. Returns the exit code."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = EditorWindow(
        scene, vexag=vexag, terrain=terrain, geoimage=geoimage,
        texture_on=texture_on, arrow_az=arrow_az, arrow_el=arrow_el, files=files,
    )
    win.resize(1100, 760)
    win.show()
    return app.exec_()
