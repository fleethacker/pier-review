"""The exercise simulator's support endpoints: shared scenario library, public map token, client error log."""

import logging

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from modeling_api.routers import exercise

P = "/api/v1/exercise"
client = TestClient(app)
SCENARIO = {"id": "x", "name": "Test run", "description": "d", "units": [{"id": "a"}, {"id": "b"}]}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("EXERCISE_DATA_DIR", str(tmp_path / "lib"))
    exercise._recent.clear()
    return tmp_path / "lib"


def test_not_in_the_contract():
    assert not any("/exercise" in p for p in client.get("/openapi.json").json()["paths"])


def test_config_hands_out_only_public_tokens(monkeypatch):
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    monkeypatch.delenv("VITE_MAPBOX_TOKEN", raising=False)
    assert client.get(f"{P}/config").json() == {"mapboxToken": None}
    monkeypatch.setenv("VITE_MAPBOX_TOKEN", " pk.abc.def ")
    assert client.get(f"{P}/config").json() == {"mapboxToken": "pk.abc.def"}
    monkeypatch.setenv("MAPBOX_TOKEN", "sk.secret.value")
    assert client.get(f"{P}/config").json() == {"mapboxToken": None}, "a secret token is never served"


def test_save_list_load_delete():
    assert client.get(f"{P}/scenarios").json() == []
    saved = client.put(f"{P}/scenarios/test-run", json={"scenario": SCENARIO})
    assert saved.status_code == 200
    assert saved.json()["created"] is True
    listing = client.get(f"{P}/scenarios").json()
    assert listing == [{"id": "test-run", "name": "Test run", "description": "d", "units": 2, "updatedAt": saved.json()["updatedAt"]}]
    loaded = client.get(f"{P}/scenarios/test-run").json()
    assert loaded["scenario"] == SCENARIO
    assert loaded["updatedAt"] == saved.json()["updatedAt"]
    assert client.delete(f"{P}/scenarios/test-run").status_code == 204
    assert client.get(f"{P}/scenarios/test-run").status_code == 404
    assert client.delete(f"{P}/scenarios/test-run").status_code == 404


def test_newest_first():
    import os

    client.put(f"{P}/scenarios/old", json={"scenario": {**SCENARIO, "name": "Old"}})
    client.put(f"{P}/scenarios/new", json={"scenario": {**SCENARIO, "name": "New"}})
    os.utime(exercise.data_dir() / "old.json", (1, 1))
    assert [s["id"] for s in client.get(f"{P}/scenarios").json()] == ["new", "old"]


def test_overwrite_is_refused_if_someone_else_saved_first():
    import os

    first = client.put(f"{P}/scenarios/a", json={"scenario": SCENARIO}).json()
    # Someone else saves in between.
    os.utime(exercise.data_dir() / "a.json", (1_900_000_000, 1_900_000_000))
    stale = client.put(f"{P}/scenarios/a", json={"scenario": {**SCENARIO, "name": "Mine"}, "baseUpdatedAt": first["updatedAt"]})
    assert stale.status_code == 409
    assert client.get(f"{P}/scenarios/a").json()["scenario"]["name"] == "Test run"
    current = client.get(f"{P}/scenarios/a").json()["updatedAt"]
    ok = client.put(f"{P}/scenarios/a", json={"scenario": {**SCENARIO, "name": "Mine"}, "baseUpdatedAt": current})
    assert ok.status_code == 200 and ok.json()["created"] is False
    # Without a base it simply overwrites.
    assert client.put(f"{P}/scenarios/a", json={"scenario": SCENARIO}).status_code == 200


@pytest.mark.parametrize("bad", ["../etc/passwd", "UPPER", "-lead", "a" * 65, "has space", ".hidden"])
def test_ids_cannot_escape_the_library(bad):
    assert client.put(f"{P}/scenarios/{bad}", json={"scenario": SCENARIO}).status_code in (404, 405, 422)
    assert client.get(f"{P}/scenarios/{bad}").status_code in (404, 405, 422)


def test_rejects_things_that_are_not_scenarios_or_are_too_big():
    assert client.put(f"{P}/scenarios/a", json={"scenario": {"name": "", "units": []}}).status_code == 422
    assert client.put(f"{P}/scenarios/a", json={"scenario": {"name": "x"}}).status_code == 422
    assert client.put(f"{P}/scenarios/a", json={"scenario": {"name": "x", "units": ["y" * 2000] * 600}}).status_code == 413
    assert client.put(f"{P}/scenarios/a", json={"nope": 1}).status_code == 422


def test_library_has_a_limit(monkeypatch):
    monkeypatch.setattr(exercise, "MAX_SCENARIOS", 2)
    for i in range(2):
        assert client.put(f"{P}/scenarios/s{i}", json={"scenario": SCENARIO}).status_code == 200
    assert client.put(f"{P}/scenarios/s9", json={"scenario": SCENARIO}).status_code == 409
    assert client.put(f"{P}/scenarios/s0", json={"scenario": SCENARIO}).status_code == 200, "replacing one is fine"


def test_skips_files_that_are_not_scenarios(store):
    client.put(f"{P}/scenarios/ok", json={"scenario": SCENARIO})
    (store / "junk.json").write_text("not json")
    (store / "list.json").write_text("[1,2]")
    assert [s["id"] for s in client.get(f"{P}/scenarios").json()] == ["ok"]


def test_client_errors_are_logged_and_capped(caplog):
    caplog.set_level(logging.WARNING, logger="exercise")
    r = client.post(f"{P}/client-errors", json={"kind": "webgl", "message": "context lost\nagain", "page": "/", "userAgent": "UA"})
    assert r.status_code == 204
    assert "[webgl] context lost again" in caplog.text
    assert client.post(f"{P}/client-errors", json={"kind": "x" * 41, "message": "m"}).status_code == 422
    assert client.post(f"{P}/client-errors", json={"kind": "x", "message": "m" * 1001}).status_code == 422
    caplog.clear()
    for _ in range(exercise.MAX_ERRORS_PER_MINUTE + 20):
        client.post(f"{P}/client-errors", json={"kind": "spam", "message": "m"})
    assert caplog.text.count("[spam]") == exercise.MAX_ERRORS_PER_MINUTE - 1  # one slot was used by the report above


def test_falls_back_when_the_chosen_place_cannot_be_written(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("EXERCISE_DATA_DIR", str(blocker / "sub"))
    assert client.get(f"{P}/scenarios").status_code == 503
