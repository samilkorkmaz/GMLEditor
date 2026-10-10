"""Command-line entry point for the GML Editor.

v0.1 usage:  ``python -m gml_editor <path-to-gml>``
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .gml_loader import GMLError, load_gml

log = logging.getLogger("gml_editor")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gml_editor",
        description="3D Terrain GML Editor (v0.1: GML display only).",
    )
    parser.add_argument("gml", help="Path to a GML file containing line geometry.")
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
        scene = load_gml(args.gml)
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
        from .viewer import render_scene
    except Exception as exc:  # pragma: no cover - import environment issue
        log.error("Could not initialize the 3D viewer: %s", exc)
        return 2

    try:
        if args.screenshot:
            plotter = render_scene(scene, off_screen=True, vexag=args.vexag)
            plotter.screenshot(args.screenshot)
            plotter.close()
            log.info("Wrote screenshot: %s", args.screenshot)
        else:
            render_scene(scene, vexag=args.vexag)
    except Exception as exc:  # pragma: no cover - runtime display issue
        log.error("Rendering failed: %s", exc)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
