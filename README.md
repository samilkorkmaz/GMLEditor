# 3D Terrain GML Editor

A Windows tool to view (and, in later versions, edit) GML line and polygon data
in 3D. **Current version: v0.1 — GML display only.** See
[version_plan.md](version_plan.md) for the full roadmap.

## Requirements

- Python 3.10+
- `numpy`, `pyvista`, `pyvistaqt` (VTK is pulled in by PyVista)

```
pip install --user pyvista pyvistaqt numpy
```

## Usage

```
python -m gml_editor <path-to-gml> [--vexag FACTOR]
```

Example:

```
python -m gml_editor ankara_sample.gml --vexag 50
```

A 3D window opens with the data auto-fitted to view. Navigate with the mouse:

- **Left drag** — rotate
- **Mouse wheel** — zoom
- **Middle drag / Shift+Left drag** — pan

Feature count, per-layer counts, vertex count, and CRS are logged to the console.

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
```

Covers loader correctness, error handling (missing / empty / malformed /
geometry-less files), and off-screen rendering.

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
  gml_loader.py   load_gml(), GMLError
  viewer.py       mesh building, camera, render_scene
  cli.py          command line, logging
  __main__.py     entry point (python -m gml_editor)
tests/
  test_v01.py     v0.1 smoke tests
ankara_sample.gml Sample data (Ankara roads + buildings, EPSG:4326)
version_plan.md   Version roadmap
```
