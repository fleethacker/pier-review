"""Local-only controls: identity, ownership, limits, observations and recoverable storage."""
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from modeling_api.main import app
from modeling_api import security, state
from mooring.core import access, metrics, store
from mooring.core.backup import backup, restore
from mooring.core.envelopes import RESULTS, inputs_hash, resolved_inputs_hash
from mooring.core.jobs import JobQueueFull, JobStore
from mooring.examples import EXAMPLES

P="/api/v1"
A={"Authorization":"Bearer "+"a"*32}
B={"Authorization":"Bearer "+"b"*32}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOORING_API_KEYS",json.dumps({"alice":"a"*32,"bob":"b"*32}))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE","10000")
    monkeypatch.setattr(security,"RATE",security.RateLimit())
    return TestClient(app)


@contextmanager
def owner(name):
    token=access.principal.set(name); enforced=access.enforced.set(True)
    try: yield
    finally:
        access.principal.reset(token); access.enforced.reset(enforced)


def test_authentication_fails_closed_and_is_opt_in(client,monkeypatch):
    assert client.get(P+"/health").status_code==200
    assert client.get(P+"/version").status_code==401
    assert client.get(P+"/version",headers=A).status_code==200
    assert client.get(P+"/version",headers={"Authorization":"Bearer " + "x"*32}).status_code==401
    monkeypatch.setenv("MOORING_API_KEYS", "invalid")
    assert client.get(P+"/version",headers=A).status_code==503
    monkeypatch.delenv("MOORING_API_KEYS")
    monkeypatch.setenv("MOORING_AUTH_REQUIRED","1")
    assert client.get(P+"/version",headers=A).status_code==503
    monkeypatch.delenv("MOORING_AUTH_REQUIRED")
    assert client.get(P+"/version").status_code==200


def test_scenario_job_result_and_session_principal_separation(client):
    sid=client.post(P+"/scenarios",json=EXAMPLES["scenario"],headers=A).json()["scenario_id"]
    assert client.get(P+"/scenarios/"+sid,headers=A).status_code==200
    assert client.get(P+"/scenarios/"+sid,headers=B).status_code==404
    assert sid not in client.get(P+"/scenarios",headers=B).text
    loads=client.post(P+"/loads/environmental",json=EXAMPLES["loads_environmental"],headers=A).json()
    assert client.get(P+"/results/"+loads["result_id"],headers=A).status_code==200
    assert client.get(P+"/results/"+loads["result_id"],headers=B).status_code==404
    req={**EXAMPLES["berthing_simulate"],"scenario_id":sid,"duration_s":.2,"tug_commands":[],"line_events":[]}
    assert client.post(P+"/berthing/simulate",json=req,headers=B).status_code==404
    accepted=client.post(P+"/berthing/simulate",json=req,headers=A).json()
    jid=accepted["job_id"]
    state.JOBS.jobs[jid].future.result(timeout=5)
    result=client.get(accepted["status_url"],headers=A).json()
    assert result["state"]=="succeeded",result
    for path in (accepted["status_url"],accepted["events_url"],P+"/results/"+result["result"]["result_id"],P+f"/berthing/simulations/{jid}/series"):
        assert client.get(path,headers=A).status_code==200
        assert client.get(path,headers=B).status_code==404
    assert client.delete(accepted["status_url"],headers=B).status_code==404
    request={**EXAMPLES["berthing_session"],"scenario_id":sid}
    assert client.post(P+"/berthing/sessions",json=request,headers=B).status_code==404
    session=client.post(P+"/berthing/sessions",json=request,headers=A).json()
    assert session["validity"]["state"]=="limited"
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(session["ws_url"],headers=B): pass
    assert exc.value.code==4404
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(session["ws_url"]): pass
    assert exc.value.code==4401
    with client.websocket_connect(session["ws_url"]+"?limit=1",headers=A) as ws:
        assert ws.receive_json()["validity"]["state"]=="limited"
    assert state.SESSIONS[session["session_id"]].paused
    del state.SESSIONS[session["session_id"]]


def test_unowned_legacy_resources_are_not_claimed_on_read(client):
    rid="legacy-unowned-s21"
    store.db().execute("INSERT INTO results(result_id,envelope) VALUES (?,?)",(rid,json.dumps({"result_id":rid})))
    assert client.get(P+"/results/"+rid,headers=A).status_code==404
    assert client.get(P+"/results/"+rid,headers=B).status_code==404


def test_limits_are_principal_scoped_and_use_injected_clock(client,monkeypatch):
    clock=[0.0]
    monkeypatch.setattr(security,"RATE",security.RateLimit(clock=lambda:clock[0]))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE","2")
    for _ in range(2): assert client.get(P+"/version",headers=A).status_code==200
    limited=client.get(P+"/version",headers=A)
    assert limited.status_code==429 and int(limited.headers["Retry-After"])>0
    assert client.get(P+"/version",headers=B).status_code==200
    clock[0]=60
    assert client.get(P+"/version",headers=A).status_code==200
    monkeypatch.setenv("MOORING_MAX_BODY_BYTES","10")
    assert client.post(P+"/scenarios",content=b"x"*11,headers=B).status_code==413
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE","bad")
    assert client.get(P+"/version",headers=A).status_code==503


def test_worker_context_and_ownership_survive_restart(tmp_path,monkeypatch):
    d=store.Database(str(tmp_path/"work.sqlite"))
    monkeypatch.setattr(store,"db",lambda:d)
    jobs=JobStore("/api",workers=1,persist=True)
    try:
        with owner("alice"):
            def task(ctx):
                RESULTS["owned"]={"result_id":"owned","inputs_hash":"sha256:request"}
                return {"result_id":"owned"}
            acc=jobs.submit_task("ownership",task)
            jobs.jobs[acc.job_id].future.result(timeout=2)
            assert jobs.status(acc.job_id).state=="succeeded"
            restarted=JobStore("/api",persist=True)
            assert restarted.status(acc.job_id).result["result_id"]=="owned"
            assert RESULTS["owned"]["inputs_hash"]=="sha256:request"
        with owner("bob"):
            assert restarted.get(acc.job_id) is None and "owned" not in RESULTS
    finally:
        jobs.shutdown(); d.close()


def test_metrics_logs_saturation_and_cancelled_workers_remain_bounded(caplog):
    caplog.set_level(logging.INFO,logger="mooring.operations")
    before=metrics.snapshot()
    jobs=JobStore("/api",workers=1,queue_size=0)
    ready,release=threading.Event(),threading.Event()
    def task(ctx):
        ready.set(); assert release.wait(3)
        ctx.check_cancelled()
    try:
        acc=jobs.submit_task("bounded",task)
        assert ready.wait(2)
        with pytest.raises(JobQueueFull): jobs.submit_task("overflow",task)
        jobs.cancel(acc.job_id)
        # A cancelled but still running thread occupies capacity until it exits.
        with pytest.raises(JobQueueFull): jobs.submit_task("overflow",task)
        release.set(); jobs.jobs[acc.job_id].future.result(timeout=2)
        after=metrics.snapshot()
        assert after["queue_saturation"]>=before["queue_saturation"]+2
        assert after["cancellations"]==before["cancellations"]+1
        assert after["job_duration_seconds"]>=before["job_duration_seconds"]
        events=[json.loads(r.message) for r in caplog.records if r.name=="mooring.operations"]
        assert any(e.get("job_id")==acc.job_id and e["event"]=="job_finished" for e in events)
    finally: release.set(); jobs.shutdown()


def test_invalid_result_logs_validity_and_metrics_endpoint(client,caplog):
    caplog.set_level(logging.INFO,logger="mooring.operations")
    before=metrics.snapshot()["solver_failures"]
    with owner("alice"):
        RESULTS["invalid-observation"]={"result_id":"invalid-observation","validity":{"state":"invalid"}}
    assert metrics.snapshot()["solver_failures"]==before+1
    assert any(json.loads(r.message).get("validity")=="invalid" for r in caplog.records if r.name=="mooring.operations")
    result=client.get(P+"/metrics",headers=A)
    assert result.status_code==200
    assert {"queue_depth","queue_saturation","solver_failures","cancellations","job_duration_seconds"}<=result.json().keys()


def test_online_backup_restore_new_path_preserves_ids_hashes_and_ownership(tmp_path,monkeypatch):
    live=store.Database(str(tmp_path/"live.sqlite"))
    monkeypatch.setattr(store,"db",lambda:live)
    snapshot={"request":{"wind_speed_kt":15},"ship":{"class_id":"synthetic"}}
    rh=resolved_inputs_hash(snapshot)
    payload={"result_id":"backup-result","inputs_hash":inputs_hash(snapshot["request"]),"manifest":{"resolved_inputs_hash":rh}}
    with owner("alice"):
        RESULTS["backup-result"]=payload
        store.save_snapshot(rh,snapshot)
    backup_path=str(tmp_path/"backup.sqlite"); restored_path=str(tmp_path/"restored.sqlite")
    backup(live,backup_path)
    restore(backup_path,restored_path)
    with pytest.raises(FileExistsError): restore(backup_path,restored_path)
    with pytest.raises(FileExistsError): backup(live,backup_path)
    restored=store.Database(restored_path)
    monkeypatch.setattr(store,"db",lambda:restored)
    try:
        with owner("alice"):
            assert RESULTS["backup-result"]==payload
            assert resolved_inputs_hash(store.load_snapshot(rh))==rh
        with owner("bob"): assert "backup-result" not in RESULTS
        assert restored.schema_version()==len(store.MIGRATIONS)
    finally: live.close(); restored.close()


def test_v1_backup_migrates_copy_without_modifying_source(tmp_path):
    source=str(tmp_path/"v1.sqlite"); target=str(tmp_path/"current.sqlite")
    with sqlite3.connect(source) as conn:
        conn.executescript("CREATE TABLE schema_version(version INTEGER NOT NULL); INSERT INTO schema_version VALUES(1);"+store.MIGRATIONS[0])
        conn.execute("INSERT INTO results(result_id,inputs_hash,envelope) VALUES (?,?,?)",("old-id","sha256:old",'{"result_id":"old-id"}'))
    restore(source,target)
    d=store.Database(target)
    try:
        assert d.schema_version()==len(store.MIGRATIONS)
        assert d.execute("SELECT result_id,inputs_hash FROM results")==[("old-id","sha256:old")]
        assert d.execute("SELECT * FROM ownership")==[]
        assert d.execute("SELECT * FROM jobs")==[]
        with sqlite3.connect(source) as conn: assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]==1
    finally: d.close()


@pytest.mark.parametrize("payload,code", [(b"{}",1003),("x"*8193,1009),('{"type":"pause","unexpected":true}',1008)])
def test_websocket_rejects_bad_messages_without_damaging_session(client,monkeypatch,payload,code):
    import asyncio
    from modeling_api.sim_sessions import Session
    async def no_ticks(self): await asyncio.Event().wait()
    monkeypatch.setattr(Session,"run",no_ticks)
    sid=client.post(P+"/scenarios",json=EXAMPLES["scenario"],headers=A).json()["scenario_id"]
    response=client.post(P+"/berthing/sessions",json={**EXAMPLES["berthing_session"],"scenario_id":sid},headers=A)
    session=response.json(); model=state.SESSIONS[session["session_id"]].model
    initial=model.integrator.state
    with client.websocket_connect(session["ws_url"],headers=A) as ws:
        ws.receive_json()
        if isinstance(payload,bytes): ws.send_bytes(payload)
        else: ws.send_text(payload)
        # rm0-v1 may still deliver queued lifecycle/frame messages before the close.
        with pytest.raises(WebSocketDisconnect) as exc:
            while True: ws.receive_json()
        assert exc.value.code==code
    assert model.integrator.state==initial and model.t==0
    assert state.SESSIONS[session["session_id"]].connection is None
    del state.SESSIONS[session["session_id"]]
