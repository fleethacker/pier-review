"""S5 image validation, EXIF extraction and the capture-time rules."""

from datetime import UTC, datetime

import pytest
from mooring.core.schemas.missions import MediaMetadata
from mooring.missions import exif
from s5_images import gps_tags, make_image


def info_and_time(data, **meta):
    info = exif.extract_exif(data)
    return info, exif.resolve_time(info, MediaMetadata(**meta))


def test_exif_offset_in_file_and_subseconds_and_gps():
    data = make_image(dto="2025:06:01 08:00:00", offset="-04:00", subsec="250", gps=gps_tags(36.8833333, -76.3666667))
    info, rt = info_and_time(data)
    assert info.offset_min == -240
    assert rt.captured_utc == datetime(2025, 6, 1, 12, 0, 0, 250000, tzinfo=UTC)
    assert rt.source == "exif" and rt.caveats == []
    assert info.lat == pytest.approx(36.8833333, abs=1e-5) and info.lon == pytest.approx(-76.3666667, abs=1e-5)


def test_naive_exif_without_offset_is_unknown_never_guessed():
    _, rt = info_and_time(make_image(dto="2025:06:01 08:00:00"))
    assert rt.captured_utc is None and rt.source is None
    assert "not guess" in rt.note and "exif_utc_offset_min" in rt.note


def test_naive_exif_with_supplied_offset_and_clock_offset():
    data = make_image(dto="2025:06:01 08:00:00")
    _, rt = info_and_time(data, exif_utc_offset_min=-240)
    assert rt.captured_utc == datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    assert rt.caveats == ["EXIF_UTC_OFFSET_ASSUMED"]
    # camera slow by 90 s -> add 90 s
    _, rt = info_and_time(data, exif_utc_offset_min=-240, camera_clock_offset_s=90)
    assert rt.captured_utc == datetime(2025, 6, 1, 12, 1, 30, tzinfo=UTC)
    assert rt.caveats == ["EXIF_UTC_OFFSET_ASSUMED", "CAMERA_CLOCK_OFFSET_APPLIED"]
    # a fast camera: negative offset; EXIF's own OffsetTimeOriginal wins over the supplied one
    d2 = make_image(dto="2025:06:01 08:00:00", offset="+00:00")
    _, rt = info_and_time(d2, exif_utc_offset_min=999 // 100 * 60, camera_clock_offset_s=-2.5)
    assert rt.captured_utc == datetime(2025, 6, 1, 7, 59, 57, 500000, tzinfo=UTC)
    assert rt.caveats == ["CAMERA_CLOCK_OFFSET_APPLIED"]


def test_clock_offset_without_a_time_does_not_invent_one():
    _, rt = info_and_time(make_image(dto="2025:06:01 08:00:00"), camera_clock_offset_s=30)
    assert rt.captured_utc is None


def test_supplied_time_wins_over_exif():
    data = make_image(dto="2025:06:01 08:00:00", offset="-04:00")
    _, rt = info_and_time(data, captured_utc="2025-06-01T15:00:00+03:00")
    assert rt.captured_utc == datetime(2025, 6, 1, 12, 0, tzinfo=UTC) and rt.source == "supplied" and rt.caveats == []


def test_no_exif_and_bad_exif_values():
    info, rt = info_and_time(make_image())
    assert info.lat is None and rt.captured_utc is None and "No usable EXIF" in rt.note
    _, rt = info_and_time(make_image(dto="0000:00:00 00:00:00", offset="+00:00"))
    assert rt.captured_utc is None and "not a valid date-time" in rt.note
    info, _ = info_and_time(make_image(gps={1: "N", 2: (95.0, 0.0, 0.0), 3: "E", 4: (10.0, 0.0, 0.0)}))
    assert info.lat is None and info.lon is None and any("out of range" in n for n in info.notes)
    info, _ = info_and_time(make_image(gps={1: "N", 2: (0.0, 0.0, 0.0), 3: "E", 4: (0.0, 0.0, 0.0)}))
    assert info.lat is None  # 0,0 is a camera with no fix, not the Gulf of Guinea


def test_southern_and_western_hemispheres():
    info, _ = info_and_time(make_image(gps=gps_tags(-33.5, -70.25)))
    assert (info.lat, info.lon) == (pytest.approx(-33.5, abs=1e-4), pytest.approx(-70.25, abs=1e-4))


@pytest.mark.parametrize("fmt,ctype", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_validate_image_by_magic_bytes(fmt, ctype):
    assert exif.validate_image(make_image(fmt)) == ctype


def test_validate_image_rejections():
    good = make_image()
    for data, status in ((b"", 422), (b"GIF89a" + b"0" * 100, 415), (b"%PDF-1.4 ....", 415), (good[:30], 422),
                         (good + b"\0" * exif.MAX_IMAGE_BYTES, 413)):
        with pytest.raises(exif.ImageError) as e:
            exif.validate_image(data)
        assert e.value.status == status
    # a PNG renamed .jpg is still a PNG: only content counts
    assert exif.validate_image(make_image("PNG")) == "image/png"
    # JPEG magic with non-JPEG content
    with pytest.raises(exif.ImageError):
        exif.validate_image(b"\xff\xd8\xff" + b"not really a jpeg")
