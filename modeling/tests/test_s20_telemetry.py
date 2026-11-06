"""S20: declared NMEA 0183 subset, validating ingest, bounded storage and source arbitration. Synthetic fixtures."""

import json
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
    with pytest.raises(nmea.NmeaError, match="coordinate"):
        nmea.decode(sentence("GPGGA,123519,3699.000,N,07619.830,W,1,08,0.9,5.0,M,0.0,M,,"))


@pytest.mark.parametrize("mode", ["E", "M", "S", "N", "X", ""])
def test_non_observed_vtg_modes_cannot_update_good_telemetry(mode):
    result, state = run([nm(sentence(f"GPVTG,123.4,T,,M,12.5,N,23.2,K,{mode}"))])
    assert result.accepted == 0 and result.rejections[0].code == "DATA_NOT_VALID"
    assert state.latest == {} and state.history == {}


@pytest.mark.parametrize("mode", ["A", "D"])
def test_observed_vtg_modes_are_accepted(mode):
    assert nmea.decode(sentence(f"GPVTG,123.4,T,,M,12.5,N,23.2,K,{mode}")) == nmea.Course(123.4, 12.5)


@pytest.mark.parametrize("quality", [0, 3, 6, 7, 8, 9, -1])
def test_unsupported_gga_quality_cannot_update_good_telemetry(quality):
    result, state = run([nm(sentence(f"GPGGA,123519,3657.510,N,07619.830,W,{quality},08,0.9,5.0,M,0.0,M,,"))])
    assert result.accepted == 0 and result.rejections[0].code == "DATA_NOT_VALID"
    assert state.latest == {} and state.history == {}


@pytest.mark.parametrize("quality", [1, 2, 4, 5])
def test_declared_gnss_quality_is_accepted(quality):
    assert nmea.decode(sentence(f"GPGGA,123519,3657.510,N,07619.830,W,{quality},08,0.9,5.0,M,0.0,M,,")).fix_quality == quality


@pytest.mark.parametrize("latitude,longitude", [
    ("3699.000", "07619.830"), ("3657.510", "07660.000"),
    ("3657.510", "18100.000"), ("9000.001", "07619.830"),
    ("3.65751e3", "07619.830"), ("+3657.510", "07619.830"),
    (" 3657.510", "07619.830"), ("3657.510", "7619.830"),
])
def test_gga_rejects_bad_coordinate_format_or_range(latitude, longitude):
    result, state = run([nm(sentence(f"GPGGA,123519,{latitude},N,{longitude},W,1,08,0.9,5.0,M,0.0,M,,"))])
    assert result.accepted == 0 and result.rejected == 1
    assert state.latest == {} and state.history == {}


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
    with pytest.raises(nmea.NmeaError, match="outside its valid range"):
        nmea.true_wind(nmea.Wind("relative", 10.0, 5.0), 360.0, 0.0, 0.0)


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
    assert i.latest[("local-demo", "DDG-1", "load_cell:LC-2")].record.tension_lbf == 31_000.0 and i.latest[("local-demo", "DDG-1", "load_cell:LC-3")].record.tension_lbf == 12_000.0   # no overwrite
    assert "checksum verified" in i.latest[("local-demo", None, "ship_nmea:MWV")].provenance and i.latest[("local-demo", "DDG-1", "load_cell:LC-2")].record.received_utc == NOW


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
    key = ("local-demo", "DDG-1", "load_cell:LC-2")
    assert i.latest[key].record.seq == 5 and len(i.history[key]) == 1
    assert (key, 6) not in i.seen  # Rejected ordering never reserves a sequence.
    assert run([lc(seq=6, t_utc=NOW)], i)[0].accepted == 1


def test_storage_is_bounded():
    i = ing.Ingest(SENSORS, clock=lambda: NOW)
    for k in range(ing.HISTORY + 50):
        run([lc(seq=k, t_utc=NOW)], i)
    assert len(i.history[("local-demo", "DDG-1", "load_cell:LC-2")]) == ing.HISTORY
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


def test_websocket_recovers_after_invalid_json_and_schema(monkeypatch):
    from modeling_api.backend import telemetry
    isolated = ing.Ingest(clock=lambda: NOW)
    monkeypatch.setattr(telemetry, "ingest", isolated.ingest)
    with client.websocket_connect("/ws/telemetry?limit=3") as ws:
        ws.send_text("{invalid json")
        assert ws.receive_json()["rejected"] == 1
        ws.send_json(["not a record"])
        assert ws.receive_json()["rejected"] == 1
        assert isolated.latest == {}
        ws.send_json(nm().model_dump(mode="json"))
        assert ws.receive_json()["accepted"] == 1
    assert len(isolated.latest) == 1


def test_websocket_binary_record_closes_with_declared_error():
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.send_bytes(b"not JSON text")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1003


def test_non_ascii_telemetry_key_is_rejected_without_server_error(monkeypatch):
    monkeypatch.setenv("MOORING_TELEMETRY_KEY", "s3cret")
    headers = {b"x-telemetry-key": "wrong-é".encode()}
    assert client.post("/api/v1/telemetry/batch", json={"records": []}, headers=headers).status_code == 401
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/ws/telemetry", headers=headers):
            pass
    assert denied.value.code == 1008


@pytest.fixture
def authorized_ingest(monkeypatch):
    state = ing.Ingest(SENSORS, clock=lambda: NOW)
    monkeypatch.setattr(ing, "DEFAULT", state)
    monkeypatch.setenv("MOORING_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MOORING_API_KEYS", json.dumps({"alice": "a" * 32, "bob": "b" * 32}))
    monkeypatch.setenv("MOORING_TELEMETRY_VESSELS", json.dumps({"alice": ["DDG-1"], "bob": ["CG-2"]}))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "0")
    monkeypatch.delenv("MOORING_TELEMETRY_KEY", raising=False)
    return state


def authorized_headers(owner):
    return {"Authorization": "Bearer " + ("a" if owner == "alice" else "b") * 32}


def test_http_authorizes_vessels_before_sequence_or_time_can_poison_state(authorized_ingest):
    state = authorized_ingest

    def post(owner, record):
        response = client.post("/api/v1/telemetry/batch", headers=authorized_headers(owner),
                               json={"records": [record.model_dump(mode="json")]})
        assert response.status_code == 202
        return response.json()

    hdt = sentence("HEHDT,123.4,T")
    assert post("alice", nm(hdt, seq=1, vessel_id="DDG-1"))["accepted"] == 1
    forged = nm(hdt, seq=2, vessel_id="DDG-1").model_copy(update={"t_utc": NOW + timedelta(seconds=59)})
    rejected = post("bob", forged)
    assert rejected["accepted"] == 0 and rejected["rejections"][0]["code"] == "VESSEL_NOT_AUTHORIZED"
    valid = nm(hdt, seq=2, vessel_id="DDG-1").model_copy(update={"t_utc": NOW + timedelta(seconds=1)})
    assert post("alice", valid)["accepted"] == 1
    assert post("bob", nm(hdt, seq=1, vessel_id="CG-2"))["accepted"] == 1
    assert post("bob", lc())["rejections"][0]["code"] == "VESSEL_NOT_AUTHORIZED"
    assert post("alice", lc())["accepted"] == 1
    assert set(state.latest) == {("alice", "DDG-1", "ship_nmea:HDT"), ("bob", "CG-2", "ship_nmea:HDT"),
                                 ("alice", "DDG-1", "load_cell:LC-2")}
    assert [item.record.seq for item in state.history[("alice", "DDG-1", "ship_nmea:HDT")]] == [1, 2]
    assert state.last_t[("bob", "CG-2", "ship_nmea:HDT")] == NOW
    assert (("bob", "DDG-1", "ship_nmea:HDT"), 2) not in state.seen


def test_websocket_uses_authenticated_principal_and_same_vessel_policy(authorized_ingest):
    state = authorized_ingest
    with client.websocket_connect("/ws/telemetry?limit=3", headers=authorized_headers("bob")) as ws:
        ws.send_json(nm(seq=4, vessel_id="DDG-1").model_dump(mode="json"))
        denied = ws.receive_json()
        assert denied["accepted"] == 0 and denied["rejections"][0]["code"] == "VESSEL_NOT_AUTHORIZED"
        ws.send_json(nm(seq=4).model_dump(mode="json"))
        assert ws.receive_json()["rejections"][0]["code"] == "VESSEL_NOT_AUTHORIZED"
        assert state.latest == {} and state.seen == {}
        ws.send_json(nm(seq=4, vessel_id="CG-2").model_dump(mode="json"))
        assert ws.receive_json()["accepted"] == 1
    with client.websocket_connect("/ws/telemetry?limit=1", headers=authorized_headers("alice")) as ws:
        ws.send_json(nm(seq=4, vessel_id="DDG-1").model_dump(mode="json"))
        assert ws.receive_json()["accepted"] == 1
    assert set(state.latest) == {("alice", "DDG-1", "ship_nmea:MWV"), ("bob", "CG-2", "ship_nmea:MWV")}


@pytest.mark.parametrize("mapping", [None, "", "{secret:bad}", "[]", '{"alice":"DDG-1"}',
                                    '{"alice":["DDG-1"],"alice":["CG-2"]}',
                                    "x" * (ing.MAX_AUTH_CONFIG_CHARS + 1),
                                    '{"alice":[' + "[" * 1200 + "0" + "]" * 1200 + "]}"])
def test_missing_or_invalid_vessel_policy_fails_closed_without_leaking_configuration(authorized_ingest, monkeypatch, mapping):
    if mapping is None:
        monkeypatch.delenv("MOORING_TELEMETRY_VESSELS", raising=False)
    else:
        monkeypatch.setenv("MOORING_TELEMETRY_VESSELS", mapping)
    response = client.post("/api/v1/telemetry/batch", headers=authorized_headers("alice"),
                           json={"records": [nm(seq=1, vessel_id="DDG-1").model_dump(mode="json")]})
    assert response.status_code == 202
    assert response.json()["accepted"] == 0
    assert response.json()["rejections"] == [{"index": 0, "code": "AUTHORIZATION_UNAVAILABLE",
                                              "message": "Telemetry vessel authorization is not configured correctly"}]
    assert authorized_ingest.latest == {} and authorized_ingest.seen == {}


def test_authorized_same_vessel_still_has_separate_principal_state(authorized_ingest, monkeypatch):
    monkeypatch.setenv("MOORING_TELEMETRY_VESSELS", '{"alice":["DDG-1"],"bob":["DDG-1"]}')
    for owner, offset in (("alice", 59), ("bob", 0)):
        record = nm(vessel_id="DDG-1", seq=1).model_copy(update={"t_utc": NOW + timedelta(seconds=offset)})
        response = client.post("/api/v1/telemetry/batch", headers=authorized_headers(owner),
                               json={"records": [record.model_dump(mode="json")]})
        assert response.status_code == 202 and response.json()["accepted"] == 1
    assert len(authorized_ingest.history) == 2


def test_local_demo_keeps_vessels_and_legacy_unassigned_channel_separate(monkeypatch):
    monkeypatch.delenv("MOORING_TELEMETRY_VESSELS", raising=False)
    result, state = run([nm(seq=1, vessel_id="DDG-1"), nm(seq=1, vessel_id="CG-2"), nm(seq=1)])
    assert result.accepted == 3 and len(state.latest) == 3
    assert set(state.latest) == {("local-demo", vessel, "ship_nmea:MWV") for vessel in ("DDG-1", "CG-2", None)}


def test_new_channel_capacity_rejects_without_evicting_existing_order(monkeypatch):
    monkeypatch.setattr(ing, "MAX_CHANNELS", 1)
    result, state = run([nm(seq=1, vessel_id="DDG-1"), nm(seq=1, vessel_id="CG-2")])
    assert result.accepted == 1 and result.rejections[0].code == "CHANNEL_LIMIT"
    assert len(state.latest) == len(state.history) == len(state.last_t) == len(state.seen) == 1
    assert run([nm(seq=2, vessel_id="DDG-1")], state)[0].accepted == 1
