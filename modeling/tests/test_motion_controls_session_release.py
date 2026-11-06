"""A completed DELETE and TTL cleanup may observe the same disconnected session."""
import threading
import pytest

from test_motion_controls_physics import model  # noqa: F401
from modeling_api import sim_sessions


def test_expiry_tolerates_concurrent_completed_release(model):
    session=sim_sessions.Session(model,session_id="old",clock=lambda:0)
    session.last_access=-10000
    sessions={"old":session}
    persisted,deleted=threading.Event(),threading.Event()
    original=session.persist
    def persist(*args,**kwargs):
        original(*args,**kwargs)
        persisted.set()
        assert deleted.wait(2)
    session.persist=persist
    failures=[]
    def expire_create():
        try:
            sim_sessions.create(sessions,"new",model.clone_for_prediction())
        except Exception as exc:
            failures.append(exc)
    worker=threading.Thread(target=expire_create)
    worker.start()
    assert persisted.wait(2)
    with session.lock:
        session.released=True
        del sessions["old"]
    deleted.set();worker.join(2)
    assert not worker.is_alive()
    assert not failures,repr(failures)
    assert "new" in sessions


def test_expiry_tombstones_retained_socket_reference(model):
    expired=sim_sessions.Session(model,session_id="expired",clock=lambda:0)
    expired.last_access=-10000
    sessions={"expired":expired}
    sim_sessions.create(sessions,"new",model.clone_for_prediction())
    assert "expired" not in sessions and expired.released
    with pytest.raises(ValueError,match="session released"):
        expired.attach("delayed socket")
