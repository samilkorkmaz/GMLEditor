# 3D Terrain GML Editor: Version Plan

**Target platform:** Windows
**Proposed stack:** Python + GDAL/OGR + PyVista (VTK), packaged with PyInstaller
**Strategy:** Start with the simplest data type (GML), get the editing loop (select, delete, undo, export) working early, then layer terrain and imagery underneath it.

---

## Version Overview

| Version | Theme | Command line |
|---|---|---|
| v0.1 | GML display only **(DONE)** | `python -m gml_editor <gml> [--vexag N]` |
| v0.2 | GML editing (select, delete, undo, export) **(DONE)** | `python -m gml_editor <gml> [--vexag N]` |
| v0.3 | DTED terrain + GML draped **(DONE)** | `python -m gml_editor <gml> <dted> [--vexag N]` |
| v0.4 | GeoTIFF texture **(DONE)** | `python -m gml_editor <gml> <dted> <geotiff>` |
| v0.5 | CRS robustness and performance | same |
| v1.0 | Packaging and release | same |

---

## v0.1: GML Display Only — **DONE**

**Goal:** Prove the toolchain end to end: read GML, render it, navigate with the mouse.

**How to run**

```
python -m gml_editor <path-to-gml> [--vexag FACTOR]
```

Example: `python -m gml_editor ankara_sample.gml --vexag 50`

**Implemented scope**
- Parse command line: one GML file path. Usage is shown and the process exits non‑zero on missing / unreadable / malformed / empty / geometry‑less files.
- Read all line geometries (LineString, MultiLineString, and polygon boundaries). Both GML2 (`gml:coordinates`) and GML3 (`gml:posList`/`gml:pos`) encodings are handled.
- Render in a 3D window: line features as polylines; **polygon features extruded into 3D solids** (see "Beyond original scope" below).
- Mouse navigation: pan, zoom (wheel), and rotate (default VTK trackball interactor).
- Auto-fit camera to the data extent on startup (top-down when flat, isometric when there is vertical relief).
- Log feature count, per-layer counts, vertex count, and CRS to the console.
- Orientation axes with light-colored X/Y/Z labels (legible on the dark background).

**Beyond original scope (added on request)**
- **Vertical exaggeration** (`--vexag`): source z/height (metres) is converted into the x/y unit and scaled. `0` = flat 2D map, `1` = true geographic scale (default), `>1` exaggerates relief (e.g. 30–50 to make small building heights visible on a city-scale map).
- **Buildings as 3D boxes**: polygon footprints are extruded from the ground plane (z=0) up to their height, rendered as shaded solids with visible edges. Height is read from the geometry's z, falling back to a `height_m`/`height` attribute.

**Out of scope (unchanged):** terrain, imagery, selection, editing. Not done: building wall/extrusion from true terrain, CRS reprojection, longitude-aspect correction.

**Acceptance criteria — met**
- Opens the sample GML (`ankara_sample.gml`) and shows all features.
- Mesh build for 100k line vertices is ~7 ms; VTK renders interactively (responsive pan/zoom). *Note: the interactive window was not exercised here (headless dev environment); rendering was verified via off-screen screenshots. Confirm the live window on a desktop.*
- Invalid / empty / malformed / geometry-less files give a clear error (via `GMLError`) and a non-zero exit, not a crash.

**Decisions made this version**
- **Stack:** Python + **PyVista/VTK** for rendering (installed and working). **GDAL/OGR was NOT used** — it has no prebuilt wheel for the local Python and needs the native GDAL library (OSGeo4W/conda), which is not installable here without an admin installer. GML is XML, so v0.1 parses it with the standard-library XML parser behind a single `load_gml()` entry point. **GDAL becomes necessary at v0.3 (DTED) / v0.4 (GeoTIFF)**; install it then (OSGeo4W or conda) and swap an OGR-backed loader in behind the same interface.
- **Data model:** `Scene` (features + CRS + source path) and `Feature` (stable `fid`, layer, geom_type, per-part `(N,3)` vertex arrays holding the source coordinates, attributes, and a `source_ref` to the original XML element). `source_ref` plays the role the plan assigned to the OGR feature reference, so v0.2 undo/export can round-trip features unchanged.
- **Working CRS:** the GML's own `srsName` is read and stored centrally on the `Scene` (e.g. `EPSG:4326`); `None` if undeclared. No reprojection yet.
- **"Lines":** LineString and MultiLineString render as polylines; Polygon/LinearRing boundaries render as extruded solids (not plain lines).

**Code layout**
- `gml_editor/model.py` — `Scene`, `Feature`.
- `gml_editor/gml_loader.py` — `load_gml()`, `GMLError`.
- `gml_editor/viewer.py` — mesh building (`build_line_mesh`, `build_building_mesh`), vertical-scale/CRS helpers, camera, `render_scene`.
- `gml_editor/cli.py`, `gml_editor/__main__.py` — CLI, logging, entry point.
- `tests/test_v01.py` — loader correctness, error handling, line/building mesh and off-screen render smoke tests.

---

## v0.2: GML Editing — **DONE**

**Goal:** Deliver the full interaction loop on the simplest data, before terrain complicates picking.

**Controls:** left-click select · `Delete` remove · `Ctrl+Z` undo · `Ctrl+Y` redo · `Ctrl+S` export · `q` quit.

**Scope**
- Left click selects a whole feature and highlights it:
  - For a line feature (road/path): the nearest line within a screen-space distance threshold.
  - For a building: clicking **anywhere on its extruded box** (any wall, cap, or edge) selects the **entire building**, not the individual face, ring segment, or line under the cursor. The whole box is highlighted as one unit.
- Click on empty space clears the selection.
- `Delete` removes the selected feature from the display.
- `Ctrl+Z` restores the most recently deleted feature (multi-level undo stack).
- Export edited GML to a new file (menu item or `Ctrl+S`, plus a default output name such as `<input>_edited.gml`). Never overwrite the input.
- Exported file preserves the original schema, attributes, and CRS.

**Design notes**
- Selection granularity: always the whole feature — a LineString/MultiLineString in full, or a complete building (all parts/rings and, in the 3D view, every wall and cap of its extruded box). Never a single segment, ring, or face. This keeps undo and export simple.
- Picking maps the clicked primitive back to its owning feature via the `feature_index` cell array already attached to every mesh in v0.1 (both the line mesh and the extruded-building mesh). A building box contributes many cells but they all carry the same `feature_index`, so any hit resolves to one feature.
- Highlighting a selected building re-colors/outlines the whole box (all its cells), not just the picked face.
- Undo stack stores `(feature, position)` so restoration is exact. Implemented in `editing.py` (`EditSession`), with multi-level undo **and** redo.
- Export: since v0.1 parses GML with the stdlib (no OGR — see v0.1 notes), export round-trips the original XML tree minus the deleted features' elements. Surviving elements are copied verbatim, so schema, attributes, and CRS are preserved exactly. Deleted features are matched by a stable document-order `order` key via the same feature-iterator used at load. Implemented in `export.py`. (When OGR arrives at v0.3+, an OGR-backed export can replace this behind the same function.)
- `Ctrl+Y` redo: implemented.

**Acceptance criteria — met**
- Clicking any face or edge of a building selects and highlights the whole building; `Delete` then removes the entire box (verified by the picking test and before/after renders). Building picks use a VTK cell picker → `feature_index`; thin lines use a screen-space nearest-segment test.
- Delete then undo repeatedly returns the exact original state (unit-tested, including delete-all-then-undo-all).
- Exported GML re-opens with the correct feature count, attributes, and CRS; namespace prefixes (`ogr:`, `gml:`) and `srsName` are preserved. *Verified by re-loading the export and by text inspection; not opened in QGIS here.*
- Deleting all features and exporting produces a valid (well-formed) empty GML.
- *Caveat:* the live interactive window (mouse/keys) was not exercised in this headless dev environment — all edit operations are plain methods verified off-screen; confirm the live window on a desktop.

**Code added this version**
- `editing.py` — `EditSession` (selection + undo/redo stack).
- `export.py` — `export_gml()` / `default_output_path()` (XML round-trip export, refuses to overwrite the input).
- `viewer.py` — `GmlEditorView` (picking, highlight, rebuild-on-edit, key/mouse wiring); `render_scene` now opens this editor.
- `model.py` — `Feature.order`; `Scene.tree_root` + `Scene.nsmap`.
- `tests/test_v02.py` — editing, export round-trip, picking, off-screen edit-loop smoke tests.

---

## v0.3: DTED Terrain — **DONE**

**Goal:** Add the elevation surface and drape the GML on it.

**Scope (implemented)**
- Command line accepts a DTED file alongside the GML (order-independent; files are classified by extension/content). A sample tile `ankara_sample.dt1` is included.
- Read DTED (any level) into an elevation grid — **with a pure-Python reader, not GDAL** (see decision below).
- DTED void values (-32767) are detected and filled (with the tile mean).
- Terrain mesh built as a `StructuredGrid`, colored by elevation, downsampled (stride to <= 400/axis) so large Level-2 tiles stay responsive.
- Terrain height sampled at each GML vertex by bilinear interpolation; lines get a small vertical offset to avoid z-fighting.
- Long GML segments are densified (to ~one terrain cell) before draping so lines follow the surface between vertices.
- v0.2 editing preserved in 3D: selection, delete, undo/redo, and export all still work.

**Decision: no GDAL (pure-Python DTED).** GDAL is still not installable in this environment (see v0.1 notes). DTED is a simple, documented binary format, so it is read directly in `dted.py` (UHL/DSI/ACC headers + per-column records, 16-bit big-endian **sign-magnitude** elevations). This keeps the project installable and matches the pure-language approach. A sample-writer (`write_dted`) generates spec-conformant tiles for tests. GeoTIFF (v0.4) can likewise use a pure-Python reader (`tifffile`/`imagecodecs`) rather than GDAL.

**Acceptance criteria — met**
- DTED tiles load; large grids are downsampled so the UI stays responsive (tested with a 900x900 tile → capped mesh). *Real Level-2 (3601²) not run here, but the striding path is exercised.*
- Lines follow terrain contours (densify + bilinear sample); verified by render and by a draping test (line z matches the sampled surface).
- Picking still selects the correct line/building from angled views over terrain — line picking projects the **exact draped** geometry, so it stays aligned (tested).
- Exported GML coordinates are unchanged by draping (draping is display-only; export uses the untouched source tree) — tested by reloading an export and comparing coordinates.

**Enhancement — crop terrain to the GML.** A full 1-degree tile (e.g. the real `n39_e032_1arc_v3.dt2`, 3601x3601) dwarfs a city-block GML (which covers ~11% x 7% of it). By default the DTED is cropped to the GML extent plus a small margin (`DtedGrid.subset()`), so the geometry fills the view; `--full-terrain` shows the whole tile. Verified on the real tile (3601x3601 cropped to 287x457).

**Code added:** `dted.py` (reader + writer + `subset`), `terrain.py` (`Terrain` sampler/mesh + `densify`); `viewer.py` builders take an optional `terrain`; `cli.py` classifies inputs, crops, and builds the terrain; `tests/test_v03.py`.

---

## v0.4: GeoTIFF Texture — **DONE**

**Goal:** Drape imagery over the terrain.

**Scope (implemented)**
- Command line accepts a GeoTIFF alongside the GML (and optional DTED); files are classified by extension/content, order-independent. A sample `ankara_sample.tif` (test pattern) is included.
- Read GeoTIFF **with a pure-Python reader (Pillow), not GDAL** — Pillow decodes the raster, geo tags (ModelPixelScale/ModelTiepoint/ModelTransformation) are read from the TIFF directory. RGB/RGBA used directly, greyscale shown as-is, a single data band gets a viridis ramp.
- Texture coordinates computed from georeferencing (lon/lat -> u/v) so imagery aligns with the terrain; applied as a VTK texture on the terrain mesh (or a flat plane when there is no DTED).
- Partial overlap handled: the image is padded with a neutral border and texture coords are clamped, so terrain outside the imagery footprint shows a neutral colour rather than stretched edge pixels.
- Texture toggle: the `t` key shows/hides the imagery; `--no-texture` starts with it hidden.
- Large GeoTIFFs are downsampled on load (to <= 2048/axis by default) so memory stays bounded; geographic extent is preserved.

**Decision: no GDAL (pure-Python GeoTIFF), via Pillow** — already a dependency (used for screenshots), so no new requirement and nothing extra to bundle.

**Acceptance criteria — met**
- Imagery aligns with terrain/GML: georef is unit-tested (quadrant colours sampled at known lon/lat), texture orientation is guarded (no vertical flip — the inner top-left texel is the source north-west pixel), and verified visually top-down (N=red/S=blue/W-tinted) and over the real terrain.
- Large GeoTIFFs load via downsampling (tested: 3000x2400 -> capped at 512, extent preserved).

**Code added:** `geotiff.py` (`load_geotiff`/`write_geotiff`, `GeoImage`); `viewer.py` texture helpers (`_build_texture`, `_texture_coords`, `_flat_plane`) + `toggle_texture` and the `t` key; `cli.py` classifies a third input and builds the `GeoImage`; `tests/test_v04.py`.

**Follow-up (triggered by a real Sentinel-2 tile): compressed reader + UTM reprojection.**
A real Sentinel-2 band (`T36TVK_..._B04_10m.tif`) exposed two gaps: (1) it is DEFLATE-compressed/tiled, which Pillow can't decode, and (2) it is in UTM zone 36N, not lon/lat. Both are now handled:
- `geotiff.py` reads via **`tifffile` + `imagecodecs`** when available (compression/tiling/BigTIFF), falling back to Pillow for simple files, and detects the CRS from the GeoKeys (geographic vs WGS84/UTM).
- `reproject.py` adds pure-Python **UTM↔WGS84** (Transverse Mercator, accurate to ~1e-10° in round-trip) and `reproject_to_lonlat()`, which resamples a UTM image onto the lon/lat terrain/GML extent. The CLI reprojects automatically.
This pulls part of v0.5's CRS work forward. Verified: the real Sentinel-2 tile reads, reprojects from UTM 36N, and drapes aligned over the Ankara terrain. Deps `tifffile`/`imagecodecs` are optional (Pillow fallback) and added to `gml_editor.spec`.

---

## v0.5: CRS Robustness and Performance

**Goal:** Make it behave on real, messy data.

**Scope**
- Reproject all three inputs into one working CRS (default: the DTED CRS, normally WGS84; consider a local metric projection for correct proportions). *Partly done in v0.4: UTM GeoTIFF -> lon/lat (`reproject.py`). Remaining: reproject GML/DTED themselves, and non-UTM projected CRSs.*
- Honor axis order differences (lat/lon vs lon/lat) in GML.
- Mesh decimation or level of detail for large DTED tiles.
- Texture size limiting and mipmapping.
- Progress indicator during loading.
- Clear errors for missing CRS, non-overlapping extents, and unsupported geometry.

**Acceptance criteria**
- Mixed-CRS test set displays aligned.
- Interaction stays smooth (target 30+ FPS) on a typical Level 2 dataset.

---

## v1.0: Packaging and Release

**Scope**
- Package as a single Windows folder or `.exe` with PyInstaller (bundle GDAL and PROJ data directories, and set `PROJ_LIB` and `GDAL_DATA` at startup).
- Finalize command-line help and error messages.
- Keyboard shortcut summary shown with `F1` or in a status bar.
- Smoke test on a clean Windows machine with no Python installed.
- Short README with usage and supported formats.

**Acceptance criteria**
- Runs on a clean Windows install with the documented command line.
- Full workflow (open, navigate, delete, undo, export) works on the release build.

---

## Cross-Cutting Concerns

- **Testing:** keep a small fixed test dataset per version (tiny GML, one DTED tile, one GeoTIFF) and a manual checklist for the interaction flow. Unit-test the undo stack and the export logic.
- **Separation of concerns:** keep loaders, data model (features plus undo stack), and rendering in separate modules so each version only adds to them.
- **Scope control:** features not in the original requirements (redo, segment-level editing, multi-select, drawing new lines) stay out unless explicitly promoted into a version.

## Open Questions

1. Should delete act on whole features or individual segments? (Plan assumes whole features.)
2. Should exported GML contain Z values, or keep the original 2D coordinates?
3. Is a menu or toolbar needed, or are keyboard shortcuts alone sufficient?
4. What is the typical size of the DTED and GeoTIFF inputs?
