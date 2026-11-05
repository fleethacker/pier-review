"""S5 track parsers: CSV, GPX, NMEA, GeoJSON, plus merge semantics (duplicates, reordering)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from mooring.core.schemas.missions import MissionCreate, TrackFix
from mooring.core.store import reset_db
from mooring.missions import parsers, store

FX = Path(__file__).parent / "fixtures" / "missions"


def fx(name):
    return (FX / name).read_bytes()


def t(h, m, s=0):
    return datetime(2025, 6, 1, h, m, s, tzinfo=UTC)


# ---- CSV

def test_csv_fixture_reports_each_bad_row_with_line_numbers():
    r = parsers.parse_csv(fx("track.csv"), utc_offset_min=0)
    # rows: 2..9 in the file; lat 95 (line 7), 'abc' (line 8) rejected; the epoch row (line 9) is valid
    assert [f.t_utc for f in r.fixes][:3] == [t(12, 0), t(12, 1), t(12, 0, 30)]
    # the fixture's one same-timestamp row is dropped at parse time (first kept) and counted, not stored twice
    assert len(r.fixes) == 5 and r.duplicates == 1 and r.rejected == 2
    assert r.errors[0].startswith("line 7:") and "out of range" in r.errors[0]
    assert r.errors[1].startswith("line 8:") and "lat is not a number" in r.errors[1]
    assert r.fixes[-1].t_utc == datetime(2025, 6, 1, 13, 0, 0, tzinfo=UTC)  # epoch 1748782800
    assert r.fixes[0].quality == "good" and r.fixes[0].sog_kt == 10.0 and r.fixes[0].source == "csv"


def test_csv_naive_timestamps_rejected_without_offset_and_converted_with_one():
    r = parsers.parse_csv(fx("track.csv"))
    naive = [e for e in r.errors if "naive" in e]
    assert len(naive) == 1 and naive[0].startswith("line 6:")   # 12:02:00 has no zone
    r2 = parsers.parse_csv(b"time,lat,lon\n2025-06-01 20:00:00,10,20\n", utc_offset_min=480)
    assert r2.fixes[0].t_utc == t(12, 0)  # +08:00 -> 12:00Z
    # an explicit zone in the data wins over utc_offset_min
    r3 = parsers.parse_csv(b"time,lat,lon\n2025-06-01T12:00:00Z,10,20\n", utc_offset_min=480)
    assert r3.fixes[0].t_utc == t(12, 0)


def test_csv_header_aliases_delimiters_bom_and_comments():
    data = "﻿# logger v2\nTimestamp;Latitude;Lng;HDG;Speed (kt)\n2025-06-01T12:00:00Z;1,5;2;370;4\n".encode()
    r = parsers.parse_csv(data)
    assert r.fixes == [] and r.rejected == 1  # '1,5' is not a number (decimal comma), 370 heading out of range
    ok = "﻿Timestamp;Latitude;Lng;HDG;Speed (kt)\n2025-06-01T12:00:00Z;1.5;2;360;4\n".encode()
    f = parsers.parse_csv(ok).fixes[0]
    assert (f.lat, f.lon, f.heading_true_deg, f.sog_kt) == (1.5, 2.0, 0.0, 4.0)


def test_csv_without_recognised_header_is_refused():
    with pytest.raises(parsers.TrackParseError, match="lacks a recognised column"):
        parsers.parse_csv(b"a,b,c\n1,2,3\n")
    with pytest.raises(parsers.TrackParseError, match="empty"):
        parsers.parse_csv(b"\n\n")


def test_csv_epoch_milliseconds_not_silently_accepted():
    r = parsers.parse_csv(b"time,lat,lon\n1748779200000,1,2\n")
    assert r.rejected == 1 and "milliseconds" in r.errors[0]


# ---- GPX

def test_gpx_points_without_time_rejected_and_wpt_accepted():
    r = parsers.parse_gpx(fx("track.gpx"))
    assert len(r.fixes) == 4 and r.rejected == 1
    assert r.errors == ["trkpt #3: no <time>"]
    assert r.fixes[0].quality == "good"                         # hdop 1.0
    assert r.fixes[2].sog_kt == pytest.approx(10.0, abs=1e-4)   # 5.144444 m/s
    assert r.fixes[3].lat == 36.95                              # the <wpt>


def test_gpx_rejects_doctype_and_malformed_xml():
    with pytest.raises(parsers.TrackParseError, match="DOCTYPE"):
        parsers.parse_gpx(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><gpx/>')
    with pytest.raises(parsers.TrackParseError, match="well-formed"):
        parsers.parse_gpx(b"<gpx><trkpt>")
    with pytest.raises(parsers.TrackParseError, match="no trkpt"):
        parsers.parse_gpx(b"<gpx/>")


# ---- NMEA

def test_nmea_fixture_validates_checksums_status_quality_and_merges_rmc_gga():
    r = parsers.parse_nmea(fx("track.nmea"))
    assert [f.t_utc for f in r.fixes] == [t(12, 0, 0), t(12, 0, 10), t(12, 0, 40)]
    assert r.rejected == 4
    assert r.errors == ["line 5: RMC status 'V' (not a valid fix)", "line 6: checksum mismatch",
                        "line 8: not an NMEA sentence", "line 9: GGA quality '0' (no fix)"]
    a, b, c = r.fixes
    assert (a.lat, a.lon) == (pytest.approx(36 + 53 / 60), pytest.approx(-(76 + 22 / 60)))
    assert (a.sog_kt, a.cog_true_deg, a.hdop, a.quality) == (10.0, 90.0, 0.9, "good")   # RMC + GGA merged
    assert (b.hdop, b.quality) == (2.5, "degraded")
    assert c.hdop is None and c.quality == "unknown"
    assert b.lat == pytest.approx(36 + 53.01 / 60)


def test_nmea_checksum_helper_and_missing_checksum():
    assert parsers.nmea_checksum_ok("$GPRMC,1*00") is False
    assert parsers.nmea_checksum_ok("$A*41") is True  # 'A' = 0x41
    assert parsers.nmea_checksum_ok("$GPRMC,1") is None
    sentence = "$GPGGA,120000,3653.0000,N,07622.0000,W,1,08,0.9,3.0,M,0.0,M,,"
    r = parsers.parse_nmea(sentence.encode(), date(2025, 6, 1))
    assert r.rejected == 1 and "missing checksum" in r.errors[0]


def test_nmea_gga_needs_a_date_and_rolls_over_midnight():
    r = parsers.parse_nmea(fx("gga_only.nmea"))
    assert r.fixes == [] and r.rejected == 2 and all("no date" in e for e in r.errors)
    r = parsers.parse_nmea(fx("gga_only.nmea"), nmea_date=date(2025, 6, 1))
    # 23:59:58 -> 00:00:02 crosses midnight: the day advances even with GGA only (earlier expectation kept the old date)
    assert [f.t_utc for f in r.fixes] == [datetime(2025, 6, 1, 23, 59, 58, tzinfo=UTC), datetime(2025, 6, 2, 0, 0, 2, tzinfo=UTC)]


def test_nmea_rmc_date_then_gga_across_midnight():
    def cs(b):
        x = 0
        for c in b:
            x ^= ord(c)
        return f"${b}*{x:02X}"
    lines = [cs("GPRMC,235958,A,3653.0000,N,07622.0000,W,5.0,90.0,010625,,,A"),
             cs("GPGGA,000002,3653.0001,N,07622.0000,W,1,08,1.0,3.0,M,0.0,M,,")]
    r = parsers.parse_nmea("\n".join(lines).encode())
    assert [f.t_utc for f in r.fixes] == [datetime(2025, 6, 1, 23, 59, 58, tzinfo=UTC), datetime(2025, 6, 2, 0, 0, 2, tzinfo=UTC)]


# ---- GeoJSON

def test_geojson_points_and_linestrings_with_times():
    r = parsers.parse_geojson(fx("track.geojson"))
    assert len(r.fixes) == 4 and r.rejected == 3
    assert r.fixes[0].sog_kt == 8.5
    assert [f.t_utc for f in r.fixes[1:]] == [t(12, 1), t(12, 2), t(12, 3)]
    assert r.fixes[1].lat == 36.92 and r.fixes[1].lon == -76.3
    assert r.errors[0] == "feature 2: Point has no time property"
    assert "2 coordinates but 1 times" in r.errors[1]
    assert len(r.errors) == 2  # a mismatched line is one error but rejects each of its vertices


def test_geojson_naive_time_needs_offset():
    doc = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {"time": "2025-06-01T12:00:00"}}
    assert parsers.parse_geojson(json.dumps(doc).encode()).rejected == 1
    assert parsers.parse_geojson(json.dumps(doc).encode(), utc_offset_min=-60).fixes[0].t_utc == t(13, 0)


def test_geojson_not_json_and_wrong_root():
    with pytest.raises(parsers.TrackParseError):
        parsers.parse_geojson(b"{")
    with pytest.raises(parsers.TrackParseError):
        parsers.parse_geojson(b'{"type":"Point"}')


# ---- merge semantics

@pytest.fixture
def mission():
    reset_db(":memory:")
    return store.create_mission(MissionCreate(name="m", vessel_id="v")).mission_id


def fix(h, m, s, lat=0.0, lon=0.0):
    return TrackFix(t_utc=t(h, m, s), lat=lat, lon=lon)


def test_ingest_counts_duplicates_reordered_sorted_and_merges_with_existing(mission):
    batch = [fix(12, 0, 10, lon=0.1), fix(12, 0, 0, lon=0.0), fix(12, 0, 10, lon=0.9), fix(12, 0, 20, lon=0.2)]
    r = store.ingest(mission, batch, rejected=1, errors=["x"], fmt="json")
    assert (r.accepted, r.duplicates, r.reordered, r.rejected, r.fix_count) == (3, 1, 1, 1, 3)
    ix = store.load_index(mission)
    assert ix.t == sorted(ix.t) and ix.lon == [0.0, 0.1, 0.2]          # first duplicate kept
    # second upload overlapping the first: existing timestamps are duplicates, new ones are merged in order
    r2 = store.ingest(mission, [fix(12, 0, 15, lon=0.15), fix(12, 0, 20, lon=5.0)], 0, [], "json")
    assert (r2.accepted, r2.duplicates, r2.fix_count) == (1, 1, 4)
    assert store.load_index(mission).lon == [0.0, 0.1, 0.15, 0.2]
    assert r2.start_utc == t(12, 0, 0) and r2.end_utc == t(12, 0, 20)


def test_ingest_enforces_fix_cap_atomically(mission, monkeypatch):
    monkeypatch.setattr(store, "MAX_FIXES", 3)
    store.ingest(mission, [fix(12, 0, 0), fix(12, 0, 1)], 0, [], "json")
    with pytest.raises(store.LimitExceeded):
        store.ingest(mission, [fix(12, 0, 2), fix(12, 0, 3)], 0, [], "json")
    assert store.get_mission(mission).fix_count == 2   # rolled back
