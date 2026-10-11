# 3D Terrain GML Editor

A Windows tool to view and edit [GML](https://en.wikipedia.org/wiki/Geography_Markup_Language) line and polygon data in 3D, optionally
draped over [DTED](https://en.wikipedia.org/wiki/DTED) terrain and [GeoTIFF](https://en.wikipedia.org/wiki/GeoTIFF) imagery. **Current version: v0.5.** See [version_plan.md](version_plan.md)
for the full roadmap.

GML can be created with Claude Code.

DTED can be downloaded from: https://earthexplorer.usgs.gov/

GeoTIFF can be downloaded from: https://geodataviewer.com/tools/satellite-download/

## Requirements

- Python 3.10+
- `numpy`, `pyvista` (VTK is pulled in by PyVista), `Pillow`
- `pyvistaqt` + a Qt binding (`PyQt5` or `PySide6`) — for the interactive window
  with the top panel
- Optional: `tifffile` + `imagecodecs` — for compressed/tiled GeoTIFFs
  (e.g. Sentinel-2 / GDAL output). Without them, only simple uncompressed
  GeoTIFFs load (via Pillow).

```
pip install --user pyvista pyvistaqt PyQt5 numpy Pillow
pip install --user tifffile imagecodecs      # for real-world GeoTIFFs
```

## Usage

```
python -m gml_editor <gml> [<dted>] [<geotiff>] [--vexag FACTOR] [--screenshot PATH]
```

Examples:

```
python -m gml_editor ankara_sample.gml --vexag 50                               # GML only
python -m gml_editor ankara_sample.gml n39_e032_1arc_v3.dt2 --vexag 15          # draped on terrain
python -m gml_editor ankara_sample.gml n39_e032_1arc_v3.dt2 ankara_sample.tif --vexag 15  # + imagery
```

The DTED and GeoTIFF files are optional and order-independent (classified by
extension/content). The DTED provides the elevation surface the GML is draped
onto; the GeoTIFF is draped over it as imagery. By default the terrain is
**cropped to the GML extent** (plus a small margin) so the geometry isn't a
speck on a full 1-degree tile; pass `--full-terrain` to show the whole tile.
Pass `--no-texture` to start with the imagery hidden.

An interactive window opens: a **top panel** above the 3D view. Navigate the 3D
view with the mouse:

- **Left drag** — rotate
- **Mouse wheel** — zoom
- **Middle drag / Shift+Left drag** — pan

### Top panel

The panel shows the loaded **GML / DTED / TIFF** file names and the direction
arrow's **Az**, **El**, **Lat**, **Lon** in editable fields, plus two buttons
(handlers to be implemented). Editing a field and pressing Enter or clicking away
updates the arrow; double-clicking the scene moves the arrow's tip and writes the
new Lat/Lon back into the panel. (The panel requires `pyvistaqt` + a Qt binding;
without them the app falls back to a basic viewer. `--screenshot` never needs Qt.)

### Editing (v0.2)

- **Left click** — select a feature (a whole road/path line, or an entire
  building box — clicking any wall/edge selects the whole building). The
  selection is highlighted; clicking empty space clears it.
- **Delete** — remove the selected feature.
- **Ctrl+Z / Ctrl+Y** — undo / redo (multi-level).
- **Ctrl+S** — export the edited GML to `<input>_edited.gml` (the input file is
  never overwritten). Survivors keep their original schema, attributes, and CRS.
- **t** — toggle the GeoTIFF imagery on/off (when a GeoTIFF is loaded).
- **Double-click** — move the direction arrow's tip to the clicked ground point
  (when `--arrow` is used; the azimuth/elevation stay fixed).

### Direction arrow (`--arrow AZ EL`)

`--arrow AZ EL` draws a red arrow pointing to the middle of the ground, oriented
by **AZ** (azimuth in degrees clockwise from True North) and **EL** (elevation
in degrees above the horizon) — e.g. a sensor line-of-sight or sun vector. Its
length is set from the (cropped) scene dimensions. Double-clicking the scene
translates the arrow so its tip is the clicked ground point, keeping AZ/EL.

```
python -m gml_editor ankara_sample.gml n39_e032_1arc_v3.dt2 --vexag 15 --arrow 45 30
```

Feature count, per-layer counts, vertex count, and CRS are logged to the console.

Pass `--screenshot out.png` to render off-screen to a PNG and exit instead of
opening a window (useful on headless machines or for quick previews).

### `--vexag` (vertical exaggeration)

Vertical values (terrain elevation and building heights, both in metres) are in
a different unit than lon/lat (degrees), so they are scaled before display by a
single factor. **The same factor applies to terrain and building heights
together**, so the two stay proportional to each other (a 40 m building looks
correctly tiny next to a 400 m hill); only the vertical axis as a whole is
stretched relative to the horizontal extent.

- `0` — flat 2D map (no relief)
- `1` — true geographic scale (default); relief looks nearly flat on a
  city-scale map
- `~15` — good for real terrain (e.g. the Ankara DTED tile, ~400 m of relief)
- `30`–`50` — strong exaggeration; makes small building heights clearly visible
  when there is no terrain

There is a single factor for both; building heights cannot currently be scaled
independently of the terrain.

## What it renders

- **Lines** (LineString, MultiLineString) as polylines.
- **Polygons** (buildings) extruded into 3D boxes up to their height (from the
  geometry's z, or a `height_m`/`height` attribute).
- **DTED terrain** (when a DTED file is given): an elevation surface colored by
  height, with lines draped onto it and buildings standing on it.
- **GeoTIFF imagery** (when a GeoTIFF is given): draped as a texture over the
  terrain (or a flat plane), aligned by georeferencing; terrain outside the
  imagery footprint is shown in a neutral colour. Toggle with `t`. A GeoTIFF in
  **UTM** (e.g. Sentinel-2) is reprojected to lon/lat on load to align with the
  GML/DTED.

Both GML2 (`gml:coordinates`) and GML3 (`gml:posList`/`gml:pos`) are supported.
DTED and GeoTIFF are read with built-in pure-Python readers (no GDAL): DTED via
a small binary parser; GeoTIFF via `tifffile`/`imagecodecs` when installed
(handles compression/tiling) or Pillow for simple files. UTM↔WGS84 reprojection
is a pure-Python Transverse Mercator implementation (`reproject.py`). Large DTED
tiles and GeoTIFFs are downsampled to stay interactive.

## Testing

```
python -m tests.test_v01
python -m tests.test_v02
python -m tests.test_v03
python -m tests.test_v04
python -m tests.test_v05
python -m tests.test_arrow
python -m tests.test_gui
```

v0.1 covers loading + rendering; v0.2 covers editing (select / delete /
undo / redo), GML export round-trip and fidelity, and feature picking; v0.3
covers the DTED reader, terrain draping, picking over terrain, and that editing
and export still preserve the original coordinates; v0.4 covers the GeoTIFF
reader, georeferencing/alignment, texture orientation, partial overlap, and a
textured render; v0.5 covers CRS reprojection + axis order, mixed-CRS alignment,
extent-overlap errors, and the longitude-aspect proportion correction.

## Building a standalone executable (.exe)

You can package the app into a Windows executable that runs **without Python
installed** on the target machine — PyInstaller bundles the interpreter and all
dependencies (NumPy, VTK, PyVista, matplotlib, PIL).

Install PyInstaller, then build from the committed spec:

```
pip install --user pyinstaller
python -m PyInstaller --noconfirm gml_editor.spec
```

This produces `dist\gml_editor\` (**~500 MB** — the Qt GUI stack adds ~130 MB
over the headless core) containing `gml_editor.exe` plus its bundled DLLs in
`_internal\`. Distribute the **whole folder** (zip it). Run
it exactly like the Python version — command-line arguments work identically:

```
dist\gml_editor\gml_editor.exe ankara_sample.gml --vexag 50
dist\gml_editor\gml_editor.exe ankara_sample.gml --screenshot out.png
```

The spec ([gml_editor.spec](gml_editor.spec)) collects `vtk`, `pyvista`,
`pyvistaqt`/`qtpy`/`PyQt5` (the GUI panel) and `tifffile`/`imagecodecs`
(GeoTIFF), and **excludes transitive dependencies the app never imports**
(scipy, llvmlite/numba, pandas, lxml, pydantic, …). The exclude list was derived
empirically by checking which modules actually load; `matplotlib` (colormaps/
fonts) and `PIL` (screenshots) are kept because they are used.

Notes:
- `--onedir` (a folder, set in the spec) is preferred over `--onefile`: faster
  startup and far more reliable with VTK's native libraries. `--onefile` unpacks
  to a temp folder on every launch.
- `console=True` (in the spec) keeps the terminal so logging and `--help` are
  visible (it is a CLI app).
- The remaining size is dominated by VTK (~290 MB) and NumPy (~39 MB); shrinking
  substantially further would mean replacing the VTK rendering stack (e.g. a
  native GPU renderer), not just trimming dependencies.
- Build outputs (`dist\`, `build\`, `__pycache__\`) are disposable and need not
  be committed.

## Notes

- **No GDAL.** All formats are read with pure-Python code: GML via the stdlib
  XML parser, DTED via a small binary parser (`dted.py`), GeoTIFF via Pillow
  (`geotiff.py`). This keeps the app installable and the bundle lean, at the cost
  of supporting only the common cases (north-up GeoTIFFs, standard DTED levels).
- **CRS (v0.5).** Everything is brought into one working CRS (WGS84 lon/lat):
  GML is reprojected on load from its `srsName` (UTM → lon/lat, with axis-order
  handling), and UTM GeoTIFFs are reprojected too. DTED is already lon/lat.
  Use `--gml-crs EPSG:xxxx` / `--swap-xy` to override detection. Only geographic
  and WGS84/UTM are supported — other projected CRSs raise a clear error.
- **Proportions (v0.5).** East-west is scaled by cos(latitude) so shapes aren't
  stretched (one degree of longitude is shorter than one of latitude). A full
  local *metric* projection is left for future work.
- **Performance (v0.5).** DTED meshes and GeoTIFFs are downsampled
  (`--max-terrain-dim`, `--max-texture-dim`) and imagery is mipmapped; load
  progress is logged. Non-overlapping DTED/GeoTIFF vs the GML is a clear error.

## Project layout

```
gml_editor/
  model.py        Scene and Feature data model
  gml_loader.py   load_gml(), GMLError, shared feature iterator
  editing.py      EditSession (selection + undo/redo)
  export.py       export_gml() (edited-GML round-trip export)
  dted.py         load_dted()/write_dted() (pure-Python DTED reader)
  geotiff.py      load_geotiff() (tifffile/Pillow GeoTIFF reader, CRS detect)
  reproject.py    pure-Python UTM<->WGS84 + reproject_to_lonlat()
  terrain.py      Terrain (elevation sampler + mesh), densify()
  viewer.py       mesh building + draping + texturing + arrow, GmlEditorView
  gui.py          Qt window: top panel (files, arrow fields, buttons) + 3D view
  cli.py          command line, logging, input classification
  __main__.py     entry point (python -m gml_editor)
tests/
  test_v01.py     v0.1 tests (load + render)
  test_v02.py     v0.2 tests (edit, export, picking)
  test_v03.py     v0.3 tests (DTED, draping, terrain picking)
  test_v04.py     v0.4 tests (GeoTIFF, alignment, texturing)
  test_v05.py     v0.5 tests (CRS reprojection, axis order, overlap, proportions)
  test_arrow.py   direction-arrow tests (orientation, placement, move)
  test_gui.py     Qt panel tests (file labels, field<->arrow sync, buttons)
run_gml_editor.py PyInstaller entry point (see "Building a standalone executable")
ankara_sample.gml Sample GML (Ankara roads + buildings, EPSG:4326)
n39_e032_1arc_v3.dt2 Sample DTED tile covering the GML extent
ankara_sample.tif Sample GeoTIFF (synthetic test pattern over the GML extent)
version_plan.md   Version roadmap
```
