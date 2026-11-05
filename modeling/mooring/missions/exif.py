"""Image validation and EXIF extraction (DateTimeOriginal, SubSec, OffsetTimeOriginal, GPS) and the capture-time rules.

The zone of a naive EXIF time is never guessed: without OffsetTimeOriginal or a caller-supplied
`exif_utc_offset_min` the capture time is unknown (null) and the note says why.
"""

import io
import math
import re
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from PIL import Image

from mooring.core.schemas.missions import MediaMetadata

MAX_IMAGE_BYTES = 8_000_000  # same limit as the vision agent upload
MAX_PIXELS = 100_000_000
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}

_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825
_DTO, _SUBSEC, _OFFSET = 36867, 37521, 36881


class ImageError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def image_type(data: bytes) -> str | None:
    """Content type from magic bytes only (never the filename)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes) -> str:
    """Return the content type or raise ImageError (422 empty/undecodable, 413 too large, 415 unsupported type)."""
    if not data:
        raise ImageError(422, "empty image")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(413, f"image larger than {MAX_IMAGE_BYTES} bytes")
    ctype = image_type(data)
    if ctype is None:
        raise ImageError(415, "unsupported image type; JPEG, PNG and WebP are accepted (checked by content)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format != _FORMATS[ctype]:
                raise ImageError(415, "image content does not match its type")
            if img.width * img.height > MAX_PIXELS:
                raise ImageError(422, "image dimensions too large")
            img.verify()
    except ImageError:
        raise
    except Exception as exc:  # Pillow raises many types for corrupt input, including bomb warnings
        raise ImageError(422, f"image cannot be decoded ({type(exc).__name__})") from exc
    return ctype


@dataclass
class ExifInfo:
    local_time: datetime | None = None          # naive camera-local time with sub-seconds
    offset_min: int | None = None               # OffsetTimeOriginal
    lat: float | None = None
    lon: float | None = None
    notes: list[str] = field(default_factory=list)


def _rational(v) -> float:
    return float(v)


def _gps(gps) -> tuple[float | None, float | None, str | None]:
    try:
        la, lar, lo, lor = gps.get(2), gps.get(1), gps.get(4), gps.get(3)
        if la is None or lo is None or lar is None or lor is None:
            return None, None, None
        lar, lor = str(lar).strip().upper()[:1], str(lor).strip().upper()[:1]
        if lar not in ("N", "S") or lor not in ("E", "W"):
            return None, None, "GPS hemisphere reference invalid"
        d = lambda t: _rational(t[0]) + _rational(t[1]) / 60 + _rational(t[2]) / 3600
        lat, lon = d(la) * (-1 if lar == "S" else 1), d(lo) * (-1 if lor == "W" else 1)
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None, "GPS position out of range"
        if lat == 0 and lon == 0:
            return None, None, "GPS position 0,0 ignored (typical of a camera without a fix)"
        return lat, lon, None
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None, None, "GPS tags unreadable"


def extract_exif(data: bytes) -> ExifInfo:
    info = ExifInfo()
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        sub = exif.get_ifd(_EXIF_IFD)
        gps = exif.get_ifd(_GPS_IFD)
    except Exception as exc:
        info.notes.append(f"EXIF unreadable ({type(exc).__name__})")
        return info
    raw = sub.get(_DTO) or exif.get(306)  # fall back to DateTime only if DateTimeOriginal is absent
    if raw:
        raw = raw.decode("ascii", "ignore") if isinstance(raw, bytes) else str(raw)
        m = re.fullmatch(r"\s*(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)\s*", raw)
        try:
            if not m:
                raise ValueError
            dt = datetime(*map(int, m.groups()))
            ss = str(sub.get(_SUBSEC) or "").strip().strip("\x00")
            if ss.isdigit():
                dt += timedelta(microseconds=int(ss[:6].ljust(6, "0")))
            info.local_time = dt
        except ValueError:
            info.notes.append(f"EXIF capture time '{raw[:24]}' is not a valid date-time")
    off = sub.get(_OFFSET)
    if off:
        off = off.decode("ascii", "ignore") if isinstance(off, bytes) else str(off)
        m = re.fullmatch(r"\s*([+-])(\d\d):(\d\d)\s*", off)
        if m and int(m[2]) <= 14 and int(m[3]) < 60:
            info.offset_min = (1 if m[1] == "+" else -1) * (int(m[2]) * 60 + int(m[3]))
        else:
            info.notes.append(f"EXIF OffsetTimeOriginal '{off[:12]}' ignored (malformed)")
    if gps:
        info.lat, info.lon, note = _gps(gps)
        if note:
            info.notes.append(note)
    return info


@dataclass
class ResolvedTime:
    captured_utc: datetime | None
    source: str | None
    note: str
    caveats: list[str] = field(default_factory=list)  # codes of ValidityReasons the located event inherits


def resolve_time(info: ExifInfo, meta: MediaMetadata) -> ResolvedTime:
    """Apply the capture-time rules. camera_clock_offset_s applies to the camera (EXIF) time only; combining it with an
    explicit captured_utc is rejected by the caller because it would be ambiguous."""
    if meta.captured_utc is not None:
        return ResolvedTime(meta.captured_utc.astimezone(UTC), "supplied", "Time supplied with the upload.")
    extra = (" " + "; ".join(info.notes)) if info.notes else ""
    if info.local_time is None:
        return ResolvedTime(None, None, "No usable EXIF capture time and none supplied." + extra)
    caveats: list[str] = []
    if info.offset_min is not None:
        zone = timezone(timedelta(minutes=info.offset_min))
        how = f"EXIF DateTimeOriginal with EXIF OffsetTimeOriginal {info.offset_min:+d} min."
    elif meta.exif_utc_offset_min is not None:
        zone = timezone(timedelta(minutes=meta.exif_utc_offset_min))
        how = (f"EXIF DateTimeOriginal is naive; used the supplied exif_utc_offset_min {meta.exif_utc_offset_min:+d}.")
        caveats.append("EXIF_UTC_OFFSET_ASSUMED")
    else:
        return ResolvedTime(None, None, "EXIF time is naive (no OffsetTimeOriginal) and no exif_utc_offset_min was "
                                        "supplied; the time zone is not guessed, so the capture time is unknown." + extra)
    t = info.local_time.replace(tzinfo=zone).astimezone(UTC)
    if meta.camera_clock_offset_s:
        t += timedelta(seconds=meta.camera_clock_offset_s)
        how += f" Camera clock offset {meta.camera_clock_offset_s:+g} s applied."
        caveats.append("CAMERA_CLOCK_OFFSET_APPLIED")
    return ResolvedTime(t, "exif", how + extra, caveats)
