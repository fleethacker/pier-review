"""S5 review-ledger regressions (findings 1, 2, 4, 5, 6, 7). See docs/MODELING_BUILDOUT_STATUS.md."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from modeling_api.main import app
from mooring.core.store import reset_db
from mooring.missions import exif, parsers
from mooring.missions.geo import to_us
from mooring.missions.locate import TrackIndex, locate
from s5_images import make_image
from test_s5_fixes import gga, nm, rmc

P = "/api/v1"


@pytest.fixture
def client():
    reset_db(":memory:")
    return TestClient(app)


def _mission(c):
    return c.post(f"{P}/missions", json={"name": "m", "vessel_id": "v"}).json()["mission_id"]


# ---- finding 1: a rejected sentence must not move the date state
def test_rejected_rmc_does_not_change_the_date_for_later_gga():
    bad_rmc = rmc("120000", "020625", lat="9999.0000")  # valid status/date, malformed latitude: rejected
    r = parsers.parse_nmea(nm(rmc("115958", "010625"), bad_rmc, gga("120001")))
    assert r.rejected == 1
    assert [f.t_utc.day for f in r.fixes] == [1, 1]


def test_rejected_gga_does_not_roll_the_date_over():
    bad = gga("000000", lat="9999.0000")  # would be a midnight crossing, but is rejected
    r = parsers.parse_nmea(nm(gga("235958"), bad, gga("235959")), date(2025, 6, 1))
    assert r.rejected == 1
    assert [f.t_utc.day for f in r.fixes] == [1, 1]


# ---- finding 4: GGA quality
@pytest.mark.parametrize("q,ok", [("0", False), ("1", True), ("2", True), ("4", True), ("5", True),
                                  ("6", False), ("7", False), ("8", False), ("", False), ("x", False)])
def test_gga_quality_only_measured_fixes_accepted(q, ok):
    r = parsers.parse_nmea(nm(gga("120000", q=q)), date(2025, 6, 1))
    assert len(r.fixes) == int(ok)


# ---- finding 2: simulated-track validity
def _sim_index(source):
    rows = [(to_us(datetime(2025, 6, 1, 12, 0, s, tzinfo=UTC)), 0.0, 0.001 * s, 90.0, 90.0, 5.0, 0.5, "good", source)
            for s in (0, 10)]
    return TrackIndex.from_rows(rows)


@pytest.mark.parametrize("sec,method", [(0, "exact_fix"), (5, "interpolated")])
def test_events_on_simulated_track_are_limited_never_valid(sec, method):
    t = datetime(2025, 6, 1, 12, 0, sec, tzinfo=UTC)
    sim = locate(_sim_index("simulated:job_1"), t, 300)
    assert sim.method == method and sim.validity.state == "limited"
    assert "SIMULATED_TRACK" in [x.code for x in sim.validity.reasons]
    if method == "exact_fix":
        assert locate(_sim_index("gps"), t, 300).validity.state == "valid"


# ---- finding 5: malformed uploads are 4xx, never 500
def test_csv_oversized_field_is_4xx_not_500(client):
    mid = _mission(client)
    body = b'time,lat,lon\n2025-06-01T12:00:00Z,0,0,"' + b"x" * 200_000 + b'"\n'
    r = client.post(f"{P}/missions/{mid}/track/file", files={"file": ("t.csv", body)}, data={"format": "csv"})
    assert 400 <= r.status_code < 500, r.text


@pytest.mark.parametrize("fmt,body", [
    ("geojson", b'{"type":"FeatureCollection","features":[null,1,"x",{"geometry":{"type":"LineString","coordinates":5},'
                b'"properties":{"times":3}}]}'),
    ("gpx", b"<gpx><trkpt lat='x' lon='y'><time>2025-06-01T00:00:00Z</time></trkpt></gpx>"),
    ("nmea", b"\xff\xfe\x00"), ("csv", b"\x00\x00\x00")])
def test_malformed_uploads_never_500(client, fmt, body):
    mid = _mission(client)
    r = client.post(f"{P}/missions/{mid}/track/file", files={"file": ("t", body)}, data={"format": fmt})
    assert 400 <= r.status_code < 500, r.text


# ---- finding 6: truncated / corrupt JPEG body is refused at upload
def test_truncated_jpeg_is_refused_at_upload(client):
    data = make_image("JPEG", size=(64, 64))
    assert exif.validate_image(data) == "image/jpeg"
    cut = data[: len(data) - 40]
    mid = _mission(client)
    r = client.post(f"{P}/missions/{mid}/media", files={"image": ("a.jpg", cut, "image/jpeg")})
    assert r.status_code == 422, r.text
    assert client.get(f"{P}/missions/{mid}/media").json() == []


# ---- finding 7: duplicate rows do not accumulate in memory
def test_duplicate_timestamps_are_dropped_while_parsing_and_still_counted(client):
    row = "2025-06-01T12:00:00Z,1,2\n"
    r = parsers.parse_csv(("time,lat,lon\n" + row * 5000 + "2025-06-01T12:00:01Z,1,2\n").encode(), None, 100)
    assert len(r.fixes) == 2 and r.duplicates == 4999
    mid = _mission(client)
    up = client.post(f"{P}/missions/{mid}/track/file",
                     files={"file": ("t.csv", ("time,lat,lon\n" + row * 50).encode())}, data={"format": "csv"}).json()
    assert (up["accepted"], up["duplicates"]) == (1, 49)
