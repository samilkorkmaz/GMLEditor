"""Command-line entry point for the GML Editor.

Usage:  ``python -m gml_editor <gml> [<dted>] [--vexag N] [--screenshot PATH]``

Opens an interactive editor: left-click to select a feature, Delete to remove
it, Ctrl+Z / Ctrl+Y to undo / redo, Ctrl+S to export. When a DTED file is also
given (v0.3), the GML is draped onto the elevation surface.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from .gml_loader import GMLError, load_gml

log = logging.getLogger("gml_editor")

_DTED_EXTS = (".dt0", ".dt1", ".dt2", ".dted")
_GML_EXTS = (".gml", ".xml")
_TIFF_EXTS = (".tif", ".tiff", ".gtif", ".gtiff")


def _sniff(path: str) -> str:
    """Classify a file as 'gml', 'dted', or 'geotiff' by extension/content."""
    low = path.lower()
    if low.endswith(_DTED_EXTS):
        return "dted"
    if low.endswith(_TIFF_EXTS):
        return "geotiff"
    if low.endswith(_GML_EXTS):
        return "gml"
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return "gml"
    if head[:3] == b"UHL":                       # DTED User Header Label
        return "dted"
    if head[:4] in (b"II*\x00", b"MM\x00*"):     # TIFF magic (LE / BE)
        return "geotiff"
    return "gml"                                 # GML/XML starts with '<'


def _classify_inputs(paths):
    """Split paths into (gml, dted, geotiff). Raises ValueError on misuse."""
    buckets = {"gml": [], "dted": [], "geotiff": []}
    for p in paths:
        buckets[_sniff(p)].append(p)
    if len(buckets["gml"]) != 1:
        raise ValueError("Exactly one GML file is required")
    if len(buckets["dted"]) > 1:
        raise ValueError("At most one DTED file is supported")
    if len(buckets["geotiff"]) > 1:
        raise ValueError("At most one GeoTIFF file is supported")
    return (buckets["gml"][0],
            buckets["dted"][0] if buckets["dted"] else None,
            buckets["geotiff"][0] if buckets["geotiff"] else None)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gml_editor",
        description="3D Terrain GML Editor (v0.5: editing + DTED terrain + GeoTIFF "
                    "imagery + CRS reprojection).",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="FILE",
        help="A GML file, and optionally a DTED file (terrain) and/or a GeoTIFF "
             "file (imagery) to drape it onto. Order-independent; classified by "
             "extension/content.",
    )
    parser.add_argument(
        "--vexag",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help=(
            "Vertical exaggeration for any z/height in the data. "
            "0 = flat 2D map, 1 = true geographic scale (default), "
            ">1 exaggerates relief (e.g. 30-50 to make small building heights "
            "visible on a city-scale map)."
        ),
    )
    parser.add_argument(
        "--screenshot",
        metavar="PATH",
        default=None,
        help=(
            "Render off-screen to the given PNG and exit instead of opening a "
            "window. Useful on headless machines or for quick previews."
        ),
    )
    parser.add_argument(
        "--full-terrain",
        action="store_true",
        help=(
            "Show the entire DTED tile. By default the terrain is cropped to the "
            "GML extent (plus a small margin) so the geometry isn't a speck on a "
            "full 1-degree tile."
        ),
    )
    parser.add_argument(
        "--no-texture",
        action="store_true",
        help="Load the GeoTIFF but start with the texture hidden (toggle with 't').",
    )
    parser.add_argument(
        "--gml-crs",
        metavar="EPSG",
        default=None,
        help="Override the GML's CRS (e.g. EPSG:32636) when its srsName is wrong "
             "or missing. Reprojected to lon/lat for display.",
    )
    parser.add_argument(
        "--swap-xy",
        action="store_true",
        help="Force-swap the GML's coordinate order (use if lat/lon appears "
             "mirrored). Overrides axis-order detection.",
    )
    parser.add_argument(
        "--max-terrain-dim",
        type=int,
        default=400,
        metavar="N",
        help="Max terrain-mesh resolution per axis (default 400). Lower = faster.",
    )
    parser.add_argument(
        "--max-texture-dim",
        type=int,
        default=2048,
        metavar="N",
        help="Max GeoTIFF texture resolution per axis (default 2048).",
    )
    parser.add_argument(
        "--arrow",
        nargs=2,
        type=float,
        default=None,
        metavar=("AZ", "EL"),
        help="Draw a red direction arrow pointing to the middle of the ground, "
             "oriented by AZ (azimuth degrees clockwise from True North) and EL "
             "(elevation degrees above the horizon). Double-click the scene to "
             "move the arrow's tip (angles stay fixed).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def _extents_overlap(a, b) -> bool:
    """True if two (west, east, south, north) boxes overlap."""
    aw, ae, as_, an = a
    bw, be, bs, bn = b
    return not (ae < bw or be < aw or an < bs or bn < as_)


def _gml_extent(scene):
    b = scene.bounds()
    return None if b is None else (b[0], b[1], b[2], b[3])


def _log_summary(scene) -> None:
    log.info("Loaded %s", scene.source_path)
    src = scene.crs or "not declared"
    if scene.source_epsg and scene.source_epsg != 4326:
        log.info("CRS: %s (EPSG:%d) -> reprojected to %s", src, scene.source_epsg, scene.working_crs)
    else:
        log.info("CRS: %s", src)
    log.info("Features: %d", scene.feature_count)
    for layer, count in sorted(scene.layer_counts().items()):
        log.info("  %s: %d", layer, count)
    log.info("Total line vertices: %d", scene.vertex_count)


def main(argv=None) -> int:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        gml_path, dted_path, geotiff_path = _classify_inputs(args.inputs)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    try:
        scene = load_gml(gml_path, src_crs=args.gml_crs,
                         swap_xy=(True if args.swap_xy else None))
    except GMLError as exc:
        log.error("%s", exc)
        return 1

    _log_summary(scene)

    zmax_m = 0.0
    bounds = scene.bounds()
    if bounds is not None:
        zmax_m = max(abs(bounds[4]), abs(bounds[5]))
    if zmax_m > 0:
        log.info(
            "Z/height present (max %.3g source units); vertical exaggeration: %gx",
            zmax_m, args.vexag,
        )
        if args.vexag == 0:
            log.info("  (--vexag 0: heights flattened; pass e.g. --vexag 30 to see them)")
    else:
        log.info("No z/height in data; rendering flat.")

    # Import the viewer lazily so the summary/error paths don't pay the VTK
    # import cost and so --version etc. work in headless environments.
    try:
        from .viewer import _metres_per_horizontal_unit, render_scene
    except Exception as exc:  # pragma: no cover - import environment issue
        log.error("Could not initialize the 3D viewer: %s", exc)
        return 2

    terrain = None
    if dted_path is not None:
        try:
            from .dted import load_dted
            from .terrain import Terrain
            log.info("Reading DTED %s ...", os.path.basename(dted_path))
            grid = load_dted(dted_path)
        except Exception as exc:
            log.error("Could not read DTED %s: %s", dted_path, exc)
            return 1
        full_dims = (grid.nrow, grid.ncol)
        gml_ext = _gml_extent(scene)
        if gml_ext is not None and not _extents_overlap(
                (grid.lon0, grid.lon1, grid.lat0, grid.lat1), gml_ext):
            log.error(
                "DTED tile (lon %.3f..%.3f lat %.3f..%.3f) does not overlap the GML "
                "(lon %.3f..%.3f lat %.3f..%.3f); wrong tile for this area?",
                grid.lon0, grid.lon1, grid.lat0, grid.lat1, *gml_ext)
            return 1
        bounds = scene.bounds()
        if not args.full_terrain and bounds is not None:
            grid = grid.subset(bounds[0], bounds[2], bounds[1], bounds[3])
        mpu = _metres_per_horizontal_unit(scene.working_crs)
        terrain = Terrain(grid, mpu, args.vexag, max_dim=args.max_terrain_dim)
        cropped = "" if args.full_terrain else " (cropped to GML from %dx%d)" % full_dims
        log.info(
            "DTED: %s  %dx%d grid%s, extent lon %.4f..%.4f lat %.4f..%.4f, "
            "elev %.0f..%.0f m, %d voids filled",
            os.path.basename(dted_path), grid.nrow, grid.ncol, cropped,
            grid.lon0, grid.lon1, grid.lat0, grid.lat1,
            grid.zmin, grid.zmax, grid.void_count,
        )

    geoimage = None
    if geotiff_path is not None:
        try:
            from .geotiff import GeoTIFFError, load_geotiff
            mb = os.path.getsize(geotiff_path) / 1e6
            log.info("Reading GeoTIFF %s (%.0f MB) ...", os.path.basename(geotiff_path), mb)
            geoimage = load_geotiff(geotiff_path, max_dim=max(args.max_texture_dim, 1024))
        except Exception as exc:
            log.error("Could not read GeoTIFF %s: %s", geotiff_path, exc)
            return 1
        # Check the imagery actually covers the GML before building anything.
        gml_ext = _gml_extent(scene)
        if geoimage.is_geographic:
            img_ext = geoimage.extent
        else:
            from .reproject import utm_to_lonlat
            lons, lats = [], []
            for e_ in (geoimage.west, geoimage.east):
                for n_ in (geoimage.south, geoimage.north):
                    lo, la = utm_to_lonlat(e_, n_, geoimage.utm_zone, geoimage.utm_northern)
                    lons.append(float(lo)); lats.append(float(la))
            img_ext = (min(lons), max(lons), min(lats), max(lats))
        if gml_ext is not None and not _extents_overlap(img_ext, gml_ext):
            log.error("GeoTIFF footprint does not overlap the GML; nothing to drape.")
            return 1
        if not geoimage.is_geographic:
            # Projected imagery (UTM) must be resampled to lon/lat to align with
            # the GML/DTED. Use the terrain extent (already cropped to the GML)
            # when available, else the GML bounds with a small margin.
            if terrain is not None:
                g = terrain.grid
                target = (g.lon0, g.lon1, g.lat0, g.lat1)
            else:
                b = scene.bounds()
                mx = (b[1] - b[0]) * 0.05 or 0.001
                my = (b[3] - b[2]) * 0.05 or 0.001
                target = (b[0] - mx, b[1] + mx, b[2] - my, b[3] + my)
            try:
                from .reproject import reproject_to_lonlat
                zone = geoimage.utm_zone
                log.info("Reprojecting imagery from UTM zone %d to lon/lat ...", zone)
                geoimage = reproject_to_lonlat(geoimage, target, out_max_dim=args.max_texture_dim)
                log.info("Reprojected GeoTIFF from UTM zone %d to lon/lat (EPSG:4326)", zone)
            except Exception as exc:
                log.error("Could not reproject GeoTIFF: %s", exc)
                return 1
        w, e, s, n = geoimage.extent
        log.info(
            "GeoTIFF: %s  %dx%d px, extent lon %.4f..%.4f lat %.4f..%.4f",
            os.path.basename(geotiff_path), geoimage.height, geoimage.width, w, e, s, n,
        )

    texture_on = not args.no_texture
    arrow_az, arrow_el = (args.arrow if args.arrow else (None, None))
    if args.arrow:
        log.info("Direction arrow: azimuth %g deg from North, elevation %g deg above horizon",
                 arrow_az, arrow_el)
    try:
        if args.screenshot:
            plotter = render_scene(scene, off_screen=True, vexag=args.vexag,
                                   terrain=terrain, geoimage=geoimage, texture_on=texture_on,
                                   arrow_az=arrow_az, arrow_el=arrow_el)
            plotter.screenshot(args.screenshot)
            plotter.close()
            log.info("Wrote screenshot: %s", args.screenshot)
        else:
            controls = ("Controls: left-click select | Delete remove | "
                        "Ctrl+Z undo | Ctrl+Y redo | Ctrl+S export | "
                        "q / Ctrl+Q quit")
            if geoimage is not None:
                controls += " | t texture"
            controls += " | double-click move arrow"
            log.info(controls)
            files = {"gml": gml_path, "dted": dted_path, "geotiff": geotiff_path}
            try:
                from .gui import launch
                return launch(scene, vexag=args.vexag, terrain=terrain,
                              geoimage=geoimage, texture_on=texture_on,
                              arrow_az=arrow_az, arrow_el=arrow_el, files=files)
            except Exception as exc:
                log.warning("GUI panel unavailable (%s); using the basic viewer.", exc)
                render_scene(scene, vexag=args.vexag, terrain=terrain,
                             geoimage=geoimage, texture_on=texture_on,
                             arrow_az=arrow_az, arrow_el=arrow_el)
    except Exception as exc:  # pragma: no cover - runtime display issue
        log.error("Rendering failed: %s", exc)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
