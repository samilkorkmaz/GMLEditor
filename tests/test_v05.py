"""v0.5 tests: CRS reprojection + axis order, mixed-CRS alignment, overlap
checks, and the longitude-aspect proportion correction.

Run:  python -m tests.test_v05   (from the project root)
"""

import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gml_editor.gml_loader import load_gml, GMLError  # noqa: E402
from gml_editor.reproject import (  # noqa: E402
    lonlat_to_utm, to_wgs84_lonlat, parse_srs, CRSError,
)

# A reference line in lon/lat.
REF = [(32.80, 39.90), (32.82, 39.92), (32.85, 39.905)]


def _write_gml(path, srs, coords):
    tuples = " ".join(f"{x},{y}" for x, y in coords)
    xml = (
        '<?xml version="1.0"?>'
        '<ogr:FeatureCollection xmlns:ogr="http://ogr.maptools.org/" '
        'xmlns:gml="http://www.opengis.net/gml">'
        '<gml:featureMember><ogr:r fid="r.0"><ogr:geometryProperty>'
        f'<gml:LineString srsName="{srs}"><gml:coordinates>{tuples}</gml:coordinates>'
        '</gml:LineString></ogr:geometryProperty></ogr:r></gml:featureMember>'
        '</ogr:FeatureCollection>'
    )
    with open(path, "w") as fh:
        fh.write(xml)


def test_parse_srs_and_to_wgs84():
    assert parse_srs("EPSG:4326") == (4326, False)
    assert parse_srs("urn:ogc:def:crs:EPSG::4326") == (4326, True)   # lat,lon
    assert parse_srs("EPSG:32636") == (32636, False)
    assert parse_srs(None) == (None, False)
    # geographic passthrough; UTM converts; unsupported raises.
    x, y = to_wgs84_lonlat(32.8, 39.9, 4326)
    assert abs(float(x) - 32.8) < 1e-9 and abs(float(y) - 39.9) < 1e-9
    try:
        to_wgs84_lonlat(0, 0, 3857)
    except CRSError:
        pass
    else:
        raise AssertionError("expected CRSError for EPSG:3857")
    print("test_parse_srs_and_to_wgs84: OK")


def test_mixed_crs_aligns():
    """The headline: the same line in lon/lat and in UTM must coincide once loaded."""
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "wgs84.gml")
        b = os.path.join(tmp, "utm.gml")
        _write_gml(a, "EPSG:4326", REF)
        utm = [tuple(float(v) for v in lonlat_to_utm(lon, lat, 36, True)) for lon, lat in REF]
        _write_gml(b, "EPSG:32636", utm)
        pa = load_gml(a).features[0].parts[0]
        pb = load_gml(b).features[0].parts[0]
        assert np.allclose(pa[:, :2], pb[:, :2], atol=1e-6), (pa[:, :2], pb[:, :2])
        # ...and both equal the reference lon/lat.
        assert np.allclose(pa[:, :2], np.array(REF), atol=1e-6)
    print("test_mixed_crs_aligns: OK")


def test_axis_order_swap():
    with tempfile.TemporaryDirectory() as tmp:
        # URN geographic => lat,lon order; loader must swap to lon,lat.
        p = os.path.join(tmp, "latlon.gml")
        _write_gml(p, "urn:ogc:def:crs:EPSG::4326", [(lat, lon) for lon, lat in REF])
        parts = load_gml(p).features[0].parts[0]
        assert np.allclose(parts[:, :2], np.array(REF), atol=1e-9), parts[:, :2]

        # Force swap via override on a lon,lat file -> becomes lat,lon.
        q = os.path.join(tmp, "forced.gml")
        _write_gml(q, "EPSG:4326", REF)
        swapped = load_gml(q, swap_xy=True).features[0].parts[0]
        assert np.allclose(swapped[:, 0], [lat for _, lat in REF], atol=1e-9)
    print("test_axis_order_swap: OK")


def test_unsupported_crs_errors():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "merc.gml")
        _write_gml(p, "EPSG:3857", [(3.6e6, 4.8e6), (3.6e6, 4.9e6)])
        try:
            load_gml(p)
        except GMLError as exc:
            print("test_unsupported_crs_errors: OK  (%s)" % str(exc)[:60])
            return
    raise AssertionError("expected GMLError for unsupported CRS")


def test_extent_overlap_helper():
    from gml_editor.cli import _extents_overlap
    assert _extents_overlap((0, 1, 0, 1), (0.5, 1.5, 0.5, 1.5)) is True
    assert _extents_overlap((0, 1, 0, 1), (2, 3, 2, 3)) is False
    print("test_extent_overlap_helper: OK")


def test_non_overlapping_dted_errors():
    from gml_editor import cli
    from gml_editor.dted import write_dted
    with tempfile.TemporaryDirectory() as tmp:
        far = os.path.join(tmp, "far.dt1")
        write_dted(far, np.full((20, 20), 500.0), 10.0, 10.0, 3.0, 3.0)  # lon10/lat10
        rc = cli.main([os.path.join(ROOT, "ankara_sample.gml"), far])
        assert rc == 1, rc
    print("test_non_overlapping_dted_errors: OK")


def test_aspect_proportion_correction():
    import math
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import GmlEditorView
    scene = load_gml(os.path.join(ROOT, "ankara_sample.gml"))
    view = GmlEditorView(scene, vexag=50.0, off_screen=True)
    b = scene.bounds()
    lat0 = 0.5 * (b[2] + b[3])
    assert abs(view._kx - math.cos(math.radians(lat0))) < 1e-9
    # The x-aspect scale is actually applied to the drawn actor.
    assert abs(view._line_actor.scale[0] - view._kx) < 1e-9
    assert abs(view._line_actor.scale[1] - 1.0) < 1e-9
    # Mesh coordinates themselves stay true lon/lat (only the actor is scaled).
    assert view._line_mesh.points[:, 0].max() <= b[1] + 1e-9
    view.plotter.close()
    print("test_aspect_proportion_correction: OK  (kx=%.4f)" % view._kx)


if __name__ == "__main__":
    test_parse_srs_and_to_wgs84()
    test_mixed_crs_aligns()
    test_axis_order_swap()
    test_unsupported_crs_errors()
    test_extent_overlap_helper()
    test_non_overlapping_dted_errors()
    test_aspect_proportion_correction()
    print("\nALL v0.5 TESTS PASSED")
