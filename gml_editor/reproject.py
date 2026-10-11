"""Pure-Python CRS reprojection between WGS84 lon/lat and UTM.

v0.4 needs this so a GeoTIFF in a projected CRS (e.g. Sentinel-2 tiles in UTM)
can be aligned with the lon/lat GML and DTED without GDAL/pyproj. The standard
Transverse Mercator series (Snyder / USGS 1395) is accurate to a few mm within a
UTM zone, which is far better than a pixel here.

Only WGS84 UTM is handled (EPSG 326xx north / 327xx south); that covers the
common projected imagery. The functions are vectorised over NumPy arrays.
"""

from __future__ import annotations

import re

import numpy as np

# Geographic (lon/lat) datums we treat as already in the working CRS.
_GEOGRAPHIC_EPSG = {4326, 4269, 4258, 4267}


class CRSError(Exception):
    """Raised for an unsupported or unparseable CRS."""


def parse_srs(srs_name):
    """Parse a GML ``srsName`` into ``(epsg, swap_axes)``.

    ``swap_axes`` is True when the file's coordinate order is (lat, lon) and must
    be swapped to the (lon/x, lat/y) order the rest of the app expects. By
    convention the OGC URN form of a geographic CRS (``urn:ogc:def:crs:EPSG::4326``)
    is lat/lon, while the short ``EPSG:4326`` form is lon/lat; projected CRSs are
    easting/northing (no swap). Returns ``(None, False)`` for an absent srsName.
    """
    if not srs_name:
        return None, False
    nums = re.findall(r"\d+", srs_name)
    epsg = int(nums[-1]) if nums else None
    is_urn = "urn:" in srs_name.lower()
    geographic = epsg in _GEOGRAPHIC_EPSG if epsg else False
    return epsg, bool(geographic and is_urn)


def is_geographic_epsg(epsg) -> bool:
    return epsg in _GEOGRAPHIC_EPSG


def to_wgs84_lonlat(x, y, epsg):
    """Convert coordinates in CRS ``epsg`` (x=lon/easting, y=lat/northing) to lon/lat.

    Supports geographic datums (passed through) and WGS84 UTM. Raises
    :class:`CRSError` for anything else.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if epsg is None or is_geographic_epsg(epsg):
        return x, y
    utm = epsg_to_utm(epsg)
    if utm is not None:
        zone, northern = utm
        return utm_to_lonlat(x, y, zone, northern)
    raise CRSError(
        f"Unsupported CRS EPSG:{epsg}. Only geographic lon/lat and WGS84/UTM are "
        f"handled; reproject the data to EPSG:4326 or a UTM zone first."
    )

# WGS84 ellipsoid.
_A = 6378137.0
_F = 1.0 / 298.257223563
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9996


def utm_zone_central_meridian(zone: int) -> float:
    """Central-meridian longitude (degrees) of a UTM zone."""
    return (zone - 1) * 6 - 180 + 3


def epsg_to_utm(epsg: int):
    """Return (zone, northern) for a WGS84 UTM EPSG code, or None if not UTM."""
    if 32601 <= epsg <= 32660:
        return epsg - 32600, True
    if 32701 <= epsg <= 32760:
        return epsg - 32700, False
    return None


def lonlat_to_utm(lon, lat, zone: int, northern: bool = True):
    """Forward project geographic lon/lat (degrees) to UTM easting/northing (m)."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    lat_r = np.radians(lat)
    lon0 = np.radians(utm_zone_central_meridian(zone))
    dlon = np.radians(lon) - lon0

    sin_lat = np.sin(lat_r)
    cos_lat = np.cos(lat_r)
    tan_lat = np.tan(lat_r)

    N = _A / np.sqrt(1 - _E2 * sin_lat ** 2)
    T = tan_lat ** 2
    C = _EP2 * cos_lat ** 2
    A = dlon * cos_lat

    M = _A * (
        (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256) * lat_r
        - (3 * _E2 / 8 + 3 * _E2 ** 2 / 32 + 45 * _E2 ** 3 / 1024) * np.sin(2 * lat_r)
        + (15 * _E2 ** 2 / 256 + 45 * _E2 ** 3 / 1024) * np.sin(4 * lat_r)
        - (35 * _E2 ** 3 / 3072) * np.sin(6 * lat_r)
    )

    easting = _K0 * N * (
        A + (1 - T + C) * A ** 3 / 6
        + (5 - 18 * T + T ** 2 + 72 * C - 58 * _EP2) * A ** 5 / 120
    ) + 500000.0

    northing = _K0 * (
        M + N * tan_lat * (
            A ** 2 / 2 + (5 - T + 9 * C + 4 * C ** 2) * A ** 4 / 24
            + (61 - 58 * T + T ** 2 + 600 * C - 330 * _EP2) * A ** 6 / 720
        )
    )
    if not northern:
        northing = northing + 10000000.0
    return easting, northing


_NEUTRAL_RGB = (58, 62, 68)


def reproject_to_lonlat(src, target_extent, out_max_dim: int = 2048):
    """Resample a UTM :class:`~gml_editor.geotiff.GeoImage` onto a lon/lat grid.

    ``target_extent`` is the (west, east, south, north) lon/lat box to cover
    (typically the cropped terrain / GML extent). Output pixels are forward-
    projected to UTM and nearest-sampled from ``src``; areas outside the source
    are filled neutral. Returns a geographic :class:`GeoImage`.
    """
    from .geotiff import GeoImage

    if src.utm_zone is None:
        raise ValueError("source GeoImage is not in a UTM CRS")
    w, e, s, n = target_extent
    aspect = (e - w) / (n - s)
    if aspect >= 1:
        ow = out_max_dim
        oh = max(1, int(round(out_max_dim / aspect)))
    else:
        oh = out_max_dim
        ow = max(1, int(round(out_max_dim * aspect)))

    lons = np.linspace(w, e, ow)
    lats = np.linspace(n, s, oh)  # row 0 = north
    LON, LAT = np.meshgrid(lons, lats)
    E, N = lonlat_to_utm(LON, LAT, src.utm_zone, src.utm_northern)

    col = (E - src.west) / src.dx
    row = (src.north - N) / src.dy
    valid = (col >= 0) & (col < src.width) & (row >= 0) & (row < src.height)
    ci = np.clip(col, 0, src.width - 1).astype(np.intp)
    ri = np.clip(row, 0, src.height - 1).astype(np.intp)
    out = src.rgb[ri, ci].copy()
    out[~valid] = _NEUTRAL_RGB

    return GeoImage(out, west=w, north=n, dx=(e - w) / ow, dy=(n - s) / oh,
                    is_geographic=True, crs_epsg=4326)


def utm_to_lonlat(easting, northing, zone: int, northern: bool = True):
    """Inverse project UTM easting/northing (m) to geographic lon/lat (degrees)."""
    easting = np.asarray(easting, dtype=np.float64)
    northing = np.asarray(northing, dtype=np.float64)
    x = easting - 500000.0
    y = northing - (0.0 if northern else 10000000.0)

    M = y / _K0
    mu = M / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - np.sqrt(1 - _E2)) / (1 + np.sqrt(1 - _E2))

    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * np.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * np.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * np.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * np.sin(8 * mu)
    )

    sin_p = np.sin(phi1)
    cos_p = np.cos(phi1)
    tan_p = np.tan(phi1)
    N1 = _A / np.sqrt(1 - _E2 * sin_p ** 2)
    T1 = tan_p ** 2
    C1 = _EP2 * cos_p ** 2
    R1 = _A * (1 - _E2) / (1 - _E2 * sin_p ** 2) ** 1.5
    D = x / (N1 * _K0)

    lat = phi1 - (N1 * tan_p / R1) * (
        D ** 2 / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * _EP2) * D ** 4 / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * _EP2 - 3 * C1 ** 2) * D ** 6 / 720
    )
    lon = np.radians(utm_zone_central_meridian(zone)) + (
        D
        - (1 + 2 * T1 + C1) * D ** 3 / 6
        + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * _EP2 + 24 * T1 ** 2) * D ** 5 / 120
    ) / cos_p
    return np.degrees(lon), np.degrees(lat)
