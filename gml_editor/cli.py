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


def _looks_like_dted(path: str) -> bool:
    if path.lower().endswith(_DTED_EXTS):
        return True
    if path.lower().endswith(_GML_EXTS):
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    # DTED starts with the "UHL" User Header Label; GML/XML starts with '<'.
    return head[:3] == b"UHL"


def _classify_inputs(paths):
    """Split input paths into (gml_path, dted_path). Raises ValueError on misuse."""
    gml = [p for p in paths if not _looks_like_dted(p)]
    dted = [p for p in paths if _looks_like_dted(p)]
    if len(gml) != 1:
        raise ValueError("Exactly one GML file is required")
    if len(dted) > 1:
        raise ValueError("At most one DTED file is supported")
    return gml[0], (dted[0] if dted else None)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gml_editor",
        description="3D Terrain GML Editor (v0.3: GML editing + DTED terrain).",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="FILE",
        help="A GML file, and optionally a DTED file to drape it onto "
             "(order-independent; classified by extension/content).",
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
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def _log_summary(scene) -> None:
    log.info("Loaded %s", scene.source_path)
    log.info("CRS: %s", scene.crs or "not declared")
    log.info("Features: %d", scene.feature_count)
    for layer, count in sorted(scene.layer_counts().items()):
        log.info("  %s: %d", layer, count)
    log.info("Total line vertices: %d", scene.vertex_count)


def main(argv=None) -> int:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        gml_path, dted_path = _classify_inputs(args.inputs)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    try:
        scene = load_gml(gml_path)
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
            grid = load_dted(dted_path)
        except Exception as exc:
            log.error("Could not read DTED %s: %s", dted_path, exc)
            return 1
        full_dims = (grid.nrow, grid.ncol)
        bounds = scene.bounds()
        if not args.full_terrain and bounds is not None:
            grid = grid.subset(bounds[0], bounds[2], bounds[1], bounds[3])
        mpu = _metres_per_horizontal_unit(scene.crs)
        terrain = Terrain(grid, mpu, args.vexag)
        cropped = "" if args.full_terrain else " (cropped to GML from %dx%d)" % full_dims
        log.info(
            "DTED: %s  %dx%d grid%s, extent lon %.4f..%.4f lat %.4f..%.4f, "
            "elev %.0f..%.0f m, %d voids filled",
            os.path.basename(dted_path), grid.nrow, grid.ncol, cropped,
            grid.lon0, grid.lon1, grid.lat0, grid.lat1,
            grid.zmin, grid.zmax, grid.void_count,
        )

    try:
        if args.screenshot:
            plotter = render_scene(scene, off_screen=True, vexag=args.vexag, terrain=terrain)
            plotter.screenshot(args.screenshot)
            plotter.close()
            log.info("Wrote screenshot: %s", args.screenshot)
        else:
            log.info("Controls: left-click select | Delete remove | "
                     "Ctrl+Z undo | Ctrl+Y redo | Ctrl+S export | q quit")
            render_scene(scene, vexag=args.vexag, terrain=terrain)
    except Exception as exc:  # pragma: no cover - runtime display issue
        log.error("Rendering failed: %s", exc)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
