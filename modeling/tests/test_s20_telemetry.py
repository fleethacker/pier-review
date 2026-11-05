"""S20: declared NMEA 0183 subset, validating ingest, bounded storage and source arbitration. Synthetic fixtures."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from modeling_api.main import app
from mooring.core.schemas import EnvironmentSnapshot, TelemetryBatch, TelemetryRecord
from mooring.telemetry import ingest as ing
from mooring.telemetry import nmea

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def sentence(body: str) -> str:
    return f"${body}*{nmea.checksum(body)}"


MWV = sentence("WIMWV,045.0,R,18.5,N,A")


# ---------- NMEA ----------

def test_valid_mwv_and_hdt_decode_with_unit_conversion():
    w = nmea.decode(MWV + "\r\n")
    assert (w.reference, w.angle_from_deg, w.speed_kt) == ("relative", 45.0, 18.5)
    assert nmea.decode(sentence("IIMWV,270.0,T,10.0,M,A")).speed_kt == pytest.approx(10 / 0.514444)
    assert nmea.decode(sentence("IIMWV,270.0,T,37.04,K,A")).speed_kt == pytest.approx(20.0, rel=1e-3)
    assert nmea.decode(sentence("HEHDT,123.4,T")).true_deg == 123.4


def test_vtg_gga_and_dpt_declared_subset():
    assert nmea.decode(sentence("GPVTG,123.4,T,,M,12.5,N,23.2,K")).speed_kt == 12.5
    pos = nmea.decode(sentence("GPGGA,123519,3657.510,N,07619.830,W,1,08,0.9,5.0,M,0.0,M,,"))
    assert pos.latitude == pytest.approx(36.9585) and pos.longitude == pytest.approx(-76.3305)
    assert nmea.decode(sentence("SDDPT,12.3,-0.7")).depth_m == 12.3


@pytest.mark.parametrize("raw,code", [
    ("$WIMWV,045.0,R,18.5,N,A*00", "CHECKSUM_MISMATCH"),
    ("$WIMWV,045.0,R,18.5,N,A", "MISSING_CHECKSUM"),
    ("$WIMWV,045.0,R,18.5,N,A*ZZ", "BAD_CHECKSUM_FORMAT"),
    ("WIMWV,045.0,R,18.5,N,A*1E", "BAD_FRAMING"),
    ("!AIVDM,1,1,,A,x,0*00", "BAD_FRAMING"),
    (sentence("WIGGA,1,2,3"), "BAD_FIELD_COUNT"),
    (sentence("WIMWV,045.0,R,18.5,N,V"), "DATA_NOT_VALID"),
    (sentence("WIMWV,045.0,X,18.5,N,A"), "BAD_REFERENCE"),
    (sentence("WIMWV,045.0,R,18.5,Q,A"), "BAD_UNITS"),
    (sentence("WIMWV,045.0,R,abc,N,A"), "BAD_NUMBER"),
    (sentence("WIMWV,400.0,R,18.5,N,A"), "OUT_OF_RANGE"),
    (sentence("WIMWV,045.0,R,18.5,N"), "BAD_FIELD_COUNT"),
    (sentence("HEHDT,123.4,M"), "BAD_FIELD_COUNT"),
    ("$" + "A" * 90 + "*00", "SENTENCE_TOO_LONG"),
])
def test_malformed_unsupported_and_bad_input_is_rejected_with_a_code(raw, code):
    with pytest.raises(nmea.NmeaError) as e:
        nmea.decode(raw)
    assert e.value.code == code


def test_apparent_to_true_wind_with_explicit_frames():
    # True wind from the east (090) at 10 kt; vessel heading north at 10 kt over ground.
    # apparent = true - vessel: wind velocity (-10, 0) - (0, 10) = (-10, -10): 14.14 kt from 045 relative to the bow.
    app_w = nmea.Wind("relative", 45.0, math.hypot(10, 10))
    t = nmea.true_wind(app_w, heading_true_deg=0.0, sog_kt=10.0, cog_true_deg=0.0)
    assert (t.reference, round(t.angle_from_deg, 6), round(t.speed_kt, 6)) == ("true", 90.0, 10.0)
    # Heading east: the same apparent reading is rotated into the true frame.
    t2 = nmea.true_wind(nmea.Wind("relative", 0.0, 20.0), 0.0, 10.0, 0.0)   # head wind 20 kt apparent, moving north 10 kt: true 10 kt from north
    assert (round(t2.angle_from_deg, 6), round(t2.speed_kt, 6)) == (0.0, 10.0)
    at_rest = nmea.true_wind(nmea.Wind("relative", 90.0, 12.0), 0.0, 0.0, 0.0)  # starboard beam, no motion
    assert (round(at_rest.angle_from_deg, 6), round(at_rest.speed_kt, 6)) == (90.0, 12.0)
    with pytest.raises(nmea.NmeaError):
        nmea.true_wind(nmea.Wind("true", 10.0, 5.0), 0.0, 0.0, 0.0)


# ---------- ingest ----------

SENSORS = [ing.Sensor("LC-2", "DDG-1", 2, "cal-7", NOW - timedelta(days=30), NOW + timedelta(days=30), 0.0, 400_000.0),
           ing.Sensor("LC-3", "DDG-1", 3, "cal-4", NOW - timedelta(days=30), NOW + timedelta(days=30), 0.0, 400_000.0)]


def lc(**kw):
    base = dict(source="load_cell", t_utc=NOW, sensor_id="LC-2", vessel_id="DDG-1", line_number=2, tension_lbf=31_000.0, calibration_rev="cal-7", units="lbf", seq=1)
    base.update(kw)
    return TelemetryRecord(**base)


def nm(s=MWV, **kw):
    return TelemetryRecord(source="ship_nmea", t_utc=NOW, sentence=s, **kw)


def run(records, i=None):
    i = i or ing.Ingest(SENSORS, clock=lambda: NOW)
    return i.ingest(TelemetryBatch(records=records)), i


def test_good_records_are_adopted_with_provenance_and_independent_channels():
    r, i = run([nm(seq=1), lc(), lc(sensor_id="LC-3", line_number=3, calibration_rev="cal-4", tension_lbf=12_000.0, seq=1)])
    assert r.accepted == 3 and r.rejected == 0
    assert i.latest["load_cell:LC-2"].record.tension_lbf == 31_000.0 and i.latest["load_cell:LC-3"].record.tension_lbf == 12_000.0   # no overwrite
    assert "checksum verified" in i.latest["ship_nmea:MWV"].provenance and i.latest["load_cell:LC-2"].record.received_utc == NOW


@pytest.mark.parametrize("rec,code", [
    (nm("$WIMWV,045.0,R,18.5,N,A*00"), "CHECKSUM_MISMATCH"),
    (lc(units="kN"), "BAD_UNITS"),
    (lc(vessel_id="CG-9"), "WRONG_VESSEL"),
    (lc(line_number=3), "WRONG_CHANNEL"),
    (lc(sensor_id="LC-9"), "UNKNOWN_SENSOR"),
    (lc(calibration_rev="cal-1"), "CALIBRATION_MISMATCH"),
    (lc(t_utc=NOW + timedelta(days=60)), "FUTURE_TIMESTAMP"),
    (lc(tension_lbf=-5.0), "OUT_OF_BOUNDS"),
    (lc(tension_lbf=900_000.0), "OUT_OF_BOUNDS"),
    (lc(t_utc=NOW - timedelta(hours=2)), "STALE_RECORD"),
    (TelemetryRecord(source="ais", t_utc=NOW, mmsi="123"), "AIS_UNSUPPORTED"),
    (TelemetryRecord(source="load_cell", t_utc=NOW, line_number=2, tension_lbf=1.0), "MISSING_FIELDS"),
])
def test_rejections_and_rejected_input_leaves_no_trace(rec, code):
    r, i = run([rec])
    assert r.accepted == 0 and r.rejections[0].code == code and i.latest == {} and i.history == {}


def test_expired_calibration_is_rejected():
    old = ing.Sensor("LC-2", "DDG-1", 2, "cal-7", NOW - timedelta(days=90), NOW - timedelta(days=1))
    r, i = run([lc(t_utc=NOW)], ing.Ingest([old], clock=lambda: NOW))
    assert r.rejections[0].code == "CALIBRATION_EXPIRED" and i.latest == {}


def test_duplicate_replayed_and_out_of_order_messages():
    i = ing.Ingest(SENSORS, clock=lambda: NOW)
    assert run([lc(seq=5)], i)[0].accepted == 1
    dup = run([lc(seq=5)], i)[0]
    assert dup.rejections[0].code == "DUPLICATE_OR_REPLAY"
    older = run([lc(seq=6, t_utc=NOW - timedelta(seconds=30))], i)[0]
    assert older.rejections[0].code == "OUT_OF_ORDER"
    assert i.latest["load_cell:LC-2"].record.seq == 5 and len(i.history["load_cell:LC-2"]) == 1


def test_storage_is_bounded():
    i = ing.Ingest(SENSORS, clock=lambda: NOW)
    for k in range(ing.HISTORY + 50):
        run([lc(seq=k, t_utc=NOW)], i)
    assert len(i.history["load_cell:LC-2"]) == ing.HISTORY
    with pytest.raises(ing.BatchTooLarge):
        run([lc(seq=10_000 + k) for k in range(ing.MAX_BATCH + 1)], i)


def test_mixed_batch_accepts_good_records_and_reports_each_bad_one():
    r, i = run([nm(seq=1), lc(units="N"), lc(seq=2, tension_lbf=500.0)])
    assert (r.accepted, r.rejected) == (2, 1) and r.rejections[0].index == 1 and "record 1: BAD_UNITS" in r.errors[0]


# ---------- arbitration ----------

def snap(wind):
    return EnvironmentSnapshot(wind_speed_kt=wind, wind_gust_kt=wind + 4, wind_from_true_deg=0, current_speed_kt=0.3, current_set_true_deg=0, water_level_mllw_ft=0)


def test_sensor_never_silently_overrides_a_qualified_forecast_or_manual_input():
    d = ing.arbitrate([ing.Candidate("observation", snap(30), label="sensor"), ing.Candidate("forecast", snap(15), label="forecast")])
    assert d.chosen.kind == "forecast" and any("conflict" in n and "higher-priority" in n for n in d.notes)
    d2 = ing.arbitrate([ing.Candidate("observation", snap(30), label="sensor"), ing.Candidate("manual", snap(12), label="deck officer"), ing.Candidate("forecast", snap(15))])
    assert d2.chosen.kind == "manual"


def test_stale_bad_quality_or_unqualified_sources_are_rejected_and_cannot_influence():
    d = ing.arbitrate([ing.Candidate("observation", snap(30), age_s=5_000, label="old sensor"), ing.Candidate("observation", snap(31), quality="suspect", label="bad sensor"),
                       ing.Candidate("forecast", snap(10), qualified=False, label="raw forecast")])
    assert d.chosen is None and len(d.notes) == 4 and "no usable source" in d.notes[-1]
    ok = ing.arbitrate([ing.Candidate("observation", snap(14), age_s=30)])
    assert ok.chosen.kind == "observation"


# ---------- HTTP ----------

client = TestClient(app)


def test_http_ingest_enforces_the_key_only_when_configured(monkeypatch):
    body = {"records": [{"source": "ship_nmea", "t_utc": datetime.now(UTC).isoformat(), "sentence": MWV}]}
    assert client.post("/api/v1/telemetry/batch", json=body).status_code == 202          # local demo mode: no key configured
    monkeypatch.setenv("MOORING_TELEMETRY_KEY", "s3cret")
    assert client.post("/api/v1/telemetry/batch", json=body).status_code == 401
    assert client.post("/api/v1/telemetry/batch", json=body, headers={"X-Telemetry-Key": "wrong"}).status_code == 401
    ok = client.post("/api/v1/telemetry/batch", json=body, headers={"X-Telemetry-Key": "s3cret"})
    assert ok.status_code == 202 and ok.json()["accepted"] == 1


def test_websocket_ingest_uses_the_same_configured_key(monkeypatch):
    monkeypatch.setenv("MOORING_TELEMETRY_KEY", "s3cret")
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/ws/telemetry?limit=1"):
            pass
    assert denied.value.code == 1008
    with client.websocket_connect("/ws/telemetry?limit=1", headers={"X-Telemetry-Key": "s3cret"}) as ws:
        ws.send_json({})
        assert ws.receive_json()["rejected"] == 1
