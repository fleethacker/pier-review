#!/usr/bin/env python3
"""Write a small, realistic demo dataset for the Missions app (S5 storyboard) into a folder.

Usage: uv run --all-packages --with pillow python scripts/make_demo_mission_data.py <outdir>

Writes (offline, deterministic, no network):
  track.csv        2 h sortie from Norfolk, one fix every 30 s, with a 10 minute recording gap (12:50-13:00 UTC)
  on_track.jpg     taken 12:20 UTC, inside the track
  in_gap.jpg       taken 12:55 UTC, inside the gap: the storyboard must say "position not established"
  clock_off.jpg    camera clock 2 min slow: shown 13:28:00, true 13:30:00; enter camera clock offset 120 s
  reports.json     two reports: a log entry, and one with a stated position about 1 km north of the track
Same geometry as scripts/check_missions_ui.py. Synthetic data; not a real track.
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

T0 = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def pos_at(sec: float) -> tuple[float, float]:
    f = sec / 7200
    return 36.95 + 0.06 * f, -76.33 + 0.17 * f


def csv_track() -> str:
    rows = ["time,lat,lon,heading,sog,hdop"]
    for s in range(0, 7201, 30):
        if 3000 < s < 3600:  # recording gap 12:50-13:00
            continue
        lat, lon = pos_at(s)
        rows.append(f"{(T0 + timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%SZ')},{lat:.6f},{lon:.6f},75,9.5,1.0")
    return "\n".join(rows) + "\n"


def dms(v: float) -> tuple[int, int, float]:
    v = abs(v)
    return int(v), int((v % 1) * 60), ((v * 60) % 1) * 60


def jpeg(label: str, shown: datetime, lat: float, lon: float) -> bytes:
    img = Image.new("RGB", (640, 400), (30, 90, 160))
    ImageDraw.Draw(img).text((20, 20), f"{label}\ncamera clock {shown:%H:%M:%S}", fill=(255, 255, 255))
    exif = Image.Exif()
    sub = exif.get_ifd(0x8769)
    sub[36867] = shown.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal
    sub[36881] = "+00:00"  # OffsetTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N" if lat >= 0 else "S", dms(lat)
    gps[3], gps[4] = "E" if lon >= 0 else "W", dms(lon)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "track.csv").write_text(csv_track())
    (out / "on_track.jpg").write_bytes(jpeg("On the track", T0 + timedelta(minutes=20), *pos_at(1200)))
    (out / "in_gap.jpg").write_bytes(jpeg("Inside the gap", T0 + timedelta(minutes=55), *pos_at(3300)))
    (out / "clock_off.jpg").write_bytes(jpeg("Camera clock 2 min slow", T0 + timedelta(minutes=88), *pos_at(5400)))
    lat, lon = pos_at(4800)
    reports = [
        {"t_utc": (T0 + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"), "title": "Bridge log entry",
         "body": "Underway, pilot disembarked."},
        {"t_utc": (T0 + timedelta(minutes=80)).strftime("%Y-%m-%dT%H:%M:%SZ"), "title": "Stated position report",
         "body": "Watch officer's stated position (about 1 km north of the recorded track).",
         "lat": round(lat + 0.009, 6), "lon": round(lon, 6)},
    ]
    (out / "reports.json").write_text(json.dumps(reports, indent=2) + "\n")
    print(f"wrote track.csv, on_track.jpg, in_gap.jpg, clock_off.jpg, reports.json to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
