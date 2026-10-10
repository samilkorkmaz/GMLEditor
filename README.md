# 3D Terrain GML Editor

A Windows tool to view and edit GML line and polygon data in 3D.
**Current version: v0.2 — view + edit (select, delete, undo, export).** See
[version_plan.md](version_plan.md) for the full roadmap.

## Requirements

- Python 3.10+
- `numpy`, `pyvista`, `pyvistaqt` (VTK is pulled in by PyVista)

```
pip install --user pyvista pyvistaqt numpy
```

## Usage

```
python -m gml_editor <path-to-gml> [--vexag FACTOR] [--screenshot PATH]
```

Example:

```
python -m gml_editor ankara_sample.gml --vexag 50
```

A 3D window opens with the data auto-fitted to view. Navigate with the mouse:

- **Left drag** — rotate
- **Mouse wheel** — zoom
- **Middle drag / Shift+Left drag** — pan

### Editing (v0.2)

- **Left click** — select a feature (a whole road/path line, or an entire
  building box — clicking any wall/edge selects the whole building). The
  selection is highlighted; clicking empty space clears it.
- **Delete** — remove the selected feature.
- **Ctrl+Z / Ctrl+Y** — undo / redo (multi-level).
- **Ctrl+S** — export the edited GML to `<input>_edited.gml` (the input file is
  never overwritten). Survivors keep their original schema, attributes, and CRS.

Feature count, per-layer counts, vertex count, and CRS are logged to the console.

Pass `--screenshot out.png` to render off-screen to a PNG and exit instead of
opening a window (useful on headless machines or for quick previews).

### `--vexag` (vertical exaggeration)

Source heights (e.g. building height in metres) are in a different unit than
lon/lat (degrees), so they are scaled before display:

- `0` — flat 2D map
- `1` — true geographic scale (default); small heights look nearly flat
- `30`–`50` — exaggerate relief so building heights are clearly visible

## What v0.1 renders

- **Lines** (LineString, MultiLineString) as polylines.
- **Polygons** (buildings) extruded into 3D boxes from the ground up to their
  height (from the geometry's z, or a `height_m`/`height` attribute).

Both GML2 (`gml:coordinates`) and GML3 (`gml:posList`/`gml:pos`) are supported.

## Testing

```
python -m tests.test_v01
python -m tests.test_v02
```

v0.1 covers loader correctness, error handling (missing / empty / malformed /
geometry-less files), and off-screen rendering. v0.2 covers editing
(select / delete / undo / redo), GML export round-trip and fidelity, feature
picking, and an off-screen edit-loop smoke test.

## Building a standalone executable (.exe)

You can package the app into a Windows executable that runs **without Python
installed** on the target machine — PyInstaller bundles the interpreter and all
dependencies (NumPy, VTK, PyVista).

Install PyInstaller, then build:

```
pip install --user pyinstaller
python -m PyInstaller --noconfirm --onedir --console --name gml_editor ^
  --collect-all vtk --collect-all pyvista --collect-all pyvistaqt ^
  run_gml_editor.py
```

This produces `dist\gml_editor\` containing `gml_editor.exe` plus its bundled
DLLs in `_internal\`. Distribute the **whole folder** (zip it). Run it exactly
like the Python version — command-line arguments work identically:

```
dist\gml_editor\gml_editor.exe ankara_sample.gml --vexag 50
dist\gml_editor\gml_editor.exe ankara_sample.gml --screenshot out.png
```

After the first build, a `gml_editor.spec` is generated; rebuild with just:

```
python -m PyInstaller --noconfirm gml_editor.spec
```

Notes:
- `--onedir` (a folder) is recommended over `--onefile`: faster startup and far
  more reliable with VTK's native libraries. `--onefile` works too but unpacks
  to a temp folder on every launch.
- `--console` keeps the terminal so logging and `--help` are visible (it is a
  CLI app). `--windowed` would hide them.
- `--collect-all vtk pyvista pyvistaqt` pulls in data files and dynamically
  imported submodules that static analysis misses; without them the exe builds
  but crashes at render time.
- Build outputs (`dist\`, `build\`, `__pycache__\`) are disposable and need not
  be committed.

## Notes

- **No GDAL in v0.1.** GML is parsed with the standard-library XML parser.
  GDAL/OGR will be introduced at v0.3 (DTED terrain) and v0.4 (GeoTIFF), which
  need the native GDAL library (install via OSGeo4W or conda at that point).
- CRS reprojection and longitude-aspect correction are deferred to v0.5; v0.1
  reads and stores the GML's own CRS but does not reproject.

## Project layout

```
gml_editor/
  model.py        Scene and Feature data model
  gml_loader.py   load_gml(), GMLError, shared feature iterator
  editing.py      EditSession (selection + undo/redo)
  export.py       export_gml() (edited-GML round-trip export)
  viewer.py       mesh building, GmlEditorView (interactive editor), render_scene
  cli.py          command line, logging
  __main__.py     entry point (python -m gml_editor)
tests/
  test_v01.py     v0.1 smoke tests (load + render)
  test_v02.py     v0.2 tests (edit, export, picking)
run_gml_editor.py PyInstaller entry point (see "Building a standalone executable")
ankara_sample.gml Sample data (Ankara roads + buildings, EPSG:4326)
version_plan.md   Version roadmap
```
