"""S5 mission storyboarding through the HTTP API: full flow, ownership, limits."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from modeling_api import security
from modeling_api.main import app
from mooring.core.store import reset_db
from mooring.missions import parsers
from s5_images import gps_tags, make_image

P = "/api/v1"
FX = Path(__file__).parent / "fixtures" / "missions"
A = {"Authorization": "Bearer " + "a" * 32}
B = {"Authorization": "Bearer " + "b" * 32}
DEG_M = 6_371_008.8 * 3.141592653589793 / 180


@pytest.fixture
def client(monkeypatch):
    reset_db(":memory:")
    return TestClient(app)


@pytest.fixture
def authed(monkeypatch):
    reset_db(":memory:")
    monkeypatch.setenv("MOORING_API_KEYS", json.dumps({"alice": "a" * 32, "bob": "b" * 32}))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "10000")
    monkeypatch.setattr(security, "RATE", security.RateLimit())
    return TestClient(app)


def new_mission(c, headers=None):
    r = c.post(f"{P}/missions", json={"name": "Harbor transit", "vessel_id": "DDG-51"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["mission_id"]


def csv_track():
    rows = ["time,lat,lon,heading,sog,hdop"]
    for i in range(7):   # equator, 60 s apart, 0.01 deg per fix; hole between 12:03 and 12:06 is 180 s long
        if i in (4, 5):
            continue
        rows.append(f"2025-06-01T12:{i:02d}:00Z,0.0,{0.01 * i:.4f},90,10,1.0")
    return "\n".join(rows) + "\n"


def upload_track(c, mid, body, fmt="csv", headers=None, **form):
    return c.post(f"{P}/missions/{mid}/track/file", files={"file": ("t." + fmt, body)}, data={"format": fmt, **form},
                  headers=headers)


def test_full_flow_create_track_images_reports_storyboard_geojson(client):
    mid = new_mission(client)
    r = upload_track(client, mid, csv_track())
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["accepted"], res["rejected"], res["duplicates"], res["fix_count"], res["format"]) == (5, 0, 0, 5, "csv")
    assert res["start_utc"].startswith("2025-06-01T12:00:00") and res["end_utc"].startswith("2025-06-01T12:06:00")

    # image 1: camera local time 08:00:30 at -04:00 (EXIF offset), exactly between fixes 12:00 and 12:01
    img1 = make_image(dto="2025:06:01 08:00:30", offset="-04:00", gps=gps_tags(0.0, 0.0053))
    # image 2: naive EXIF, supplied zone and a 90 s slow camera: 07:58:30 local +90 s = 08:00:00 -> 12:00:00Z... then
    # adjusted: the true time is 12:04:30 (inside the 180 s hole)
    img2 = make_image(dto="2025:06:01 08:03:00", gps=gps_tags(0.0, 0.0445))
    r1 = client.post(f"{P}/missions/{mid}/media", files={"image": ("a.jpg", img1, "image/jpeg")},
                     data={"metadata": json.dumps({"caption": "bridge wing"})})
    r2 = client.post(f"{P}/missions/{mid}/media", files={"image": ("b.jpg", img2, "image/jpeg")},
                     data={"metadata": json.dumps({"exif_utc_offset_min": -240, "camera_clock_offset_s": 90})})
    assert r1.status_code == r2.status_code == 201, (r1.text, r2.text)
    m1, m2 = r1.json(), r2.json()
    assert m1["captured_utc"].startswith("2025-06-01T12:00:30") and m1["time_source"] == "exif"
    assert m1["content_type"] == "image/jpeg" and m1["exif_lon"] == pytest.approx(0.0053, abs=1e-5)
    assert m2["captured_utc"].startswith("2025-06-01T12:04:30") and m2["camera_clock_offset_s"] == 90
    assert client.get(m1["url"]).content == img1
    assert client.get(m1["url"]).headers["content-type"] == "image/jpeg"

    rep1 = client.post(f"{P}/missions/{mid}/reports", json={"t_utc": "2025-06-01T12:02:00Z", "title": "Pilot aboard",
                                                           "body": "Pilot embarked.", "lat": 0.0, "lon": 0.0205})
    rep2 = client.post(f"{P}/missions/{mid}/reports", json={"t_utc": "2025-06-01T13:00:00Z", "title": "Secured"})
    assert rep1.status_code == rep2.status_code == 201
    assert len(client.get(f"{P}/missions/{mid}/reports").json()) == 2 and len(client.get(f"{P}/missions/{mid}/media").json()) == 2

    mission = client.get(f"{P}/missions/{mid}").json()
    assert (mission["fix_count"], mission["media_count"], mission["report_count"]) == (5, 2, 2)

    sb = client.get(f"{P}/missions/{mid}/storyboard", params={"max_interp_gap_s": 120}).json()
    st = sb["stats"]
    assert st["fix_count"] == 5 and st["duration_s"] == 360 and st["max_gap_s"] == 180 and st["gaps_over_limit"] == 1
    assert st["distance_nm"] == pytest.approx(0.06 * DEG_M / 1852, rel=1e-9)
    assert [e["event_id"] for e in sb["events"]] == [m1["media_id"], rep1.json()["report_id"], m2["media_id"],
                                                     rep2.json()["report_id"]]
    e1, er, e2, e3 = sb["events"]
    assert e1["located"]["method"] == "interpolated" and e1["located"]["lon"] == pytest.approx(0.005, abs=1e-9)
    assert e1["located"]["discrepancy_m"] == pytest.approx(0.0003 * DEG_M, rel=1e-4)
    assert e1["located"]["stated_source"] == "exif" and e1["located"]["validity"]["state"] == "limited"
    assert er["located"]["method"] == "exact_fix" and er["located"]["validity"]["state"] == "valid"
    assert er["located"]["discrepancy_m"] == pytest.approx(0.0005 * DEG_M, rel=1e-4) and "media_url" not in er
    assert e2["located"]["method"] == "gap" and "lat" not in e2["located"] and e2["located"]["gap_s"] == 180
    assert e2["located"]["stated_lat"] == 0.0
    assert e3["located"]["method"] == "after_track"
    codes = {r["code"] for r in sb["validity"]["reasons"]}
    assert sb["validity"]["state"] == "limited"
    assert {"TRACK_GAPS_OVER_LIMIT", "INTERPOLATED_POSITION", "POSITION_NOT_ESTABLISHED", "EXIF_UTC_OFFSET_ASSUMED",
            "CAMERA_CLOCK_OFFSET_APPLIED"} <= codes
    # 5 stored fixes are under max_points, so all come back
    assert [f["t_utc"][11:16] for f in sb["track"]] == ["12:00", "12:01", "12:02", "12:03", "12:06"]

    gj = client.get(f"{P}/missions/{mid}/storyboard.geojson", params={"max_interp_gap_s": 120})
    assert gj.headers["content-type"].startswith("application/geo+json")
    doc = gj.json()
    lines = [f for f in doc["features"] if f["geometry"]["type"] == "LineString"]
    # the 180 s hole splits the track: 12:00-12:03 and a lone 12:06 fix (kept as a timed Point)
    assert len(lines) == 1 and len(lines[0]["geometry"]["coordinates"]) == 4 and len(lines[0]["properties"]["times"]) == 4
    pts = {f["properties"]["id"]: f["properties"] for f in doc["features"] if f["properties"]["kind"] in ("image", "report")}
    assert set(pts) == {m1["media_id"], rep1.json()["report_id"]}
    assert pts[m1["media_id"]]["media_url"] == m1["url"] and pts[m1["media_id"]]["method"] == "interpolated"
    assert {u["id"] for u in doc["properties"]["unlocated_events"]} == {m2["media_id"], rep2.json()["report_id"]}
    assert [f["properties"]["kind"] for f in doc["features"]].count("track_point") == 1

    # the export re-imports as the original fixes; event markers are skipped, not rejected
    rt = parsers.parse_geojson(gj.content)
    assert rt.rejected == 0
    assert [(f.t_utc, f.lat, f.lon) for f in rt.fixes] == [
        (datetime(2025, 6, 1, 12, i, tzinfo=UTC), 0.0, 0.01 * i) for i in (0, 1, 2, 3, 6)]


def test_geojson_round_trip_through_a_second_mission(client):
    a = new_mission(client)
    upload_track(client, a, csv_track())
    gj = client.get(f"{P}/missions/{a}/storyboard.geojson").content
    b = new_mission(client)
    r = upload_track(client, b, gj, fmt="geojson")
    assert r.status_code == 200 and r.json()["accepted"] == 5 and r.json()["rejected"] == 0
    key = lambda m: [(f["t_utc"], f["lat"], f["lon"]) for f in client.get(f"{P}/missions/{m}/track").json()["fixes"]]
    assert key(b) == key(a)   # positions and times round-trip; speed, heading, HDOP and quality are not exported


def test_track_file_errors_and_partial_acceptance(client):
    mid = new_mission(client)
    r = upload_track(client, mid, (FX / "track.csv").read_bytes(), utc_offset_min=0)
    res = r.json()
    assert (res["accepted"], res["duplicates"], res["rejected"], res["reordered"]) == (5, 1, 2, 1)
    assert res["errors"][0].startswith("line 7") and res["fix_count"] == 5
    # all rows rejected -> 422 with the line numbers
    r = upload_track(client, mid, (FX / "track.csv").read_bytes())
    assert r.status_code == 200   # most rows have zones: only the naive one is refused
    r = upload_track(client, mid, "time,lat,lon\n2025-06-01 12:00:00,1,2\n2025-06-01 12:00:01,1,2\n")
    assert r.status_code == 422 and r.json()["detail"]["errors"][0].startswith("line 2") and r.json()["detail"]["rejected"] == 2
    assert upload_track(client, mid, "a,b\n1,2\n").status_code == 422
    assert upload_track(client, mid, b"\xff\xfe\x00", fmt="csv").status_code == 422
    assert upload_track(client, mid, "x", fmt="kml").status_code == 422
    assert upload_track(client, mid, "x", fmt="nmea", nmea_date="2025-13-40").status_code == 422
    assert upload_track(client, mid, "x", utc_offset_min=9999).status_code == 422


def test_nmea_gpx_geojson_uploads(client):
    mid = new_mission(client)
    n = upload_track(client, mid, (FX / "track.nmea").read_bytes(), "nmea").json()
    assert (n["accepted"], n["rejected"], n["format"]) == (3, 4, "nmea")
    g = upload_track(client, mid, (FX / "track.gpx").read_bytes(), "gpx").json()
    assert (g["accepted"], g["duplicates"], g["rejected"]) == (2, 2, 1)   # 12:00:00 and 12:00:10 already stored
    j = upload_track(client, mid, (FX / "track.geojson").read_bytes(), "geojson").json()
    assert (j["accepted"], j["duplicates"], j["rejected"]) == (2, 2, 3)
    track = client.get(f"{P}/missions/{mid}/track").json()
    times = [f["t_utc"] for f in track["fixes"]]
    assert times == sorted(times) and track["fix_count"] == len(times) == 7 and track["decimated"] is False
    assert {f["source"] for f in track["fixes"]} == {"nmea", "gpx", "geojson"}


def test_get_track_decimation(client):
    mid = new_mission(client)
    fixes = [{"t_utc": f"2025-06-01T{12 + i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z", "lat": 1e-6 * i * i / 100,
              "lon": 1e-4 * i} for i in range(600)]
    r = client.post(f"{P}/missions/{mid}/track", json={"fixes": fixes})
    assert r.status_code == 200 and r.json()["format"] == "json" and r.json()["accepted"] == 600
    t = client.get(f"{P}/missions/{mid}/track", params={"max_points": 50}).json()
    assert t["decimated"] is True and t["fix_count"] == 600 and len(t["fixes"]) == 50
    assert t["fixes"][0]["t_utc"].startswith("2025-06-01T12:00:00") and t["fixes"][-1]["t_utc"].startswith("2025-06-01T12:09:59")
    assert client.get(f"{P}/missions/{mid}/track", params={"max_points": 1000}).json()["decimated"] is False
    assert client.get(f"{P}/missions/{mid}/track", params={"max_points": 1}).status_code == 422
    # JSON naive timestamps are a schema error
    bad = client.post(f"{P}/missions/{mid}/track", json={"fixes": [{"t_utc": "2025-06-01T12:00:00", "lat": 0, "lon": 0}]})
    assert bad.status_code == 422


def test_media_limits_types_and_metadata(client):
    mid = new_mission(client)
    ok = make_image()
    up = lambda data, name="x.jpg", meta=None: client.post(
        f"{P}/missions/{mid}/media", files={"image": (name, data, "image/jpeg")}, data={"metadata": meta} if meta else {})
    assert up(ok).status_code == 201
    r = up(ok + b"\0" * 8_100_000)
    assert r.status_code == 413
    assert up(b"GIF89a" + b"\0" * 64, "cat.jpg").status_code == 415        # filename claims jpg, magic says GIF
    assert up(b"%PDF-1.4\n" + b"0" * 64).status_code == 415
    assert up(b"").status_code == 422
    assert up(ok[:40]).status_code == 422                                   # truncated JPEG
    assert up(ok, meta="{not json").status_code == 422
    assert up(ok, meta=json.dumps({"exif_utc_offset_min": 9999})).status_code == 422
    assert up(ok, meta=json.dumps({"surprise": 1})).status_code == 422
    assert up(ok, meta=json.dumps({"captured_utc": "2025-06-01T12:00:00", })).status_code == 422   # naive supplied time
    both = up(ok, meta=json.dumps({"captured_utc": "2025-06-01T12:00:00Z", "camera_clock_offset_s": 5}))
    assert both.status_code == 422
    # untrimmed names are sanitised, an image with no usable time is stored with a null time and a reason
    r = up(ok, name="../..\\evil.jpg")
    assert r.status_code == 201 and r.json()["filename"] == "evil.jpg" and r.json().get("captured_utc") is None
    assert "not guess" not in r.json()["time_note"] and "No usable" in r.json()["time_note"]
    sb = client.get(f"{P}/missions/{mid}/storyboard").json()
    nt = [e for e in sb["events"] if e.get("t_utc") is None]
    assert nt and sb["events"][-1] in nt and nt[0]["located"]["method"] in ("no_time",)


def test_image_count_and_report_caps(client, monkeypatch):
    from mooring.missions import store
    monkeypatch.setattr(store, "MAX_IMAGES", 2)
    monkeypatch.setattr(store, "MAX_REPORTS", 1)
    mid = new_mission(client)
    for i in range(2):
        assert client.post(f"{P}/missions/{mid}/media", files={"image": ("a.png", make_image("PNG"), "image/png")}).status_code == 201
    assert client.post(f"{P}/missions/{mid}/media", files={"image": ("a.png", make_image("PNG"), "image/png")}).status_code == 409
    rep = {"t_utc": "2025-06-01T12:00:00Z", "title": "t"}
    assert client.post(f"{P}/missions/{mid}/reports", json=rep).status_code == 201
    assert client.post(f"{P}/missions/{mid}/reports", json=rep).status_code == 409
    assert client.post(f"{P}/missions/{mid}/reports", json={**rep, "lat": 1}).status_code == 422   # lat without lon


def test_track_file_size_limit(client, monkeypatch):
    mid = new_mission(client)
    monkeypatch.setattr("modeling_api.routers.missions.MAX_TRACK_FILE_BYTES", 1000)
    assert upload_track(client, mid, "time,lat,lon\n" + "x" * 2000).status_code == 413


def test_empty_mission_storyboard_and_geojson(client):
    mid = new_mission(client)
    sb = client.get(f"{P}/missions/{mid}/storyboard").json()
    assert sb["stats"]["fix_count"] == 0 and sb["track"] == [] and sb["validity"]["reasons"][0]["code"] == "NO_TRACK"
    assert client.get(f"{P}/missions/{mid}/storyboard.geojson").json()["features"] == []


def test_ownership_and_unknown_missions_are_404(authed):
    c = authed
    mid = new_mission(c, A)
    upload_track(c, mid, csv_track(), headers=A)
    img = c.post(f"{P}/missions/{mid}/media", files={"image": ("a.jpg", make_image(), "image/jpeg")}, headers=A).json()
    assert c.post(f"{P}/missions/{mid}/reports", json={"t_utc": "2025-06-01T12:00:00Z", "title": "t"}, headers=A).status_code == 201
    paths = [("get", f"/missions/{mid}"), ("get", f"/missions/{mid}/track"), ("get", f"/missions/{mid}/media"),
             ("get", img["url"][len(P):]), ("get", f"/missions/{mid}/reports"), ("get", f"/missions/{mid}/storyboard"),
             ("get", f"/missions/{mid}/storyboard.geojson")]
    for _, path in paths:
        assert c.get(P + path, headers=A).status_code == 200, path
        assert c.get(P + path, headers=B).status_code == 404, path
        assert c.get(P + path.replace(mid, "mis_unknown"), headers=A).status_code == 404, path
    assert c.post(f"{P}/missions/{mid}/track", json={"fixes": [{"t_utc": "2025-06-01T12:00:00Z", "lat": 0, "lon": 0}]}, headers=B).status_code == 404
    assert upload_track(c, mid, csv_track(), headers=B).status_code == 404
    assert c.post(f"{P}/missions/{mid}/media", files={"image": ("a.jpg", make_image(), "image/jpeg")}, headers=B).status_code == 404
    assert c.post(f"{P}/missions/{mid}/reports", json={"t_utc": "2025-06-01T12:00:00Z", "title": "t"}, headers=B).status_code == 404
    assert mid not in c.get(f"{P}/missions", headers=B).text and mid in c.get(f"{P}/missions", headers=A).text
    # Bob's mission cannot be used to reach Alice's image
    bm = new_mission(c, B)
    assert c.get(f"{P}/missions/{bm}/media/{img['media_id']}", headers=B).status_code == 404
    assert c.get(f"{P}/missions/{mid}/track").status_code == 401   # no credentials at all


def test_upload_routes_have_their_own_bounded_body_limit_and_others_keep_the_default(client, monkeypatch):
    """Defaults: S5 uploads accept up to MOORING_MAX_UPLOAD_BYTES (32 MiB); every other route keeps 1 MiB."""
    monkeypatch.delenv("MOORING_MAX_BODY_BYTES", raising=False)
    monkeypatch.delenv("MOORING_MAX_UPLOAD_BYTES", raising=False)
    mid = new_mission(client)
    big_csv = csv_track() + ("#" + "x" * 1023 + "\n") * 3000          # ~3 MB: over the global default, under the upload limit
    r = upload_track(client, mid, big_csv)
    assert r.status_code != 413, r.text
    r = client.post(f"{P}/missions", json={"name": "x" * 2_000_000, "vessel_id": "v"})
    assert r.status_code == 413
    monkeypatch.setenv("MOORING_MAX_UPLOAD_BYTES", "1000")
    assert upload_track(client, mid, csv_track() * 20).status_code == 413
