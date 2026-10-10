"""Pure-Python GeoTIFF reader (v0.4).

Reads a GeoTIFF without GDAL. ``tifffile`` (+ ``imagecodecs``) is used when
available — it handles compressed/tiled/BigTIFF rasters such as GDAL- and
Sentinel-produced GeoTIFFs — falling back to Pillow for simple TIFFs. Geo tags
(ModelPixelScale / ModelTiepoint / ModelTransformation) give the georeferencing;
the CRS is taken from the GeoKeys (geographic lon/lat, or WGS84 UTM).

A projected (UTM) image is returned in its native metres; :mod:`gml_editor.reproject`
resamples it to lon/lat to align with the GML/DTED. Large rasters are downsampled
on load so memory stays bounded.

Public entry point: :func:`load_geotiff` -> :class:`GeoImage`. :func:`write_geotiff`
writes a minimal north-up geographic GeoTIFF (used by the tests).
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image
from PIL.TiffImagePlugin import ImageFileDirectory_v2

from .reproject import epsg_to_utm

# GeoTIFF tag numbers.
_TAG_PIXEL_SCALE = 33550
_TAG_TIEPOINT = 33922
_TAG_TRANSFORM = 34264

Image.MAX_IMAGE_PIXELS = None  # we downsample ourselves; don't trip the bomb guard


class GeoTIFFError(Exception):
    """Raised for a missing, unreadable, or non-georeferenced TIFF."""


class GeoImage:
    """A raster with georeferencing, in whatever CRS it was read in.

    ``rgb`` is ``(H, W, 3)`` uint8 with row 0 at the north/top edge. ``west`` /
    ``north`` are the top-left pixel corner, ``dx`` / ``dy`` the (positive) pixel
    sizes — in degrees when geographic, in metres when UTM.
    """

    def __init__(self, rgb, west, north, dx, dy, *, is_geographic=True,
                 crs_epsg=None, utm_zone=None, utm_northern=True):
        self.rgb = rgb
        self.height, self.width = rgb.shape[:2]
        self.west = west
        self.north = north
        self.dx = dx
        self.dy = dy
        self.is_geographic = is_geographic
        self.crs_epsg = crs_epsg
        self.utm_zone = utm_zone
        self.utm_northern = utm_northern

    @property
    def east(self):
        return self.west + self.width * self.dx

    @property
    def south(self):
        return self.north - self.height * self.dy

    @property
    def extent(self):
        """(west, east, south, north)."""
        return (self.west, self.east, self.south, self.north)

    def sample_rgb(self, lon, lat):
        """Nearest-pixel RGB at a coordinate (clamped), for alignment checks."""
        col = int(np.clip((lon - self.west) / self.dx, 0, self.width - 1))
        row = int(np.clip((self.north - lat) / self.dy, 0, self.height - 1))
        return tuple(int(v) for v in self.rgb[row, col])


# -- array -> displayable RGB --------------------------------------------------

def _stretch_band(band: np.ndarray) -> np.ndarray:
    """Percentile-stretch a single data band to a uint8 greyscale image."""
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        return np.zeros(band.shape, np.uint8)
    lo, hi = np.percentile(finite, (2, 98))
    if hi <= lo:
        hi = lo + 1
    out = np.clip((band - lo) / (hi - lo), 0, 1)
    return (out * 255).astype(np.uint8)


def _array_to_rgb(arr: np.ndarray) -> np.ndarray:
    """Turn a decoded raster array into (H, W, 3) uint8."""
    if arr.ndim == 3 and arr.shape[2] >= 3:
        chans = arr[:, :, :3]
        if chans.dtype == np.uint8:
            return np.ascontiguousarray(chans)
        return np.stack([_stretch_band(chans[:, :, i].astype(np.float64)) for i in range(3)], axis=2)
    band = arr[:, :, 0] if arr.ndim == 3 else arr
    g = _stretch_band(band.astype(np.float64))
    return np.repeat(g[:, :, None], 3, axis=2)


def _downsample(arr: np.ndarray, max_dim: int):
    """Stride-subsample so the largest axis is <= max_dim. Returns (arr, step)."""
    h, w = arr.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / float(max_dim))))
    return (arr[::step, ::step], step) if step > 1 else (arr, 1)


# -- georeferencing / CRS ------------------------------------------------------

def _georef(pixel_scale, tiepoint, transform):
    """Return (west, north, dx, dy) from GeoTIFF model tags (any of the three)."""
    if pixel_scale is not None and tiepoint is not None:
        sx, sy = float(pixel_scale[0]), float(pixel_scale[1])
        i, j, x, y = float(tiepoint[0]), float(tiepoint[1]), float(tiepoint[3]), float(tiepoint[4])
        return x - i * sx, y + j * sy, sx, sy
    if transform is not None:
        m = [float(v) for v in transform]
        if abs(m[1]) > 1e-12 or abs(m[4]) > 1e-12:
            raise GeoTIFFError("Rotated GeoTIFF (ModelTransformation) is not supported")
        return m[3], m[7], abs(m[0]), abs(m[5])
    raise GeoTIFFError("TIFF has no GeoTIFF georeferencing tags")


def _crs_fields(epsg, west, north, dx, dy):
    """Classify the CRS -> dict of GeoImage crs kwargs, or raise if unsupported."""
    if epsg in (4326, 4269, None):
        looks_geographic = (-180.5 <= west <= 180.5 and -90.5 <= north <= 90.5
                            and 0 < dx < 1 and 0 < dy < 1)
        if epsg in (4326, 4269) or looks_geographic:
            return dict(is_geographic=True, crs_epsg=epsg or 4326)
        raise GeoTIFFError(
            f"GeoTIFF has no CRS and its coordinates (origin {west:.1f},{north:.1f}; "
            f"pixel {dx:g},{dy:g}) are not lon/lat degrees; cannot georeference it."
        )
    utm = epsg_to_utm(epsg)
    if utm is not None:
        return dict(is_geographic=False, crs_epsg=epsg, utm_zone=utm[0], utm_northern=utm[1])
    raise GeoTIFFError(
        f"Projected CRS EPSG:{epsg} is not supported yet (only geographic lon/lat "
        f"and WGS84/UTM). Reproject the file to EPSG:4326 or a UTM zone first."
    )


def _epsg_from_geokeys(gm) -> "int | None":
    for key in ("ProjectedCSTypeGeoKey", "GeographicTypeGeoKey"):
        if key in gm:
            val = gm[key]
            try:
                return int(getattr(val, "value", val))
            except (TypeError, ValueError):
                return None
    return None


# -- readers -------------------------------------------------------------------

def _load_tifffile(path, max_dim):
    import tifffile
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]

        def tagval(num):
            t = page.tags.get(num)
            return t.value if t is not None else None

        # Read the model tags directly (geotiff_metadata needs a GeoKeyDirectory,
        # which minimal/hand-written GeoTIFFs may omit).
        west, north, dx, dy = _georef(tagval(_TAG_PIXEL_SCALE), tagval(_TAG_TIEPOINT),
                                      tagval(_TAG_TRANSFORM))
        gm = tf.geotiff_metadata or {}
        arr = tf.asarray()
    arr, step = _downsample(arr, max_dim)
    dx, dy = dx * step, dy * step
    crs = _crs_fields(_epsg_from_geokeys(gm), west, north, dx, dy)
    return GeoImage(_array_to_rgb(arr), west, north, dx, dy, **crs)


def _load_pil(path, max_dim):
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:
        raise GeoTIFFError(
            f"Could not decode {os.path.basename(path)} with Pillow "
            f"({type(exc).__name__}); it is likely compressed/tiled. Install "
            f"'tifffile' and 'imagecodecs' for broader GeoTIFF support."
        ) from exc
    tags = getattr(img, "tag_v2", None)
    if not tags:
        raise GeoTIFFError(f"Not a GeoTIFF (no TIFF tags): {path}")
    west, north, dx, dy = _georef(tags.get(_TAG_PIXEL_SCALE), tags.get(_TAG_TIEPOINT),
                                  tags.get(_TAG_TRANSFORM))
    arr = np.asarray(img)
    arr, step = _downsample(arr, max_dim)
    dx, dy = dx * step, dy * step
    # Pillow does not expose GeoKeys easily; classify by coordinate range.
    crs = _crs_fields(None, west, north, dx, dy)
    return GeoImage(_array_to_rgb(arr), west, north, dx, dy, **crs)


def load_geotiff(path: str, max_dim: int = 4096) -> GeoImage:
    """Read a GeoTIFF into a :class:`GeoImage` (native CRS), downsampled to ``max_dim``."""
    if not os.path.isfile(path):
        raise GeoTIFFError(f"File not found: {path}")
    try:
        import tifffile  # noqa: F401
        has_tifffile = True
    except ImportError:
        has_tifffile = False
    return _load_tifffile(path, max_dim) if has_tifffile else _load_pil(path, max_dim)


def write_geotiff(path: str, rgb: np.ndarray, west: float, north: float,
                  dx: float, dy: float) -> None:
    """Write a minimal north-up geographic GeoTIFF (RGB) for tests."""
    ifd = ImageFileDirectory_v2()
    ifd.tagtype[_TAG_PIXEL_SCALE] = 12  # DOUBLE
    ifd[_TAG_PIXEL_SCALE] = (float(dx), float(dy), 0.0)
    ifd.tagtype[_TAG_TIEPOINT] = 12
    ifd[_TAG_TIEPOINT] = (0.0, 0.0, 0.0, float(west), float(north), 0.0)
    Image.fromarray(rgb.astype(np.uint8), "RGB").save(path, tiffinfo=ifd)
