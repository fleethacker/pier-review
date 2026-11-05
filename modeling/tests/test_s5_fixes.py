"""S5 review fixes: regression tests (time parsing, NMEA hygiene, GPX safety, range bounds, DoS limits, locate)."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from modeling_api.main import app
from mooring.core.schemas.missions import MediaMetadata, TrackFix
from mooring.core.store import reset_db
from mooring.missions import exif, parsers, store
from mooring.missions.locate import TrackIndex, locate
from s5_images import make_image

P = "/api/v1"


def cs(body: str) -> str:
    x = 0
    for c in body:
        x ^= ord(c)
    return f"${body}*{x:02X}"


def gga(hhmmss, lat="3653.0000", ns="N", lon="07622.0000", ew="W", q="1"):
    return cs(f"GPGGA,{hhmmss},{lat},{ns},{lon},{ew},{q},08,0.9,3.0,M,0.0,M,,")


def rmc(hhmmss, ddmmyy="010625", status="A", mode="A", lat="3653.0000", ns="N", lon="07622.0000", ew="W"):
    return cs(f"GPRMC,{hhmmss},{status},{lat},{ns},{lon},{ew},10.0,90.0,{ddmmyy},,,{mode}")


def nm(*lines):
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def client():
    reset_db(":memory:")
    return TestClient(app)


def mission(c):
    return c.post(f"{P}/missions", json={"name": "m", "vessel_id": "v"}).json()["mission_id"]


# ---- 1. NMEA GGA-only date rollover

def test_gga_only_rolls_over_midnight_with_nmea_date_and_keeps_going():
    data = nm(gga("235958"), gga("235959"), gga("000000"), gga("000001"), gga("235959"), gga("000000"))
    r = parsers.parse_nmea(data, date(2025, 6, 1))
    assert [f.t_utc for f in r.fixes] == [
        datetime(2025, 6, 1, 23, 59, 58, tzinfo=UTC), datetime(2025, 6, 1, 23, 59, 59, tzinfo=UTC),
        datetime(2025, 6, 2, 0, 0, 0, tzinfo=UTC), datetime(2025, 6, 2, 0, 0, 1, tzinfo=UTC),
        datetime(2025, 6, 2, 23, 59, 59, tzinfo=UTC), datetime(2025, 6, 3, 0, 0, 0, tzinfo=UTC)]


def test_mixed_rmc_then_gga_rollover_and_rmc_date_wins():
    data = nm(rmc("235959"), gga("000000"), gga("000001"), rmc("000002", "020625"))
    r = parsers.parse_nmea(data)
    assert [f.t_utc.day for f in r.fixes] == [1, 2, 2, 2]


# ---- 2. epoch vs compact dates

@pytest.mark.parametrize("val", ["20260105", "20260105120000", "20260105T120000", "1748779200000", "12345"])
def test_csv_compact_dates_are_not_epoch_seconds(val):
    r = parsers.parse_csv(f"time,lat,lon\n{val},1,2\n".encode())  # no offset: naive compact or ambiguous -> rejected
    assert r.fixes == [] and r.rejected == 1
    assert "1970" not in r.errors[0]


def test_csv_compact_iso_with_offset_and_epoch_forms():
    r = parsers.parse_csv(b"time,lat,lon\n20260105T120000Z,1,2\n20260105120000,1,3\n20260105T120000-0500,1,4\n"
                          b"1748779200,1,5\n1748779200.5,1,6\n", utc_offset_min=60)
    assert [f.t_utc for f in r.fixes] == [
        datetime(2026, 1, 5, 12, tzinfo=UTC), datetime(2026, 1, 5, 11, tzinfo=UTC), datetime(2026, 1, 5, 17, tzinfo=UTC),
        datetime(2025, 6, 1, 12, tzinfo=UTC), datetime(2025, 6, 1, 12, 0, 0, 500000, tzinfo=UTC)]
    assert parsers.parse_csv(b"time,lat,lon\n20260105,1,2\n", utc_offset_min=0).rejected == 1  # bare date: never epoch


def test_csv_explicit_epoch_column_accepts_small_epoch_values():
    r = parsers.parse_csv(b"epoch,lat,lon\n946684800,1,2\n3000000000,1,3\n")
    assert len(r.fixes) == 2
    r = parsers.parse_csv(b"unix,lat,lon\n1748779200000,1,2\n")  # milliseconds still refused
    assert r.rejected == 1 and "milliseconds" in r.errors[0]
    assert len(parsers.parse_csv(b"time_s,lat,lon\n86400,1,2\n").fixes) == 1


# ---- 3. year bounds / OverflowError

BAD_TIMES = ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00"]


@pytest.mark.parametrize("ts", BAD_TIMES)
def test_out_of_range_times_rejected_not_500(client, ts):
    r = parsers.parse_csv(f"time,lat,lon\n{ts},1,2\n".encode())
    assert r.rejected == 1 and "1970..2100" in r.errors[0]
    mid = mission(client)
    up = client.post(f"{P}/missions/{mid}/track/file", files={"file": ("t.csv", f"time,lat,lon\n{ts},1,2\n".encode())},
                     data={"format": "csv"})
    assert up.status_code == 422
    j = client.post(f"{P}/missions/{mid}/track", json={"fixes": [{"t_utc": ts, "lat": 1, "lon": 2}]})
    assert j.status_code == 422 and "1970..2100" in j.text
    rp = client.post(f"{P}/missions/{mid}/reports", json={"t_utc": ts, "title": "x"})
    assert rp.status_code == 422 and "1970..2100" in rp.text
    m = client.post(f"{P}/missions/{mid}/media", files={"image": ("a.jpg", make_image())},
                    data={"metadata": json.dumps({"captured_utc": ts})})
    assert m.status_code == 422
    assert client.get(f"{P}/missions/{mid}").json()["fix_count"] == 0


def test_out_of_range_in_gpx_geojson_and_epoch():
    gpx = b'<gpx><trkpt lat="1" lon="2"><time>0001-01-01T00:00:00+05:00</time></trkpt></gpx>'
    assert parsers.parse_gpx(gpx).rejected == 1
    gj = json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [2, 1]},
                     "properties": {"time": "9999-12-31T23:59:59-05:00"}}).encode()
    assert parsers.parse_geojson(gj).rejected == 1
    assert parsers.parse_geojson(json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [2, 1]},
                                             "properties": {"time": 1e300}}).encode()).rejected == 1


def test_boundary_years_accepted():
    r = parsers.parse_csv(b"time,lat,lon\n1970-01-01T00:00:00Z,1,2\n2100-12-31T23:59:59Z,1,3\n")
    assert len(r.fixes) == 2


# ---- 4. GeoJSON recursion

def test_deeply_nested_geojson_is_422(client):
    deep = b'{"type":"Feature","properties":{"a":' + b"[" * 100_000 + b"]" * 100_000 + b'},"geometry":null}'
    with pytest.raises(parsers.TrackParseError, match="deeper|deeply"):
        parsers.parse_geojson(deep)
    mid = mission(client)
    r = client.post(f"{P}/missions/{mid}/track/file", files={"file": ("t.geojson", deep)}, data={"format": "geojson"})
    assert r.status_code == 422


def test_json_recursion_error_is_also_caught(monkeypatch):
    monkeypatch.setattr(parsers, "_depth_ok", lambda text: True)
    deep = b"[" * 200_000 + b"]" * 200_000
    with pytest.raises(parsers.TrackParseError, match="deeply"):
        parsers.parse_geojson(deep)


# ---- 5. DoS: early cap, off the event loop

def test_cap_aborts_during_parsing_not_after(monkeypatch, client):
    built = []
    real = parsers.make_fix
    monkeypatch.setattr(parsers, "make_fix", lambda *a, **k: built.append(1) or real(*a, **k))
    monkeypatch.setattr(store, "MAX_FIXES", 5)
    rows = "\n".join(f"2025-06-01T12:00:{i:02d}Z,1,2" for i in range(50))
    mid = mission(client)
    r = client.post(f"{P}/missions/{mid}/track/file", files={"file": ("t.csv", ("time,lat,lon\n" + rows).encode())},
                    data={"format": "csv"})
    assert r.status_code == 409 and "at most 5" in r.text
    assert len(built) == 6  # stopped at the first row over the cap, not after all 50
    assert client.get(f"{P}/missions/{mid}").json()["fix_count"] == 0


def test_cap_counts_distinct_timestamps_so_duplicate_reupload_still_works(monkeypatch):
    monkeypatch.setattr(store, "MAX_FIXES", 3)
    rows = "\n".join(["2025-06-01T12:00:00Z,1,2"] * 10 + ["2025-06-01T12:00:01Z,1,2"])
    r = parsers.parse_csv(("time,lat,lon\n" + rows).encode(), max_fixes=3)
    # same-timestamp rows are dropped while parsing (bounded memory, ledger finding 7) but still counted
    assert len(r.fixes) == 2 and r.duplicates == 9 and len(r.fixes) + r.duplicates == 11


def test_parse_runs_off_the_event_loop(monkeypatch, client):
    import threading
    seen = []
    real = parsers.parse_csv
    monkeypatch.setitem(__import__("modeling_api.routers.missions", fromlist=["x"])._PARSERS, "csv",
                        lambda *a: seen.append(threading.current_thread().name) or real(*a))
    mid = mission(client)
    r = client.post(f"{P}/missions/{mid}/track/file", files={"file": ("t.csv", b"time,lat,lon\n2025-06-01T12:00:00Z,1,2\n")},
                    data={"format": "csv"})
    assert r.status_code == 200 and seen
    # TestClient drives the app on an anyio portal thread; the parser must run on a different (worker) thread
    assert seen[0] != threading.main_thread().name


def test_parsed_fixes_are_equal_to_validated_ones():
    r = parsers.parse_csv(b"time,lat,lon,heading,cog,sog_kt,hdop\n2025-06-01T12:00:00Z,1,2,90,91,5,1.5\n")
    f = r.fixes[0]
    assert f == TrackFix(t_utc=f.t_utc, lat=1, lon=2, heading_true_deg=90, cog_true_deg=91, sog_kt=5, hdop=1.5,
                         quality="good", source="csv")
    assert f.model_fields_set == TrackFix.model_fields.keys()


# ---- 6. EXIF DateTime fallback

def test_exif_datetime_tag_only_is_not_a_capture_time():
    data = make_image(extra_ifd0={306: "2025:06:01 08:00:00"}, offset="-04:00")
    info = exif.extract_exif(data)
    rt = exif.resolve_time(info, MediaMetadata(exif_utc_offset_min=-240))
    assert rt.captured_utc is None and rt.source is None
    assert "DateTime" in rt.note and "not a capture time" in rt.note


def test_exif_datetime_original_wins_over_datetime():
    data = make_image(dto="2025:06:01 08:00:00", offset="-04:00", extra_ifd0={306: "2030:01:01 00:00:00"})
    rt = exif.resolve_time(exif.extract_exif(data), MediaMetadata())
    assert rt.captured_utc == datetime(2025, 6, 1, 12, tzinfo=UTC)


# ---- 7. GPX safety

GPX = ('<?xml version="1.0" encoding="{enc}"?>{dt}<gpx><trkpt lat="1" lon="2"><time>2025-06-01T12:00:00Z</time></trkpt></gpx>')


def test_gpx_utf16_with_doctype_refused():
    for enc in ("utf-16", "utf-16-le", "utf-16-be"):
        doc = GPX.format(enc="UTF-16", dt='<!DOCTYPE x [<!ENTITY a "b">]>')
        with pytest.raises(parsers.TrackParseError, match="UTF-8"):
            parsers.parse_gpx(doc.encode(enc))
    with pytest.raises(parsers.TrackParseError, match="UTF-8"):  # BOM-less UTF-16 with no declaration
        parsers.parse_gpx("<gpx/>".encode("utf-16-le"))
    with pytest.raises(parsers.TrackParseError, match="UTF-8"):  # declared non-UTF-8 encoding
        parsers.parse_gpx(GPX.format(enc="ISO-8859-1", dt="").encode("latin-1"))


def test_gpx_doctype_after_64kb_and_case_variants_refused():
    pad = "<!-- " + "x" * 70_000 + " -->"
    for decl in ('<!DOCTYPE x>', '<!doctype x>', '<!DocType x [<!EnTiTy a "b">]>', '<!ENTITY a "b">'):
        with pytest.raises(parsers.TrackParseError, match="DOCTYPE|entity"):
            parsers.parse_gpx(GPX.format(enc="UTF-8", dt=pad + decl).encode())
    ok = parsers.parse_gpx(GPX.format(enc="utf-8", dt=pad).encode())
    assert len(ok.fixes) == 1
    assert len(parsers.parse_gpx(b"\xef\xbb\xbf" + GPX.format(enc="UTF-8", dt="").encode()).fixes) == 1


# ---- 8/9. locate

def index(*rows):
    return TrackIndex.from_rows([(int(t * 1e6), lat, lon, None, None, None, None, q, "csv") for t, lat, lon, q in rows])


T0 = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_event_just_outside_track_is_before_after_not_valid():
    base = T0.timestamp()
    ix = index((base, 0, 0, "good"), (base + 60, 0, 0.01, "good"))
    for dt, method in ((-0.4, "before_track"), (60.4, "after_track")):
        loc = locate(ix, T0 + timedelta(seconds=dt), 300)
        assert loc.method == method and loc.lat is None and loc.validity.state == "limited"
    # at the fix (within 1 ms) it is still the fix; interior 0.4 s from a fix still snaps
    assert locate(ix, T0 - timedelta(microseconds=800), 300).method == "exact_fix"
    assert locate(ix, T0 + timedelta(seconds=60, microseconds=900), 300).method == "exact_fix"
    assert locate(ix, T0 + timedelta(seconds=0.4), 300).method == "exact_fix"
    assert locate(ix, T0, 300).validity.state == "valid"


def test_interpolated_between_degraded_fixes_says_so():
    base = T0.timestamp()
    for qs, flagged in ((("good", "good"), False), (("good", "degraded"), True), (("unknown", "good"), True)):
        ix = index((base, 0, 0, qs[0]), (base + 60, 0, 0.01, qs[1]))
        codes = [r.code for r in locate(ix, T0 + timedelta(seconds=30), 300).validity.reasons]
        assert "INTERPOLATED_POSITION" in codes and ("FIX_QUALITY_NOT_GOOD" in codes) == flagged


# ---- 10. NMEA hygiene

@pytest.mark.parametrize("mode,ok", [("A", True), ("D", True), ("", True), ("E", False), ("S", False), ("M", False),
                                     ("N", False), ("F", False)])
def test_rmc_modes(mode, ok):
    r = parsers.parse_nmea(nm(rmc("120000", mode=mode)))
    assert len(r.fixes) == int(ok) and r.rejected == int(not ok)


def test_nmea_hemisphere_seconds_and_checksum_hygiene():
    bad = [rmc("120000", ns="E"), rmc("120000", ew="N"), rmc("120000", ns="X"), gga("120000", ns="W"), gga("120000", ew="S"),
           rmc("120060"), gga("120060"), gga("120000").replace("*", "*0"), gga("120000")[:-1], gga("120000") + " 1",
           gga("120000")[:-3] + "*G1"]
    r = parsers.parse_nmea(nm(*bad), date(2025, 6, 1))
    assert r.fixes == [] and r.rejected == len(bad), r.errors
    good = parsers.parse_nmea(nm(gga("120059", ns="S", ew="E"), rmc("120000", ns="N", ew="W")), date(2025, 6, 1))
    assert len(good.fixes) == 2
    assert parsers.nmea_checksum_ok("$A*041") is False and parsers.nmea_checksum_ok("$A*4") is False


# ---- 11. CSV speed column

def test_bare_speed_column_ignored_with_one_warning():
    r = parsers.parse_csv(b"time,lat,lon,speed\n2025-06-01T12:00:00Z,1,2,10\n2025-06-01T12:00:01Z,1,2,11\n")
    assert len(r.fixes) == 2 and all(f.sog_kt is None for f in r.fixes) and r.rejected == 0
    assert len(r.errors) == 1 and "speed" in r.errors[0] and "unit" in r.errors[0]


@pytest.mark.parametrize("name", ["sog", "sog_kt", "speed_kt", "speed_kn", "knots"])
def test_knots_named_speed_columns_are_read(name):
    r = parsers.parse_csv(f"time,lat,lon,{name}\n2025-06-01T12:00:00Z,1,2,10\n".encode())
    assert r.fixes[0].sog_kt == 10 and r.errors == []
