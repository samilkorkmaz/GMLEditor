"""Pure-Python DTED reader (v0.3).

DTED (Digital Terrain Elevation Data) is a simple, well-documented binary raster
of elevations, so it is read here directly without GDAL — consistent with the
rest of the project (see v0.1 notes) and avoiding the native-GDAL install.

File layout (MIL-PRF-89020):
  UHL  (User Header Label)            80 bytes
  DSI  (Data Set Identification)     648 bytes
  ACC  (Accuracy Description)       2700 bytes
  data records                     one per longitude line (column)

Each data record:
  1 byte   sentinel (0xAA)
  3 bytes  data block count
  2 bytes  longitude count
  2 bytes  latitude count
  2*nrow   elevations, 16-bit big-endian **sign-magnitude**, metres
  4 bytes  checksum

Columns run west->east (increasing longitude); within a column, samples run
south->north (increasing latitude). The void value is -32767.

The public entry point is :func:`load_dted` -> :class:`DtedGrid`. A
:func:`write_dted` helper produces spec-conformant files (used by the tests to
generate synthetic terrain without shipping a real tile).
"""

from __future__ import annotations

import math
import os

import numpy as np

VOID = -32767
_HEADER_BYTES = 80 + 648 + 2700  # UHL + DSI + ACC = 3428


class DtedError(Exception):
    """Raised for a missing, truncated, or malformed DTED file."""


def _parse_angle(field: bytes) -> float:
    """Parse a DTED DDDMMSSH / DDMMSSH angle field to signed decimal degrees."""
    s = field.decode("ascii", "replace").strip()
    hemi = s[-1].upper()
    digits = s[:-1]
    sec = int(digits[-2:])
    minute = int(digits[-4:-2])
    deg = int(digits[:-4])
    val = deg + minute / 60.0 + sec / 3600.0
    if hemi in ("S", "W"):
        val = -val
    return val


def _fmt_angle(value: float, lat: bool) -> str:
    """Format signed decimal degrees as an 8-char DDDMMSSH field."""
    hemi = ("N" if value >= 0 else "S") if lat else ("E" if value >= 0 else "W")
    v = abs(value)
    deg = int(v)
    minute = int((v - deg) * 60)
    sec = int(round((v - deg - minute / 60.0) * 3600))
    if sec == 60:  # rounding roll-over
        sec = 0
        minute += 1
    if minute == 60:
        minute = 0
        deg += 1
    return f"{deg:03d}{minute:02d}{sec:02d}{hemi}"


class DtedGrid:
    """An elevation grid with its geographic georeferencing.

    ``elev`` is indexed ``[row, col]`` where row 0 is the southernmost latitude
    (``lat0``) and col 0 the westernmost longitude (``lon0``). Voids are filled
    (see ``void_count``) so the array is finite and ready for sampling/meshing.
    """

    def __init__(self, elev: np.ndarray, lon0: float, lat0: float,
                 dlon: float, dlat: float):
        self.lon0 = lon0
        self.lat0 = lat0
        self.dlon = dlon          # degrees per column step
        self.dlat = dlat          # degrees per row step
        self.nrow, self.ncol = elev.shape

        void_mask = (elev == VOID) | ~np.isfinite(elev)
        self.void_count = int(void_mask.sum())
        filled = elev.astype(np.float64, copy=True)
        if self.void_count:
            valid = filled[~void_mask]
            fill_value = float(valid.mean()) if valid.size else 0.0
            filled[void_mask] = fill_value
        self.elev = filled
        self.zmin = float(filled.min())
        self.zmax = float(filled.max())

    # geographic extent (degrees)
    @property
    def lon1(self) -> float:
        return self.lon0 + (self.ncol - 1) * self.dlon

    @property
    def lat1(self) -> float:
        return self.lat0 + (self.nrow - 1) * self.dlat

    def sample(self, lon, lat) -> np.ndarray:
        """Bilinearly sample elevation (metres) at lon/lat (scalars or arrays).

        Coordinates outside the grid are clamped to the edge.
        """
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        fx = np.clip((lon - self.lon0) / self.dlon, 0.0, self.ncol - 1)
        fy = np.clip((lat - self.lat0) / self.dlat, 0.0, self.nrow - 1)
        c0 = np.floor(fx).astype(np.intp)
        r0 = np.floor(fy).astype(np.intp)
        c1 = np.minimum(c0 + 1, self.ncol - 1)
        r1 = np.minimum(r0 + 1, self.nrow - 1)
        tx = fx - c0
        ty = fy - r0
        e = self.elev
        top = e[r0, c0] * (1 - tx) + e[r0, c1] * tx
        bot = e[r1, c0] * (1 - tx) + e[r1, c1] * tx
        return top * (1 - ty) + bot * ty

    def subset(self, lon_min: float, lat_min: float, lon_max: float, lat_max: float,
               margin_frac: float = 0.05) -> "DtedGrid":
        """Return the sub-grid covering a lon/lat box (plus a fractional margin).

        Used to crop a full 1-degree tile down to the area of interest (e.g. the
        GML extent) so the geometry isn't a speck on a huge surface. The window
        is snapped outward to whole grid cells and clamped to the tile.
        """
        mlon = (lon_max - lon_min) * margin_frac
        mlat = (lat_max - lat_min) * margin_frac
        lon_min -= mlon; lon_max += mlon
        lat_min -= mlat; lat_max += mlat

        c0 = int(math.floor((lon_min - self.lon0) / self.dlon))
        c1 = int(math.ceil((lon_max - self.lon0) / self.dlon))
        r0 = int(math.floor((lat_min - self.lat0) / self.dlat))
        r1 = int(math.ceil((lat_max - self.lat0) / self.dlat))
        c0 = max(0, min(c0, self.ncol - 1))
        c1 = max(0, min(c1, self.ncol - 1))
        r0 = max(0, min(r0, self.nrow - 1))
        r1 = max(0, min(r1, self.nrow - 1))
        if c1 <= c0:
            c1 = min(c0 + 1, self.ncol - 1)
        if r1 <= r0:
            r1 = min(r0 + 1, self.nrow - 1)

        sub = self.elev[r0:r1 + 1, c0:c1 + 1]
        new_lon0 = self.lon0 + c0 * self.dlon
        new_lat0 = self.lat0 + r0 * self.dlat
        return DtedGrid(sub, new_lon0, new_lat0, self.dlon, self.dlat)


def _decode_sign_magnitude(raw16: np.ndarray) -> np.ndarray:
    """Decode big-endian 16-bit sign-magnitude integers to signed values."""
    vals = raw16.astype(np.int32)
    neg = (vals & 0x8000) != 0
    mag = vals & 0x7FFF
    return np.where(neg, -mag, mag)


def load_dted(path: str) -> DtedGrid:
    """Read a DTED file (any level) into a :class:`DtedGrid`."""
    if not os.path.isfile(path):
        raise DtedError(f"File not found: {path}")
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < _HEADER_BYTES or raw[:3] != b"UHL":
        raise DtedError(f"Not a DTED file (missing UHL header): {path}")

    uhl = raw[:80]
    try:
        lon0 = _parse_angle(uhl[4:12])
        lat0 = _parse_angle(uhl[12:20])
        dlon = int(uhl[20:24]) / 10.0 / 3600.0   # tenths of arc-sec -> degrees
        dlat = int(uhl[24:28]) / 10.0 / 3600.0
        ncol = int(uhl[47:51])                    # number of longitude lines
        nrow = int(uhl[51:55])                    # latitude points per line
    except ValueError as exc:
        raise DtedError(f"Malformed UHL header in {path}: {exc}") from exc

    if ncol <= 0 or nrow <= 0:
        raise DtedError(f"Invalid grid size {ncol}x{nrow} in {path}")

    rec_len = 8 + 2 * nrow + 4
    expected = _HEADER_BYTES + ncol * rec_len
    if len(raw) < expected:
        raise DtedError(
            f"Truncated DTED: expected {expected} bytes, got {len(raw)} ({path})"
        )

    elev = np.empty((nrow, ncol), dtype=np.float64)
    for c in range(ncol):
        base = _HEADER_BYTES + c * rec_len
        data_start = base + 8
        raw16 = np.frombuffer(raw, dtype=">u2", count=nrow, offset=data_start)
        elev[:, c] = _decode_sign_magnitude(raw16)

    return DtedGrid(elev, lon0, lat0, dlon, dlat)


def write_dted(path: str, elev_m: np.ndarray, lon0: float, lat0: float,
               dlon_arcsec: float, dlat_arcsec: float) -> None:
    """Write a spec-conformant DTED file. ``elev_m`` is ``[row(south->north), col(west->east)]``."""
    nrow, ncol = elev_m.shape

    uhl = bytearray(b" " * 80)
    uhl[0:4] = b"UHL1"
    uhl[4:12] = _fmt_angle(lon0, lat=False).encode("ascii")
    uhl[12:20] = _fmt_angle(lat0, lat=True).encode("ascii")
    uhl[20:24] = f"{int(round(dlon_arcsec * 10)):04d}".encode("ascii")
    uhl[24:28] = f"{int(round(dlat_arcsec * 10)):04d}".encode("ascii")
    uhl[28:32] = b"0000"
    uhl[47:51] = f"{ncol:04d}".encode("ascii")
    uhl[51:55] = f"{nrow:04d}".encode("ascii")

    dsi = bytearray(b" " * 648)
    dsi[0:3] = b"DSI"
    acc = bytearray(b" " * 2700)
    acc[0:3] = b"ACC"

    out = bytearray(uhl + dsi + acc)
    for c in range(ncol):
        col = np.round(np.clip(elev_m[:, c], -32767, 32767)).astype(np.int32)
        mag = np.abs(col).astype(np.uint16)
        enc = np.where(col < 0, mag | np.uint16(0x8000), mag).astype(">u2")
        out.append(0xAA)
        out += int(c).to_bytes(3, "big")   # data block count
        out += int(c).to_bytes(2, "big")   # longitude count
        out += (0).to_bytes(2, "big")      # latitude count
        out += enc.tobytes()
        out += (0).to_bytes(4, "big")      # checksum (not validated on read)

    with open(path, "wb") as fh:
        fh.write(out)
