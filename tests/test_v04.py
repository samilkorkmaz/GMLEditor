"""v0.4 tests: GeoTIFF reader, georeferencing/alignment, texture coords,
partial overlap, and an off-screen textured render.

Run:  python -m tests.test_v04   (from the project root)
"""

import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gml_editor.gml_loader import load_gml  # noqa: E402
from gml_editor.geotiff import load_geotiff, write_geotiff, GeoTIFFError  # noqa: E402

SAMPLE = os.path.join(ROOT, "ankara_sample.gml")

# A GeoTIFF covering the GML extent with distinct colours per quadrant so
# alignment can be checked by position.
GT_WEST, GT_NORTH = 32.76, 39.943
GT_DX = GT_DY = 0.0005


def _make_geotiff(path, w=200, h=160):
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[: h // 2, : w // 2] = (220, 40, 40)    # NW red
    rgb[: h // 2, w // 2:] = (40, 180, 40)     # NE green
    rgb[h // 2:, : w // 2] = (40, 80, 220)     # SW blue
    rgb[h // 2:, w // 2:] = (230, 210, 40)     # SE yellow
    write_geotiff(path, rgb, GT_WEST, GT_NORTH, GT_DX, GT_DY)
    return rgb


def test_geotiff_roundtrip_and_georef():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "img.tif")
        _make_geotiff(p, 200, 160)
        g = load_geotiff(p)
        assert (g.height, g.width) == (160, 200), (g.height, g.width)
        assert abs(g.west - GT_WEST) < 1e-9 and abs(g.north - GT_NORTH) < 1e-9
        assert abs(g.dx - GT_DX) < 1e-12 and abs(g.dy - GT_DY) < 1e-12
        # Extent derived correctly.
        assert abs(g.east - (GT_WEST + 200 * GT_DX)) < 1e-9
        assert abs(g.south - (GT_NORTH - 160 * GT_DY)) < 1e-9
    print("test_geotiff_roundtrip_and_georef: OK  extent=%s" % (g.extent,))


def test_geotiff_alignment():
    # The colour sampled at a known lon/lat must match the quadrant placed there.
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "img.tif")
        _make_geotiff(p, 200, 160)
        g = load_geotiff(p)
        cx = (g.west + g.east) / 2
        cy = (g.south + g.north) / 2
        q = 0.25
        nw = g.sample_rgb(g.west + q * (g.east - g.west), g.south + (1 - q) * (g.north - g.south))
        ne = g.sample_rgb(g.west + (1 - q) * (g.east - g.west), g.south + (1 - q) * (g.north - g.south))
        sw = g.sample_rgb(g.west + q * (g.east - g.west), g.south + q * (g.north - g.south))
        se = g.sample_rgb(g.west + (1 - q) * (g.east - g.west), g.south + q * (g.north - g.south))
        assert nw == (220, 40, 40), nw
        assert ne == (40, 180, 40), ne
        assert sw == (40, 80, 220), sw
        assert se == (230, 210, 40), se
    print("test_geotiff_alignment: OK  (NW/NE/SW/SE quadrants match)")


def test_downsample_bounds_memory():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "big.tif")
        _make_geotiff(p, 3000, 2400)
        g = load_geotiff(p, max_dim=512)
        assert max(g.height, g.width) <= 512, (g.height, g.width)
        # Geographic extent preserved despite the downsample.
        assert abs(g.east - (GT_WEST + 3000 * GT_DX)) < 1e-6
        assert abs(g.south - (GT_NORTH - 2400 * GT_DY)) < 1e-6
    print("test_downsample_bounds_memory: OK  (%dx%d from 2400x3000)" % (g.height, g.width))


def test_not_a_geotiff_errors():
    with tempfile.TemporaryDirectory() as tmp:
        # A plain (non-geo) TIFF has no geo tags -> clear error.
        from PIL import Image
        p = os.path.join(tmp, "plain.tif")
        Image.fromarray(np.zeros((10, 10, 3), np.uint8), "RGB").save(p)
        try:
            load_geotiff(p)
        except GeoTIFFError as exc:
            print("test_not_a_geotiff_errors: OK  (%s)" % exc)
            return
    raise AssertionError("expected GeoTIFFError for a TIFF with no geo tags")


def test_texture_coords_and_overlap():
    from gml_editor.viewer import _texture_coords, _build_texture

    class _GI:  # minimal stand-in with an extent
        pass

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "img.tif")
        _make_geotiff(p, 100, 100)
        g = load_geotiff(p)
        tex, ext = _build_texture(g, pad_px=2)
        w, e, s, n = ext
        # Orientation guard: the texture is NOT vertically flipped, so the inner
        # top-left texel is the source image's north-west pixel (row 0, col 0).
        arr = tex.to_array()
        assert tuple(arr[2, 2]) == tuple(int(v) for v in g.rgb[0, 0]), \
            (tuple(arr[2, 2]), tuple(g.rgb[0, 0]))
        # A point at the GeoTIFF centre maps near (0.5, 0.5).
        mid = np.array([[(g.west + g.east) / 2, (g.south + g.north) / 2, 0.0]])
        uv = _texture_coords(mid, ext)[0]
        assert abs(uv[0] - 0.5) < 0.05 and abs(uv[1] - 0.5) < 0.05, uv
        # Points well outside the imagery clamp to the [0,1] border (neutral).
        far = np.array([[g.west - 10, g.south - 10, 0.0], [g.east + 10, g.north + 10, 0.0]])
        uvf = _texture_coords(far, ext)
        assert uvf.min() == 0.0 and uvf.max() == 1.0
    print("test_texture_coords_and_overlap: OK")


def test_offscreen_textured_render():
    import pyvista as pv
    pv.OFF_SCREEN = True
    from gml_editor.viewer import GmlEditorView
    from gml_editor.dted import load_dted, write_dted
    from gml_editor.terrain import Terrain

    scene = load_gml(SAMPLE)
    with tempfile.TemporaryDirectory() as tmp:
        # terrain
        d = 3.0 / 3600.0
        cols = np.arange(181); rows = np.arange(121)
        LON, LAT = np.meshgrid(32.75 + cols * d, 39.85 + rows * d)
        Z = 850 + 300 * np.exp(-(((LON - 32.84) ** 2 + (LAT - 39.92) ** 2) / 0.002))
        dp = os.path.join(tmp, "t.dt1")
        write_dted(dp, Z, 32.75, 39.85, 3.0, 3.0)
        terrain = Terrain(load_dted(dp), 111320.0, vexag=30.0)
        # imagery
        gp = os.path.join(tmp, "img.tif")
        _make_geotiff(gp, 300, 240)
        geo = load_geotiff(gp)

        view = GmlEditorView(scene, vexag=30.0, off_screen=True, terrain=terrain, geoimage=geo)
        assert view._texture is not None and view._textured
        shot = os.path.join(tmp, "tex.png")
        view.plotter.screenshot(shot)
        assert os.path.getsize(shot) > 0
        # Toggle hides/shows texture without error.
        view.toggle_texture()
        assert view._textured is False
        view.toggle_texture()
        assert view._textured is True
        # Editing still works with imagery present.
        bld = next(f for f in view.session.features if f.geom_type == "Polygon")
        view.select_feature(bld)
        view.delete_selected()
        assert len(view.session.features) == scene.feature_count - 1
        view.plotter.close()
    print("test_offscreen_textured_render: OK")


def test_utm_roundtrip():
    from gml_editor.reproject import lonlat_to_utm, utm_to_lonlat, epsg_to_utm
    assert epsg_to_utm(32636) == (36, True)
    assert epsg_to_utm(32736) == (36, False)
    assert epsg_to_utm(4326) is None
    # Round-trip a spread of points to sub-micro-degree accuracy.
    for lon, lat in [(32.85, 39.93), (33.0, 40.0), (31.9, 39.7)]:
        e, n = lonlat_to_utm(lon, lat, 36, True)
        lo, la = utm_to_lonlat(e, n, 36, True)
        assert abs(float(lo) - lon) < 1e-7 and abs(float(la) - lat) < 1e-7, (lon, lat, lo, la)
    print("test_utm_roundtrip: OK")


def test_crs_classification():
    from gml_editor.geotiff import _crs_fields, GeoTIFFError
    assert _crs_fields(4326, 32.0, 40.0, 0.001, 0.001)["is_geographic"] is True
    utm = _crs_fields(32636, 400000, 4450000, 10, 10)
    assert utm["is_geographic"] is False and utm["utm_zone"] == 36 and utm["utm_northern"] is True
    assert _crs_fields(32736, 400000, 1550000, 10, 10)["utm_northern"] is False
    # No CRS but degree-range coords -> geographic.
    assert _crs_fields(None, 32.0, 40.0, 0.001, 0.001)["is_geographic"] is True
    # No CRS with metre-range coords, or an unsupported projected EPSG -> error.
    for args in [(None, 400000, 4450000, 10, 10), (3857, 0, 0, 10, 10)]:
        try:
            _crs_fields(*args)
            raise AssertionError("expected GeoTIFFError for %r" % (args,))
        except GeoTIFFError:
            pass
    print("test_crs_classification: OK")


def test_reproject_alignment():
    from gml_editor.geotiff import GeoImage
    from gml_editor.reproject import utm_to_lonlat, reproject_to_lonlat

    # A UTM image (zone 36N) with a distinctive red block.
    W = H = 120
    rgb = np.full((H, W, 3), 10, np.uint8)
    rgb[40:60, 70:90] = (240, 30, 30)
    west, north, dx, dy = 400000.0, 4450000.0, 10.0, 10.0
    src = GeoImage(rgb, west, north, dx, dy, is_geographic=False,
                   crs_epsg=32636, utm_zone=36, utm_northern=True)

    # lon/lat target covering the whole source footprint.
    corners = [(west, north), (west + W * dx, north),
               (west, north - H * dy), (west + W * dx, north - H * dy)]
    lls = [utm_to_lonlat(e, n, 36, True) for e, n in corners]
    lons = [float(a) for a, _ in lls]; lats = [float(b) for _, b in lls]
    target = (min(lons), max(lons), min(lats), max(lats))

    out = reproject_to_lonlat(src, target, out_max_dim=300)
    assert out.is_geographic and out.crs_epsg == 4326
    # The centre of the red block (UTM 400800, 4449500) must be red at its lon/lat.
    lon, lat = (float(v) for v in utm_to_lonlat(400800.0, 4449500.0, 36, True))
    assert out.sample_rgb(lon, lat) == (240, 30, 30), out.sample_rgb(lon, lat)
    # A corner far outside maps to the neutral fill.
    assert out.sample_rgb(min(lons) - 1, min(lats) - 1) == (58, 62, 68)
    print("test_reproject_alignment: OK")


if __name__ == "__main__":
    test_utm_roundtrip()
    test_crs_classification()
    test_reproject_alignment()
    test_geotiff_roundtrip_and_georef()
    test_geotiff_alignment()
    test_downsample_bounds_memory()
    test_not_a_geotiff_errors()
    test_texture_coords_and_overlap()
    test_offscreen_textured_render()
    print("\nALL v0.4 TESTS PASSED")
