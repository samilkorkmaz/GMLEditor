# 3D Terrain GML Editor: Version Plan

**Target platform:** Windows
**Proposed stack:** Python + GDAL/OGR + PyVista (VTK), packaged with PyInstaller
**Strategy:** Start with the simplest data type (GML), get the editing loop (select, delete, undo, export) working early, then layer terrain and imagery underneath it.

---

## Version Overview

| Version | Theme | Command line |
|---|---|---|
| v0.1 | GML display only **(DONE)** | `python -m gml_editor <gml> [--vexag N]` |
| v0.2 | GML editing (select, delete, undo, export) | `app gml` |
| v0.3 | DTED terrain + GML draped | `app dted gml` |
| v0.4 | GeoTIFF texture | `app dted geotiff gml` |
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

## v0.2: GML Editing

**Goal:** Deliver the full interaction loop on the simplest data, before terrain complicates picking.

**Scope**
- Left click selects the nearest line feature (screen-space distance threshold) or building; highlight the selection.
- Click on empty space clears the selection.
- `Delete` removes the selected feature from the display.
- `Ctrl+Z` restores the most recently deleted feature (multi-level undo stack).
- Export edited GML to a new file (menu item or `Ctrl+S`, plus a default output name such as `<input>_edited.gml`). Never overwrite the input.
- Exported file preserves the original schema, attributes, and CRS.

**Design notes**
- Selection granularity: whole feature (LineString or MultiLineString), not individual segments. This keeps undo and export simple.
- Undo stack stores `(feature_id, position)` so restoration is exact.
- Export copies surviving features through OGR using the source layer definition.
- Optional: `Ctrl+Y` for redo, if cheap.

**Acceptance criteria**
- Delete then undo repeatedly returns the exact original state.
- Exported GML re-opens in QGIS or `ogrinfo` with the correct feature count, attributes, and CRS.
- Deleting all features and exporting produces a valid empty GML, or a clear message.

---

## v0.3: DTED Terrain

**Goal:** Add the elevation surface and drape the GML on it.

**Scope**
- Command line becomes: `app <dted> <gml>`.
- Read DTED Level 1 or Level 2 via GDAL into an elevation grid.
- Handle DTED void values (-32767) by filling or masking.
- Build a terrain mesh with a configurable vertical exaggeration.
- Sample terrain height at each GML vertex (bilinear interpolation) so lines sit on the surface; apply a small vertical offset to avoid z-fighting.
- Densify long GML segments before draping so lines follow the terrain between vertices.
- Preserve v0.2 editing: selection, delete, undo, and export now work in 3D.

**Acceptance criteria**
- Both DTED levels load; Level 2 does not freeze the UI.
- Lines follow terrain contours without visibly cutting through hills.
- Picking still selects the correct line from angled views.
- Exported GML is unchanged in coordinates (draping affects display only, unless Z export is chosen deliberately).

**Risks**
- Picking in 3D with perspective: fall back to projecting vertices to screen space if the library picker is unreliable for thin lines.

---

## v0.4: GeoTIFF Texture

**Goal:** Drape imagery over the terrain.

**Scope**
- Command line becomes: `app <dted> <geotiff> <gml>`.
- Read GeoTIFF (RGB, grayscale, or single-band with a simple color ramp).
- Compute texture coordinates from georeferencing so imagery aligns with the terrain.
- Handle partial overlap between the GeoTIFF and DTED extents (crop or leave untextured regions in a neutral color).
- Optional toggle to hide or show the texture.

**Acceptance criteria**
- Imagery aligns with terrain and GML lines to within one pixel at sample test points.
- Large GeoTIFFs load using overviews or downsampling rather than exhausting memory.

---

## v0.5: CRS Robustness and Performance

**Goal:** Make it behave on real, messy data.

**Scope**
- Reproject all three inputs into one working CRS (default: the DTED CRS, normally WGS84; consider a local metric projection for correct proportions).
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
