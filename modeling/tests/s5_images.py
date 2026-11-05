"""Helpers: tiny images carrying chosen EXIF, generated with Pillow (no binary fixtures)."""

import io

from PIL import Image


def make_image(fmt="JPEG", dto=None, offset=None, subsec=None, gps=None, size=(8, 6), extra_ifd0=None):
    exif = Image.Exif()
    sub = {}
    if dto:
        sub[36867] = dto
    if offset:
        sub[36881] = offset
    if subsec:
        sub[37521] = subsec
    if sub:
        exif[0x8769] = sub
    if gps:
        exif[0x8825] = gps
    for k, v in (extra_ifd0 or {}).items():
        exif[k] = v
    buf = io.BytesIO()
    kw = {"exif": exif} if (sub or gps or extra_ifd0) else {}
    Image.new("RGB", size, (10, 120, 200)).save(buf, format=fmt, **kw)
    return buf.getvalue()


def gps_tags(lat, lon):
    def dms(x):
        x = abs(x)
        d = int(x)
        m = int((x - d) * 60)
        return (float(d), float(m), round((x - d - m / 60) * 3600, 4))
    return {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
