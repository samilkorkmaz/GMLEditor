# 3D Terrain GML Editor

A Windows tool to view and edit GML line and polygon data in 3D, optionally
draped over DTED terrain and GeoTIFF imagery. **Current version: v0.4 —
editing + DTED terrain + GeoTIFF texture.** See [version_plan.md](version_plan.md)
for the full roadmap.

DTED can be downloaded from: https://earthexplorer.usgs.gov/

GeoTIFF can be downloaded from: https://geodataviewer.com/tools/satellite-download/

## Requirements

- Python 3.10+
- `numpy`, `pyvista` (VTK is pulled in by PyVista), `Pillow`
- Optional: `tifffile` + `imagecodecs` — for compressed/tiled GeoTIFFs
  (e.g. Sentinel-2 / GDAL output). Without them, only simple uncompressed
  GeoTIFFs load (via Pillow).

```
pip install --user pyvista numpy Pillow
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
- **t** — toggle the GeoTIFF imagery on/off (when a GeoTIFF is loaded).

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
```

v0.1 covers loading + rendering; v0.2 covers editing (select / delete /
undo / redo), GML export round-trip and fidelity, and feature picking; v0.3
covers the DTED reader, terrain draping, picking over terrain, and that editing
and export still preserve the original coordinates; v0.4 covers the GeoTIFF
reader, georeferencing/alignment, texture orientation, partial overlap, and a
textured render.

## Building a standalone executable (.exe)

You can package the app into a Windows executable that runs **without Python
installed** on the target machine — PyInstaller bundles the interpreter and all
dependencies (NumPy, VTK, PyVista, matplotlib, PIL).

Install PyInstaller, then build from the committed spec:

```
pip install --user pyinstaller
python -m PyInstaller --noconfirm gml_editor.spec
```

This produces `dist\gml_editor\` (**~380 MB**) containing `gml_editor.exe` plus
its bundled DLLs in `_internal\`. Distribute the **whole folder** (zip it). Run
it exactly like the Python version — command-line arguments work identically:

```
dist\gml_editor\gml_editor.exe ankara_sample.gml --vexag 50
dist\gml_editor\gml_editor.exe ankara_sample.gml --screenshot out.png
```

The spec ([gml_editor.spec](gml_editor.spec)) collects `vtk` and `pyvista`, and
**excludes ~320 MB of transitive dependencies the app never imports** (PyQt5,
scipy, llvmlite/numba, pandas, lxml, pydantic, qtpy, …). Without the excludes
the bundle is ~700 MB. The exclude list was derived empirically by checking
which modules actually load during a full render; `matplotlib` (colormaps/fonts)
and `PIL` (screenshots) are kept because they are used.

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
- CRS: GML and DTED are assumed to be geographic (lon/lat); a **UTM** GeoTIFF is
  reprojected to lon/lat to match (pure-Python, WGS84 UTM only). Other projected
  CRSs, reprojecting the GML/DTED themselves, and longitude-aspect correction are
  deferred to v0.5.

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
  viewer.py       mesh building + draping + texturing, GmlEditorView, render_scene
  cli.py          command line, logging, input classification
  __main__.py     entry point (python -m gml_editor)
tests/
  test_v01.py     v0.1 tests (load + render)
  test_v02.py     v0.2 tests (edit, export, picking)
  test_v03.py     v0.3 tests (DTED, draping, terrain picking)
  test_v04.py     v0.4 tests (GeoTIFF, alignment, texturing)
run_gml_editor.py PyInstaller entry point (see "Building a standalone executable")
ankara_sample.gml Sample GML (Ankara roads + buildings, EPSG:4326)
n39_e032_1arc_v3.dt2 Sample DTED tile covering the GML extent
ankara_sample.tif Sample GeoTIFF (synthetic test pattern over the GML extent)
version_plan.md   Version roadmap
```
